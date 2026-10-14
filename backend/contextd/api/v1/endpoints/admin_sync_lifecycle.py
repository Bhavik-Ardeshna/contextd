"""Admin sync lifecycle endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException
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

router = TrailingSlashRouter()


@router.post("/sync-jobs/{job_id}/cancel", response_model=schemas.SyncJob)
async def admin_cancel_sync_job(
    job_id: UUID,
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
) -> schemas.SyncJob:
    """Admin-only: Cancel any sync job regardless of organization.

    This endpoint allows admins or API keys with `api_key_admin_sync` permission
    to cancel sync jobs across organizations for migration and support purposes.

    Args:
        job_id: The ID of the sync job to cancel
        db: Database session
        ctx: API context

    Returns:
        The updated sync job

    Raises:
        HTTPException: If not admin, job not found, or job not cancellable
    """
    from sqlalchemy import select as sa_select

    from contextd.core.datetime_utils import utc_now_naive
    from contextd.core.shared_models import SyncJobStatus
    from contextd.core.sync_job_service import sync_job_service
    from contextd.core.temporal_service import temporal_service
    from contextd.models.sync_job import SyncJob

    _require_admin_permission(ctx, FeatureFlagEnum.API_KEY_ADMIN_SYNC)

    # Get the sync job without organization filtering
    result = await db.execute(sa_select(SyncJob).where(SyncJob.id == job_id))
    sync_job = result.scalar_one_or_none()

    if not sync_job:
        raise NotFoundException(f"Sync job {job_id} not found")

    ctx.logger.info(
        f"Admin cancelling sync job {job_id} (org: {sync_job.organization_id}, "
        f"status: {sync_job.status})"
    )

    # Check if job is in a cancellable state (handle status as string or enum)
    job_status_str = sync_job.status.value if hasattr(sync_job.status, "value") else sync_job.status
    if job_status_str not in [SyncJobStatus.PENDING.value, SyncJobStatus.RUNNING.value]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job in {job_status_str} state",
        )

    # Set transitional status to CANCELLING immediately
    await sync_job_service.update_status(
        sync_job_id=job_id,
        status=SyncJobStatus.CANCELLING,
        ctx=ctx,
    )

    # Fire-and-forget cancellation request to Temporal
    cancel_result = await temporal_service.cancel_sync_job_workflow(str(job_id), ctx)

    if not cancel_result["success"]:
        # Actual Temporal connectivity/availability error - revert status
        fallback_status = (
            SyncJobStatus.RUNNING
            if sync_job.status == SyncJobStatus.RUNNING
            else SyncJobStatus.PENDING
        )
        await sync_job_service.update_status(
            sync_job_id=job_id,
            status=fallback_status,
            ctx=ctx,
        )
        raise HTTPException(status_code=502, detail="Failed to request cancellation from Temporal")

    # If workflow wasn't found, mark job as CANCELLED directly
    if not cancel_result["workflow_found"]:
        ctx.logger.info(f"Workflow not found for job {job_id} - marking as CANCELLED directly")
        await sync_job_service.update_status(
            sync_job_id=job_id,
            status=SyncJobStatus.CANCELLED,
            ctx=ctx,
            completed_at=utc_now_naive(),
            error="Workflow not found in Temporal - may have already completed",
        )

    # Fetch the updated job from database
    await db.refresh(sync_job)

    ctx.logger.info(f"✅ Admin cancelled sync job {job_id}, new status: {sync_job.status}")

    return schemas.SyncJob.model_validate(sync_job, from_attributes=True)


@router.post("/syncs/{sync_id}/cancel")
async def admin_cancel_sync_by_id(
    sync_id: UUID,
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
) -> dict:
    """Admin-only: Cancel all pending/running jobs for a sync.
    This is a convenience endpoint that finds active jobs for a sync and cancels them.
    More practical than /sync-jobs/{job_id}/cancel when you know the sync ID.

    Args:
        sync_id: The sync ID whose jobs should be cancelled
        db: Database session
        ctx: API context
    Returns:
        Dict with cancelled job IDs and results
    Raises:
        HTTPException: If not admin or sync not found
    """
    from sqlalchemy import select as sa_select

    from contextd.core.datetime_utils import utc_now_naive
    from contextd.core.shared_models import SyncJobStatus
    from contextd.core.sync_job_service import sync_job_service
    from contextd.core.temporal_service import temporal_service
    from contextd.models.sync import Sync
    from contextd.models.sync_job import SyncJob

    _require_admin_permission(ctx, FeatureFlagEnum.API_KEY_ADMIN_SYNC)

    # Verify sync exists
    result = await db.execute(sa_select(Sync).where(Sync.id == sync_id))
    sync_obj = result.scalar_one_or_none()
    if not sync_obj:
        raise NotFoundException(f"Sync {sync_id} not found")

    # Find all pending/running jobs
    jobs_result = await db.execute(
        sa_select(SyncJob).where(
            SyncJob.sync_id == sync_id,
            SyncJob.status.in_([SyncJobStatus.PENDING, SyncJobStatus.RUNNING]),
        )
    )
    jobs = list(jobs_result.scalars().all())

    if not jobs:
        return {
            "sync_id": str(sync_id),
            "message": "No active jobs to cancel",
            "cancelled_jobs": [],
        }

    ctx.logger.info(f"Admin cancelling {len(jobs)} active job(s) for sync {sync_id}")

    cancelled_jobs = []
    failed_jobs = []

    for job in jobs:
        job_id = job.id
        job_status_str = job.status.value if hasattr(job.status, "value") else job.status

        try:
            # Set to CANCELLING
            await sync_job_service.update_status(
                sync_job_id=job_id,
                status=SyncJobStatus.CANCELLING,
                ctx=ctx,
            )

            # Request cancellation from Temporal
            cancel_result = await temporal_service.cancel_sync_job_workflow(str(job_id), ctx)

            if not cancel_result["success"]:
                # Temporal error - revert status
                fallback_status = (
                    SyncJobStatus.RUNNING
                    if job.status == SyncJobStatus.RUNNING
                    else SyncJobStatus.PENDING
                )
                await sync_job_service.update_status(
                    sync_job_id=job_id,
                    status=fallback_status,
                    ctx=ctx,
                )
                failed_jobs.append(
                    {
                        "job_id": str(job_id),
                        "error": "Failed to request cancellation from Temporal",
                    }
                )
                continue

            # If workflow not found, mark as CANCELLED directly
            if not cancel_result["workflow_found"]:
                ctx.logger.info(f"Workflow not found for job {job_id} - marking as CANCELLED")
                await sync_job_service.update_status(
                    sync_job_id=job_id,
                    status=SyncJobStatus.CANCELLED,
                    ctx=ctx,
                    completed_at=utc_now_naive(),
                    error="Workflow not found in Temporal - may have already completed",
                )

            cancelled_jobs.append(
                {
                    "job_id": str(job_id),
                    "previous_status": job_status_str,
                    "workflow_found": cancel_result["workflow_found"],
                }
            )

        except Exception as e:
            ctx.logger.error(f"Failed to cancel job {job_id}: {e}")
            failed_jobs.append({"job_id": str(job_id), "error": str(e)})

    ctx.logger.info(
        f"✅ Admin cancelled {len(cancelled_jobs)}/{len(jobs)} job(s) for sync {sync_id}"
    )

    return {
        "sync_id": str(sync_id),
        "total_jobs": len(jobs),
        "cancelled": len(cancelled_jobs),
        "failed": len(failed_jobs),
        "cancelled_jobs": cancelled_jobs,
        "failed_jobs": failed_jobs,
    }


@router.delete("/syncs/{sync_id}")
async def admin_delete_sync(
    sync_id: UUID,
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
) -> dict:
    """Admin-only: Delete a sync and all related data.

    This endpoint reuses the existing source connection deletion logic which handles:
    - Cancelling active jobs
    - Cleaning up Temporal schedules
    - Removing indexed graph/search data
    - Removing ARF storage
    - Cascading deletes in Postgres (sync, connection, source_connection)

    Args:
        sync_id: The sync ID to delete
        db: Database session
        ctx: API context

    Returns:
        Success message with deleted sync ID

    Raises:
        HTTPException: If not admin, sync not found, or deletion fails
    """
    from sqlalchemy import select as sa_select

    from contextd.core.source_connection_service import source_connection_service
    from contextd.models.source_connection import SourceConnection
    from contextd.models.sync import Sync

    _require_admin_permission(ctx, FeatureFlagEnum.API_KEY_ADMIN_SYNC)

    # Verify sync exists
    result = await db.execute(sa_select(Sync).where(Sync.id == sync_id))
    sync_obj = result.scalar_one_or_none()
    if not sync_obj:
        raise NotFoundException(f"Sync {sync_id} not found")

    # Find the source connection for this sync
    source_conn_result = await db.execute(
        sa_select(SourceConnection).where(SourceConnection.sync_id == sync_id)
    )
    source_conn = source_conn_result.scalar_one_or_none()

    if not source_conn:
        raise NotFoundException(f"Source connection not found for sync {sync_id}")

    ctx.logger.info(
        f"Admin deleting sync {sync_id} (org: {sync_obj.organization_id}) "
        f"via source connection {source_conn.id}"
    )

    # Build context for the sync's organization
    sync_org_ctx = await _build_org_context(db, sync_obj.organization_id, ctx)

    # Use the existing source connection delete logic which handles all cleanup
    try:
        await source_connection_service.delete(
            db,
            id=source_conn.id,
            ctx=sync_org_ctx,
        )

        ctx.logger.info(f"✅ Admin successfully deleted sync {sync_id}")

        return {
            "sync_id": str(sync_id),
            "message": "Sync deleted successfully",
            "deleted_source_connection_id": str(source_conn.id),
        }
    except Exception as e:
        ctx.logger.error(f"Failed to delete sync {sync_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete sync: {str(e)}")
