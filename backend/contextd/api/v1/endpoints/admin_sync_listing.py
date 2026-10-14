"""Admin sync listing endpoint and helpers."""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from contextd.api import deps
from contextd.api.context import ApiContext
from contextd.api.router import TrailingSlashRouter
from contextd.api.v1.endpoints.admin_access import (
    require_admin_permission as _require_admin_permission,
)
from contextd.api.v1.endpoints.admin_sync_listing_helpers import (
    AdminSyncInfo,
    _build_admin_sync_info_list,
)
from contextd.core.shared_models import FeatureFlag as FeatureFlagEnum

router = TrailingSlashRouter()


@router.get("/syncs", response_model=List[AdminSyncInfo])
async def admin_list_all_syncs(
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
    skip: int = Query(0, description="Number of syncs to skip"),
    limit: int = Query(100, le=1000, description="Maximum number of syncs to return"),
    sync_ids: Optional[str] = Query(
        None, description="Comma-separated list of sync IDs to filter by"
    ),
    organization_id: Optional[UUID] = Query(None, description="Filter by organization ID"),
    collection_id: Optional[str] = Query(
        None, description="Filter by collection readable ID (exact match)"
    ),
    source_type: Optional[str] = Query(None, description="Filter by source short name"),
    has_source_connection: bool = Query(
        True,
        description="Include only syncs with source connections (excludes orphaned syncs by default)",
    ),
    is_authenticated: Optional[bool] = Query(
        None,
        description="Filter by source connection authentication status (true=authenticated, false=needs reauth)",
    ),
    status: Optional[str] = Query(
        None, description="Filter by sync status (active, inactive, error)"
    ),
    last_job_status: Optional[str] = Query(
        None,
        description="Filter by last job status (completed, failed, running, pending, cancelled)",
    ),
    ghost_syncs_last_n: Optional[int] = Query(
        None,
        ge=1,
        le=10,
        description="Filter to 'ghost syncs' - syncs where the last N jobs all failed (e.g., 5 for last 5 failures)",
    ),
    include_destination_counts: bool = Query(
        False,
        description="Include destination search index counts when available",
    ),
) -> List[AdminSyncInfo]:
    """Admin-only: List all syncs across organizations with entity counts.

    Supports extensive filtering for migration and monitoring purposes.

    **Note**: Orphaned syncs (deleted source connections) are excluded by default.
    Set `has_source_connection=false` to see only orphaned syncs.

    **All filters are optional** except `has_source_connection` which defaults to true.

    **Entity Counts**:
        - total_entity_count: Count from Postgres (EntityCount table)
        - total_arf_entity_count: Count from ARF storage (may be None if ARF unavailable)
        - total_search_index_entity_count: Reserved for future (currently None)

    Filters:
        - sync_ids: Comma-separated list of sync UUIDs (e.g., 'uuid1,uuid2,uuid3')
        - organization_id: Filter by organization UUID
        - collection_id: Filter by collection readable ID (exact match)
        - source_type: Filter by source short name (e.g., 'linear', 'github')
        - has_source_connection: Include syncs with source connections (default: true)
        - is_authenticated: Filter by authentication status (true=active, false=needs reauth)
        - status: Filter by sync status (active, inactive, error)
        - last_job_status: Filter by last job status (any job type)
        - exclude_failed_last_n: Exclude syncs where last N non-running jobs all failed
        - include_destination_counts: Include destination search index counts when available

    Args:
        db: Database session
        ctx: API context
        skip: Number of syncs to skip for pagination
        limit: Maximum number of syncs to return
        sync_ids: Optional comma-separated list of sync IDs
        organization_id: Optional filter by organization ID
        collection_id: Optional filter by collection readable ID
        source_type: Optional filter by source short name
        has_source_connection: Include syncs with source connections (default true)
        is_authenticated: Optional filter by authentication status
        status: Optional filter by sync status
        last_job_status: Optional filter by last job status
        exclude_failed_last_n: Optional exclude syncs with N consecutive failures
        include_destination_counts: Whether to include destination search index counts

    Returns:
        List of syncs with extended information including entity counts

    Raises:
        HTTPException: If not admin
    """
    from sqlalchemy import func
    from sqlalchemy import select as sa_select

    from contextd.core.shared_models import SyncStatus
    from contextd.models.connection import Connection
    from contextd.models.entity_count import EntityCount
    from contextd.models.source_connection import SourceConnection
    from contextd.models.sync import Sync
    from contextd.models.sync_connection import SyncConnection
    from contextd.models.sync_job import SyncJob

    _require_admin_permission(ctx, FeatureFlagEnum.API_KEY_ADMIN_SYNC)

    # Parse sync_ids if provided
    parsed_sync_ids: Optional[List[UUID]] = None
    if sync_ids:
        try:
            parsed_sync_ids = [UUID(sid.strip()) for sid in sync_ids.split(",") if sid.strip()]
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid sync_ids format. Must be comma-separated UUIDs: {e}",
            )

    # Build base query for syncs
    query = sa_select(Sync)

    # Apply SQL-level filters
    if parsed_sync_ids:
        query = query.where(Sync.id.in_(parsed_sync_ids))

    if organization_id:
        query = query.where(Sync.organization_id == organization_id)

    if status is not None:
        # Validate status value
        try:
            status_enum = SyncStatus(status.lower())
            query = query.where(Sync.status == status_enum)
        except ValueError:
            # Invalid status value, return empty result
            return []

    # Source connection filters using subqueries to avoid JOIN duplication
    if has_source_connection:
        # Only syncs that have a source connection
        query = query.where(
            Sync.id.in_(
                sa_select(SourceConnection.sync_id).where(SourceConnection.sync_id.isnot(None))
            )
        )
    else:
        # Only orphaned syncs (no source connection)
        query = query.where(
            Sync.id.notin_(
                sa_select(SourceConnection.sync_id).where(SourceConnection.sync_id.isnot(None))
            )
        )

    if is_authenticated is not None:
        query = query.where(
            Sync.id.in_(
                sa_select(SourceConnection.sync_id).where(
                    SourceConnection.is_authenticated == is_authenticated
                )
            )
        )

    if collection_id is not None:
        query = query.where(
            Sync.id.in_(
                sa_select(SourceConnection.sync_id).where(
                    SourceConnection.readable_collection_id == collection_id
                )
            )
        )

    if source_type is not None:
        query = query.where(
            Sync.id.in_(
                sa_select(SourceConnection.sync_id).where(
                    SourceConnection.short_name == source_type
                )
            )
        )

    # Apply last job status filter at SQL level
    if last_job_status is not None:
        from contextd.core.shared_models import SyncJobStatus

        try:
            status_enum = SyncJobStatus(last_job_status.lower())

            # Subquery to get most recent job per sync
            latest_job_subq = sa_select(
                SyncJob.sync_id,
                SyncJob.status,
                func.row_number()
                .over(partition_by=SyncJob.sync_id, order_by=SyncJob.created_at.desc())
                .label("rn"),
            ).subquery()

            # Filter to syncs where most recent job has the requested status
            query = query.where(
                Sync.id.in_(
                    sa_select(latest_job_subq.c.sync_id).where(
                        latest_job_subq.c.rn == 1,
                        latest_job_subq.c.status == status_enum,
                    )
                )
            )
        except ValueError:
            # Invalid status value, return empty result
            return []

    # Apply ghost sync filter at SQL level if requested
    if ghost_syncs_last_n is not None and ghost_syncs_last_n > 0:
        from contextd.core.shared_models import SyncJobStatus

        # Subquery to get last N jobs per sync (excluding running/pending)
        jobs_subq = (
            sa_select(
                SyncJob.sync_id,
                SyncJob.status,
                func.row_number()
                .over(partition_by=SyncJob.sync_id, order_by=SyncJob.created_at.desc())
                .label("rn"),
            )
            .where(
                SyncJob.status.notin_([SyncJobStatus.RUNNING.value, SyncJobStatus.PENDING.value])
            )
            .subquery()
        )

        # Get syncs where all last N jobs failed
        failed_syncs_subq = (
            sa_select(jobs_subq.c.sync_id)
            .where(jobs_subq.c.rn <= ghost_syncs_last_n)
            .group_by(jobs_subq.c.sync_id)
            .having(
                func.count().filter(jobs_subq.c.status == SyncJobStatus.FAILED.value)
                == func.count()
            )
            .having(func.count() >= ghost_syncs_last_n)
            .subquery()
        )

        query = query.where(Sync.id.in_(sa_select(failed_syncs_subq.c.sync_id)))

    query = query.order_by(Sync.created_at.desc()).offset(skip).limit(limit)

    result = await db.execute(query)
    syncs = list(result.scalars().all())

    if not syncs:
        return []

    sync_ids = [s.id for s in syncs]

    # Fetch entity counts in bulk
    entity_count_query = (
        sa_select(EntityCount.sync_id, func.sum(EntityCount.count).label("total_count"))
        .where(EntityCount.sync_id.in_(sync_ids))
        .group_by(EntityCount.sync_id)
    )
    entity_count_result = await db.execute(entity_count_query)
    entity_count_map = {row.sync_id: row.total_count or 0 for row in entity_count_result}

    # Fetch ARF entity counts in bulk (parallelized for speed)
    import asyncio

    from contextd.platform.sync.arf.service import ArfService

    arf_service = ArfService()

    # Parallelize ARF counts for all syncs
    async def get_arf_count_safe(sync_id):
        try:
            return await arf_service.get_entity_count(str(sync_id))
        except Exception:
            return None

    arf_count_tasks = [get_arf_count_safe(sync.id) for sync in syncs]
    arf_counts = await asyncio.gather(*arf_count_tasks)
    arf_count_map = {sync.id: count for sync, count in zip(syncs, arf_counts, strict=False)}

    # Fetch last job info in bulk (including error message)
    last_job_subq = (
        sa_select(
            SyncJob.sync_id,
            SyncJob.status,
            SyncJob.completed_at,
            SyncJob.error,
            func.row_number()
            .over(partition_by=SyncJob.sync_id, order_by=SyncJob.created_at.desc())
            .label("rn"),
        )
        .where(SyncJob.sync_id.in_(sync_ids))
        .subquery()
    )
    last_job_query = sa_select(last_job_subq).where(last_job_subq.c.rn == 1)
    last_job_result = await db.execute(last_job_query)
    last_job_map = {
        row.sync_id: {
            "status": row.status,
            "completed_at": row.completed_at,
            "error": row.error,
        }
        for row in last_job_result
    }

    # Fetch source connections info in bulk with collection IDs
    from contextd.models.collection import Collection

    source_conn_query = (
        sa_select(
            SourceConnection.sync_id,
            SourceConnection.short_name,
            SourceConnection.readable_collection_id,
            SourceConnection.is_authenticated,
            Collection.id.label("collection_id"),
        )
        .outerjoin(Collection, SourceConnection.readable_collection_id == Collection.readable_id)
        .where(SourceConnection.sync_id.in_(sync_ids))
    )
    source_conn_result = await db.execute(source_conn_query)
    source_conn_map = {
        row.sync_id: {
            "short_name": row.short_name,
            "readable_collection_id": row.readable_collection_id,
            "is_authenticated": row.is_authenticated,
            "collection_id": row.collection_id,
        }
        for row in source_conn_result
    }

    # Search index counts are not exposed by the default Neo4j fulltext path yet.
    search_index_count_map = {s.id: None for s in syncs}

    # Fetch sync connections to enrich with connection IDs
    sync_conn_query = (
        sa_select(SyncConnection, Connection)
        .join(Connection, SyncConnection.connection_id == Connection.id)
        .where(SyncConnection.sync_id.in_(sync_ids))
    )
    sync_conn_result = await db.execute(sync_conn_query)
    sync_connections = {}
    for sync_conn, connection in sync_conn_result:
        sync_id = sync_conn.sync_id
        if sync_id not in sync_connections:
            sync_connections[sync_id] = {"source": None, "destinations": []}
        if connection.integration_type.value == "source":
            sync_connections[sync_id]["source"] = connection.id
        elif connection.integration_type.value == "destination":
            sync_connections[sync_id]["destinations"].append(connection.id)

    # Build response using helper function
    admin_syncs = _build_admin_sync_info_list(
        syncs=syncs,
        sync_connections=sync_connections,
        source_conn_map=source_conn_map,
        last_job_map=last_job_map,
        entity_count_map=entity_count_map,
        arf_count_map=arf_count_map,
        search_index_count_map=search_index_count_map,
    )

    ctx.logger.info(
        f"Admin listed {len(admin_syncs)} syncs "
        f"(sync_ids={len(parsed_sync_ids) if parsed_sync_ids else None}, "
        f"org={organization_id}, collection={collection_id}, "
        f"source={source_type}, status={status}, "
        f"last_job_status={last_job_status}, "
        f"has_source={has_source_connection}, "
        f"is_authenticated={is_authenticated}, "
        f"ghost_syncs_n={ghost_syncs_last_n})"
    )

    return admin_syncs
