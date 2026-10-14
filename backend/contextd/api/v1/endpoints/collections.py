"""API endpoints for collections."""

import asyncio
import logging
from typing import List, Sequence

from fastapi import Depends, HTTPException, Path, Query
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud, schemas
from contextd.api import deps
from contextd.api.context import ApiContext
from contextd.api.examples import (
    create_collection_list_response,
    create_job_list_response,
)
from contextd.api.router import TrailingSlashRouter
from contextd.core.collection_service import collection_service
from contextd.core.guard_rail_service import GuardRailService
from contextd.core.logging import ContextualLogger
from contextd.core.shared_models import ActionType
from contextd.core.source_connection_service import source_connection_service
from contextd.models import (
    Cohort,
    Collection,
    Connection,
    ContextDecision,
    ContextDriftSignal,
    ContextForgeMappingArtifact,
    ContextLineageEdge,
    ContextQueryDecisionTrace,
    ContextTemporalFact,
    Entity,
    EntityAliasMapping,
    EntityCount,
    GraphEvent,
    IntegrationCredential,
    PgFieldCatalogColumn,
    PgFieldCatalogTable,
    SearchQuery,
    SourceConnection,
    SourceConnectionSetupDraft,
    Sync,
    SyncConnection,
    SyncCursor,
    SyncJob,
    SyncState,
)
from contextd.platform.cleanup import cleanup_service
from contextd.platform.graph.factory import get_graph_driver

router = TrailingSlashRouter()
logger = logging.getLogger(__name__)


_DRIFT_SEVERITY_RANK = {
    "clean": 0,
    "none": 0,
    "ok": 0,
    "info": 1,
    "warning": 2,
    "critical": 3,
}


def _worst_severity(current: str, candidate: str) -> str:
    current_value = (current or "clean").lower()
    candidate_value = (candidate or "clean").lower()
    return (
        candidate_value
        if _DRIFT_SEVERITY_RANK.get(candidate_value, 0)
        > _DRIFT_SEVERITY_RANK.get(current_value, 0)
        else current_value
    )


async def _drop_collection_graph_database(readable_id: str, ctx: ApiContext) -> None:
    """Drop the isolated Neo4j database for a collection.

    Graph cleanup should never block SQL deletion. Neo4j can refuse drops while a
    database is still starting/stopping, so failures are logged and the database
    deletion remains authoritative.
    """
    async def _drop() -> None:
        driver = await get_graph_driver()
        await driver.connect()
        await driver.drop_context_database(ctx.organization.id, readable_id)

    try:
        await asyncio.wait_for(_drop(), timeout=15)
    except asyncio.TimeoutError:  # pragma: no cover - best-effort external cleanup
        logger.warning(
            "Timed out dropping ContextD graph database for collection %s; SQL deletion will continue",
            readable_id,
        )
    except Exception as exc:  # pragma: no cover - best-effort external cleanup
        logger.warning(
            "Unable to drop ContextD graph database for collection %s: %s",
            readable_id,
            exc,
        )


