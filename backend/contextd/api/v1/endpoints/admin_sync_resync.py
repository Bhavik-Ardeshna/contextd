"""Admin sync resync endpoint."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import schemas
from contextd.api import deps
from contextd.api.context import ApiContext
from contextd.api.router import TrailingSlashRouter
from contextd.api.v1.endpoints.admin_access import (
    build_org_context as _build_org_context,
)
from contextd.api.v1.endpoints.admin_access import (
    require_admin_permission as _require_admin_permission,
)
from contextd.core.exceptions import NotFoundException
from contextd.core.shared_models import FeatureFlag as FeatureFlagEnum
from contextd.core.temporal_service import temporal_service
from contextd.platform.sync.config import SyncExecutionConfig

router = TrailingSlashRouter()


@router.post("/resync/{sync_id}", response_model=schemas.SyncJob)
async def resync_with_execution_config(
    *,
    db: AsyncSession = Depends(deps.get_db),
    sync_id: UUID,
    ctx: ApiContext = Depends(deps.get_context),
    execution_config: Optional[SyncExecutionConfig] = Body(
        None,
        description="Optional execution config for sync behavior (handler toggles, etc.)",
        examples=[
            {
                "enable_postgres_handler": False,
                "skip_cursor_load": True,
                "skip_cursor_updates": True,
            }
        ],
    ),
) -> schemas.SyncJob:
    """Admin-only: Trigger a sync with custom execution config via Temporal.

    This endpoint allows admins to trigger syncs with custom execution configurations
    for advanced use cases like ARF-only capture or dry runs.

    The sync is dispatched to Temporal and runs asynchronously in workers, not in the backend pod.

    **API Key Access**: Organizations with the `api_key_admin_sync` feature flag enabled
    can use API keys to access this endpoint programmatically.

    Args:
        db: Database session
        sync_id: ID of the sync to trigger
        ctx: API context
        execution_config: Optional dict with execution config parameters

    Returns:
        The created sync job

    Raises:
        HTTPException: If user is not admin or sync not found

    Example execution configs:
        - ARF capture only: {"enable_postgres_handler": false}
        - Dry run: {"enable_raw_data_handler": false, "enable_postgres_handler": false}
    """
    _require_admin_permission(ctx, FeatureFlagEnum.API_KEY_ADMIN_SYNC)

    ctx.logger.info(
        f"Admin triggering resync for sync {sync_id} with execution config: {execution_config}"
    )

    # Bypass organization filtering for all queries (admin access)
    from sqlalchemy import select as sa_select

    from contextd.core.shared_models import IntegrationType, SyncJobStatus
    from contextd.db.unit_of_work import UnitOfWork
    from contextd.models.collection import Collection
    from contextd.models.connection import Connection
    from contextd.models.source_connection import SourceConnection
    from contextd.models.sync import Sync
    from contextd.models.sync_connection import SyncConnection
    from contextd.models.sync_job import SyncJob

    # Get the sync without organization filtering
    result = await db.execute(sa_select(Sync).where(Sync.id == sync_id))
    sync_obj = result.scalar_one_or_none()
    if not sync_obj:
        raise NotFoundException(f"Sync {sync_id} not found")

    # Capture organization_id immediately before other async operations expire the model
    sync_organization_id = sync_obj.organization_id

    # Get connection IDs from SyncConnection table (bypass org filtering)
    sync_connections_result = await db.execute(
        sa_select(SyncConnection, Connection)
        .join(Connection, SyncConnection.connection_id == Connection.id)
        .where(SyncConnection.sync_id == sync_id)
    )
    sync_connections = sync_connections_result.all()

    source_connection_id = None
    destination_connection_ids = []
    for _sync_conn, conn in sync_connections:
        if conn.integration_type == IntegrationType.SOURCE:
            source_connection_id = conn.id
        else:
            destination_connection_ids.append(conn.id)

    if not source_connection_id:
        raise NotFoundException(f"Source connection not found for sync {sync_id}")

    # Check for existing active jobs (bypass org filtering)
    active_jobs_result = await db.execute(
        sa_select(SyncJob).where(
            SyncJob.sync_id == sync_id,
            SyncJob.status.in_(
                [
                    SyncJobStatus.PENDING,
                    SyncJobStatus.RUNNING,
                    SyncJobStatus.CANCELLING,
                ]
            ),
        )
    )
    active_jobs = list(active_jobs_result.scalars().all())
    if active_jobs:
        status = active_jobs[0].status
        job_status = (status.value if hasattr(status, "value") else status).lower()
        raise HTTPException(
            status_code=400, detail=f"Cannot start new sync: a sync job is already {job_status}"
        )

    # Enrich sync dict with connection IDs for schema validation
    sync_dict = {
        "id": sync_obj.id,
        "organization_id": sync_obj.organization_id,
        "name": sync_obj.name,
        "description": sync_obj.description,
        "status": sync_obj.status,
        "cron_schedule": sync_obj.cron_schedule,
        "next_scheduled_run": sync_obj.next_scheduled_run,
        "temporal_schedule_id": sync_obj.temporal_schedule_id,
        "sync_type": sync_obj.sync_type,
        "sync_metadata": sync_obj.sync_metadata,
        "created_at": sync_obj.created_at,
        "modified_at": sync_obj.modified_at,
        "created_by_email": sync_obj.created_by_email,
        "modified_by_email": sync_obj.modified_by_email,
        "source_connection_id": source_connection_id,
        "destination_connection_ids": destination_connection_ids,
    }
    sync_schema = schemas.Sync.model_validate(sync_dict)
    async with UnitOfWork(db) as uow:
        sync_job_obj = SyncJob(
            sync_id=sync_id,
            organization_id=sync_obj.organization_id,
            status=SyncJobStatus.PENDING,
            execution_config_json=execution_config.model_dump() if execution_config else None,
        )
        uow.session.add(sync_job_obj)
        await uow.commit()
        await uow.session.refresh(sync_job_obj)

    sync_job_schema = schemas.SyncJob.model_validate(sync_job_obj, from_attributes=True)

    # Get source connection (bypass org filtering)
    source_conn_result = await db.execute(
        sa_select(SourceConnection).where(SourceConnection.sync_id == sync_id)
    )
    source_conn = source_conn_result.scalar_one_or_none()
    if not source_conn:
        raise NotFoundException(f"Source connection not found for sync {sync_id}")

    # Get collection (bypass org filtering)
    collection_result = await db.execute(
        sa_select(Collection).where(Collection.readable_id == source_conn.readable_collection_id)
    )
    collection = collection_result.scalar_one_or_none()
    if not collection:
        raise NotFoundException(f"Collection {source_conn.readable_collection_id} not found")

    collection_schema = schemas.Collection.model_validate(collection, from_attributes=True)

    # Get the Connection object (bypass org filtering)
    connection_result = await db.execute(
        sa_select(Connection).where(Connection.id == source_conn.connection_id)
    )
    connection = connection_result.scalar_one_or_none()
    if not connection:
        raise NotFoundException("Connection not found for source connection")
    connection_schema = schemas.Connection.model_validate(connection, from_attributes=True)

    # Build context for the sync's organization (not the admin's API key org)
    # This ensures Temporal workers can access resources in the correct org context
    sync_org_ctx = await _build_org_context(db, sync_organization_id, ctx)

    # Dispatch to Temporal with the sync's organization context
    ctx.logger.info(
        f"Dispatching sync job {sync_job_schema.id} to Temporal "
        f"(sync org: {sync_organization_id}, admin org: {ctx.organization.id})"
    )
    await temporal_service.run_source_connection_workflow(
        sync=sync_schema,
        sync_job=sync_job_schema,
        collection=collection_schema,
        connection=connection_schema,
        ctx=sync_org_ctx,  # Use sync's org context, not admin's
        force_full_sync=False,
    )

    ctx.logger.info(f"✅ Admin resync job {sync_job_schema.id} dispatched to Temporal")

    return sync_job_schema


# =============================================================================
# Admin Sync Endpoints for API Key Access
# =============================================================================