async def _delete_collection_rows(
    db: AsyncSession,
    db_obj: Collection,
    sync_ids: Sequence,
    ctx: ApiContext,
) -> None:
    """Delete collection-owned rows without invoking ORM delete hooks.

    The ORM cascade path can trigger source/sync before-delete listeners and stall
    large collection deletes. Bulk SQL deletes keep the operation deterministic and
    let database-level FKs do the remaining cleanup.
    """
    source_rows = await db.execute(
        select(SourceConnection.id, SourceConnection.connection_id)
        .where(
            SourceConnection.organization_id == ctx.organization.id,
            SourceConnection.readable_collection_id == db_obj.readable_id,
        )
    )
    source_connection_ids = [row[0] for row in source_rows]
    connection_ids = [row[1] for row in source_rows if row[1]]

    credential_ids = []
    if connection_ids:
        credential_rows = await db.execute(
            select(Connection.integration_credential_id)
            .where(Connection.id.in_(connection_ids))
        )
        credential_ids = [row[0] for row in credential_rows if row[0]]

    catalog_table_ids = []
    if source_connection_ids:
        catalog_table_rows = await db.execute(
            select(PgFieldCatalogTable.id)
            .where(PgFieldCatalogTable.source_connection_id.in_(source_connection_ids))
        )
        catalog_table_ids = [row[0] for row in catalog_table_rows]

    try:
        # Collection-scoped intelligence and query artifacts.
        for model in (
            ContextQueryDecisionTrace,
            ContextDriftSignal,
            ContextDecision,
            ContextLineageEdge,
            ContextTemporalFact,
        ):
            await db.execute(
                sa_delete(model).where(
                    model.organization_id == ctx.organization.id,
                    model.collection_readable_id == db_obj.readable_id,
                )
            )

        await db.execute(
            sa_delete(ContextForgeMappingArtifact).where(
                ContextForgeMappingArtifact.organization_id == ctx.organization.id,
                ContextForgeMappingArtifact.target_collection_id == db_obj.readable_id,
            )
        )
        await db.execute(
            sa_delete(SourceConnectionSetupDraft).where(
                SourceConnectionSetupDraft.organization_id == ctx.organization.id,
                SourceConnectionSetupDraft.target_collection_id == db_obj.readable_id,
            )
        )

        if source_connection_ids:
            await db.execute(
                sa_delete(ContextForgeMappingArtifact).where(
                    ContextForgeMappingArtifact.organization_id == ctx.organization.id,
                    ContextForgeMappingArtifact.source_connection_id.in_(source_connection_ids),
                )
            )
            await db.execute(
                sa_delete(SourceConnectionSetupDraft).where(
                    SourceConnectionSetupDraft.organization_id == ctx.organization.id,
                    SourceConnectionSetupDraft.finalized_source_connection_id.in_(
                        source_connection_ids
                    ),
                )
            )

        if catalog_table_ids:
            await db.execute(
                sa_delete(PgFieldCatalogColumn).where(
                    PgFieldCatalogColumn.table_id.in_(catalog_table_ids)
                )
            )
        if source_connection_ids:
            await db.execute(
                sa_delete(PgFieldCatalogTable).where(
                    PgFieldCatalogTable.source_connection_id.in_(source_connection_ids)
                )
            )

        # Sync-scoped operational rows. Bulk deletes avoid SourceConnection/Sync
        # model event listeners while preserving the same final state.
        if sync_ids:
            await db.execute(
                sa_delete(ContextDriftSignal).where(
                    ContextDriftSignal.organization_id == ctx.organization.id,
                    ContextDriftSignal.sync_id.in_(sync_ids),
                )
            )

            await db.execute(sa_delete(GraphEvent).where(GraphEvent.sync_id.in_(sync_ids)))
            await db.execute(sa_delete(SyncState).where(SyncState.sync_id.in_(sync_ids)))
            await db.execute(sa_delete(Entity).where(Entity.sync_id.in_(sync_ids)))
            await db.execute(sa_delete(EntityCount).where(EntityCount.sync_id.in_(sync_ids)))
            await db.execute(sa_delete(SyncCursor).where(SyncCursor.sync_id.in_(sync_ids)))
            await db.execute(sa_delete(SyncConnection).where(SyncConnection.sync_id.in_(sync_ids)))
            await db.execute(
                sa_delete(EntityAliasMapping).where(
                    EntityAliasMapping.organization_id == ctx.organization.id,
                    EntityAliasMapping.last_seen_sync_id.in_(sync_ids),
                )
            )
            await db.execute(sa_delete(SyncJob).where(SyncJob.sync_id.in_(sync_ids)))

        if source_connection_ids:
            await db.execute(
                sa_delete(SourceConnection).where(
                    SourceConnection.organization_id == ctx.organization.id,
                    SourceConnection.id.in_(source_connection_ids),
                )
            )

        if sync_ids:
            await db.execute(
                sa_delete(Sync).where(
                    Sync.organization_id == ctx.organization.id,
                    Sync.id.in_(sync_ids),
                )
            )

        if connection_ids:
            await db.execute(
                sa_delete(Connection).where(
                    Connection.organization_id == ctx.organization.id,
                    Connection.id.in_(connection_ids),
                )
            )

        if credential_ids:
            still_referenced = (
                select(Connection.id)
                .where(Connection.integration_credential_id == IntegrationCredential.id)
                .exists()
            )
            await db.execute(
                sa_delete(IntegrationCredential).where(
                    IntegrationCredential.organization_id == ctx.organization.id,
                    IntegrationCredential.id.in_(credential_ids),
                    ~still_referenced,
                )
            )

        await db.execute(sa_delete(SearchQuery).where(SearchQuery.collection_id == db_obj.id))
        await db.execute(sa_delete(Cohort).where(Cohort.collection_id == db_obj.id))
        result = await db.execute(
            sa_delete(Collection).where(
                Collection.organization_id == ctx.organization.id,
                Collection.id == db_obj.id,
            )
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Collection not found")

        await db.commit()
    except Exception:
        await db.rollback()
        raise


@router.get(
    "/",
    response_model=List[schemas.Collection],
    responses=create_collection_list_response(
        ["finance_data"],
        "Finance data collection",
    ),
)
async def list(
    skip: int = Query(0, description="Number of collections to skip for pagination"),
    limit: int = Query(
        100, description="Maximum number of collections to return (1-1000)", le=1000, ge=1
    ),
    search: str = Query(None, description="Search term to filter by name or readable_id"),
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
) -> List[schemas.Collection]:
    """List all collections that belong to your organization with optional search filtering.

    Collections are always sorted by creation date (newest first).
    """
    collections = await crud.collection.get_multi(
        db,
        ctx=ctx,
        skip=skip,
        limit=limit,
        search_query=search,
    )
    return collections


@router.get("/count", response_model=int)
async def count(
    search: str = Query(None, description="Search term to filter by name or readable_id"),
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
) -> int:
    """Get total count of collections for the organization with optional search filtering."""
    return await crud.collection.count(db, ctx=ctx, search_query=search)


@router.get("/dashboard-status")
async def dashboard_status(
    readable_ids: List[str] | None = Query(
        None,
        description="Readable collection IDs to summarize for the dashboard page",
    ),
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
) -> dict[str, dict]:
    """Return lightweight native dashboard state for a page of collections.

    This endpoint intentionally avoids invoking per-database summary builders. It
    reads the native drift-signal table and latest graph-event commit state in a
    single batch so dashboard counters can stay accurate without polling every
    connector or reloading the page.
    """
    requested_ids = [
        value.strip()
        for value in dict.fromkeys(readable_ids or [])
        if value and value.strip()
    ][:100]
    if not requested_ids:
        return {}

    collection_rows = await db.execute(
        select(Collection.readable_id)
        .where(Collection.organization_id == ctx.organization.id)
        .where(Collection.readable_id.in_(requested_ids))
    )
    collection_ids = [row[0] for row in collection_rows]

    payload: dict[str, dict] = {
        readable_id: {
            "drift": {
                "active_count": 0,
                "severity": "clean",
                "status": "clean",
            },
            "graph": {
                "pending_events": 0,
                "failed_events": 0,
            },
        }
        for readable_id in collection_ids
    }
    if not collection_ids:
        return payload

    drift_rows = await db.execute(
        select(
            ContextDriftSignal.collection_readable_id,
            ContextDriftSignal.severity,
            func.count(ContextDriftSignal.id).label("signal_count"),
        )
        .where(ContextDriftSignal.organization_id == ctx.organization.id)
        .where(ContextDriftSignal.collection_readable_id.in_(collection_ids))
        .where(ContextDriftSignal.status == "active")
        .where(ContextDriftSignal.resolved_at.is_(None))
        .where(ContextDriftSignal.severity.notin_(("clean", "none", "ok")))
        .group_by(ContextDriftSignal.collection_readable_id, ContextDriftSignal.severity)
    )
    for row in drift_rows:
        drift = payload[row.collection_readable_id]["drift"]
        drift["active_count"] += int(row.signal_count or 0)
        drift["severity"] = _worst_severity(drift["severity"], row.severity)
        drift["status"] = "changed" if drift["active_count"] else "clean"

    latest_job_subq = (
        select(
            SourceConnection.readable_collection_id.label("readable_id"),
            SourceConnection.sync_id.label("sync_id"),
            SyncJob.id.label("sync_job_id"),
            func.row_number()
            .over(
                partition_by=SourceConnection.sync_id,
                order_by=SyncJob.created_at.desc(),
            )
            .label("rn"),
        )
        .join(SyncJob, SyncJob.sync_id == SourceConnection.sync_id)
        .where(SourceConnection.organization_id == ctx.organization.id)
        .where(SourceConnection.readable_collection_id.in_(collection_ids))
        .where(SourceConnection.sync_id.isnot(None))
        .subquery()
    )
    graph_rows = await db.execute(
        select(
            latest_job_subq.c.readable_id,
            GraphEvent.commit_status,
            func.count(GraphEvent.id).label("event_count"),
        )
        .join(GraphEvent, GraphEvent.sync_job_id == latest_job_subq.c.sync_job_id)
        .where(latest_job_subq.c.rn == 1)
        .where(GraphEvent.organization_id == ctx.organization.id)
        .where(GraphEvent.commit_status.in_(("pending", "failed")))
        .group_by(latest_job_subq.c.readable_id, GraphEvent.commit_status)
    )
    for row in graph_rows:
        graph = payload[row.readable_id]["graph"]
        if row.commit_status == "pending":
            graph["pending_events"] += int(row.event_count or 0)
        elif row.commit_status == "failed":
            graph["failed_events"] += int(row.event_count or 0)

    return payload


@router.post("/", response_model=schemas.Collection)
async def create(
    collection: schemas.CollectionCreate,
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
) -> schemas.Collection:
    """Create a new collection.

    The newly created collection is initially empty and does not contain any data
    until you explicitly add source connections to it.
    """
    # Create the collection
    collection_obj = await collection_service.create(db, collection_in=collection, ctx=ctx)

    ctx.analytics.track_event(
        "collection_created",
        {
            "collection_id": str(collection_obj.id),
            "collection_name": collection_obj.name,
        },
    )

    return collection_obj


@router.get("/{readable_id}", response_model=schemas.Collection)
async def get(
    readable_id: str = Path(
        ...,
        description="The unique readable identifier of the collection (e.g., 'finance-data-ab123')",
    ),
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
) -> schemas.Collection:
    """Retrieve a specific collection by its readable ID."""
    db_obj = await crud.collection.get_by_readable_id(db, readable_id=readable_id, ctx=ctx)
    if db_obj is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    return db_obj


@router.patch("/{readable_id}", response_model=schemas.Collection)
async def update(
    collection: schemas.CollectionUpdate,
    readable_id: str = Path(
        ..., description="The unique readable identifier of the collection to update"
    ),
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
) -> schemas.Collection:
    """Update a collection's properties.

    Modifies the display name of an existing collection.
    Note that the readable ID cannot be changed after creation to maintain stable
    API endpoints and preserve any existing integrations or bookmarks.
    """
    db_obj = await crud.collection.get_by_readable_id(db, readable_id=readable_id, ctx=ctx)
    if db_obj is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    return await crud.collection.update(db, db_obj=db_obj, obj_in=collection, ctx=ctx)


@router.delete("/{readable_id}", response_model=schemas.Collection)
async def delete(
    readable_id: str = Path(
        ..., description="The unique readable identifier of the collection to delete"
    ),
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
) -> schemas.Collection:
    """Delete a collection and all associated data.

    Permanently removes a collection from your organization including all synced data
    from the destination systems. All source connections within this collection
    will also be deleted as part of the cleanup process. This action cannot be undone.
    """
    # Find the collection
    db_obj = await crud.collection.get_by_readable_id(db, readable_id=readable_id, ctx=ctx)
    if db_obj is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    # Convert to schema for cleanup service
    collection_schema = schemas.Collection.model_validate(db_obj, from_attributes=True)

    # Collect sync IDs before cascading deletes remove the rows
    sync_id_rows: Sequence = await db.execute(
        select(SourceConnection.sync_id)
        .where(
            SourceConnection.organization_id == ctx.organization.id,
            SourceConnection.readable_collection_id == db_obj.readable_id,
            SourceConnection.sync_id.is_not(None),
        )
        .distinct()
    )
    sync_ids = [row[0] for row in sync_id_rows if row[0]]

    # Clean up all external data (schedules, destinations, ARF)
    await cleanup_service.cleanup_collection(db, collection_schema, sync_ids, ctx)
    logger.info("Collection %s external cleanup complete; dropping graph database", readable_id)
    await _drop_collection_graph_database(readable_id, ctx)
    logger.info("Collection %s graph cleanup returned; deleting SQL rows", readable_id)

    await _delete_collection_rows(db, db_obj, sync_ids, ctx)
    logger.info("Collection %s SQL rows deleted", readable_id)
    return collection_schema


@router.post(
    "/{readable_id}/refresh_all",
    response_model=List[schemas.SourceConnectionJob],
    responses=create_job_list_response(["completed"], "Multiple sync jobs triggered"),
)
async def refresh_all_source_connections(
    *,
    readable_id: str = Path(
        ..., description="The unique readable identifier of the collection to refresh"
    ),
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
    guard_rail: GuardRailService = Depends(deps.get_guard_rail_service),
    logger: ContextualLogger = Depends(deps.get_logger),
) -> List[schemas.SourceConnectionJob]:
    """Trigger data synchronization for all source connections in the collection.

    The sync jobs run asynchronously in the background, so this endpoint
    returns immediately with job details that you can use to track progress. You can
    monitor the status of individual data synchronization using the source connection
    endpoints.
    """
    # Check if collection exists
    collection = await crud.collection.get_by_readable_id(db, readable_id=readable_id, ctx=ctx)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    source_connections = await source_connection_service.list(
        db,
        ctx=ctx,
        readable_collection_id=readable_id,
        limit=1000,
    )

    if not source_connections:
        return []

    # Check if we're allowed to process entities
    await guard_rail.is_allowed(ActionType.ENTITIES)

    sync_jobs = []
    errors = []
    for sc in source_connections:
        try:
            sync_jobs.append(
                await source_connection_service.run(
                    db,
                    id=sc.id,
                    ctx=ctx,
                )
            )
        except Exception as e:
            logger.error(
                "Failed to trigger refresh for source connection %s in collection %s: %s",
                sc.id,
                readable_id,
                e,
            )
            errors.append(f"{sc.name}: {e}")

    if errors and not sync_jobs:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to trigger refresh for every source connection: {'; '.join(errors)}",
        )

    return sync_jobs
