"""Job operations for source connection service."""

from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud, schemas
from contextd.api.context import ApiContext
from contextd.core.shared_models import SyncJobStatus
from contextd.core.source_connection_service_helpers import source_connection_helpers
from contextd.core.sync_service import sync_service
from contextd.core.temporal_service import temporal_service


class SourceConnectionJobsMixin:
    """Run, list, and cancel source connection sync jobs."""

    async def run(
        self,
        db: AsyncSession,
        *,
        id: UUID,
        ctx: ApiContext,
        force_full_sync: bool = False,
    ) -> schemas.SourceConnectionJob:
        """Trigger a sync run for a source connection.

        Args:
            db: Database session
            id: Source connection ID
            ctx: API context
            force_full_sync: If True, forces a full sync with orphaned entity cleanup.
                           Only allowed for continuous syncs (syncs with cursor data).
                           Raises HTTPException if used on non-continuous syncs.
        """
        source_conn = await crud.source_connection.get(db, id=id, ctx=ctx)
        if not source_conn:
            raise HTTPException(status_code=404, detail="Source connection not found")

        if not source_conn.sync_id:
            raise HTTPException(status_code=400, detail="Source connection has no associated sync")

        # Validate force_full_sync is only used with continuous syncs
        if force_full_sync:
            # Check if sync has cursor data (indicates continuous sync)
            cursor = await crud.sync_cursor.get_by_sync_id(db, sync_id=source_conn.sync_id, ctx=ctx)

            if not cursor or not cursor.cursor_data:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "force_full_sync can only be used with continuous syncs "
                        "(syncs with cursor data). This sync is non-continuous and "
                        "always performs full syncs by default."
                    ),
                )

            ctx.logger.info(
                f"Force full sync requested for continuous sync {source_conn.sync_id}. "
                "Will ignore cursor data and perform full sync with orphaned entity cleanup."
            )

        # Run through Temporal
        collection = await crud.collection.get_by_readable_id(
            db, readable_id=source_conn.readable_collection_id, ctx=ctx
        )

        collection_schema = schemas.Collection.model_validate(collection, from_attributes=True)
        source_connection_schema = await self._build_source_connection_response(
            db, source_conn, ctx
        )

        # Get the actual Connection object (not SourceConnection!)
        connection_schema = await source_connection_helpers.get_connection_for_source_connection(
            db=db, source_connection=source_conn, ctx=ctx
        )

        # Trigger sync through Temporal only
        sync, sync_job = await sync_service.trigger_sync_run(
            db, sync_id=source_conn.sync_id, ctx=ctx
        )

        await temporal_service.run_source_connection_workflow(
            sync=sync,
            sync_job=sync_job,
            collection=collection_schema,
            connection=connection_schema,  # Pass Connection, not SourceConnection
            ctx=ctx,
            force_full_sync=force_full_sync,
        )

        # Convert sync_job to SourceConnectionJob using the built-in conversion method
        sync_job_schema = schemas.SyncJob.model_validate(sync_job, from_attributes=True)
        return sync_job_schema.to_source_connection_job(source_connection_schema.id)

    async def get_jobs(
        self,
        db: AsyncSession,
        *,
        id: UUID,
        ctx: ApiContext,
        limit: int = 100,
    ) -> List[schemas.SourceConnectionJob]:
        """Get sync jobs for a source connection."""
        source_conn = await crud.source_connection.get(db, id=id, ctx=ctx)
        if not source_conn:
            raise HTTPException(status_code=404, detail="Source connection not found")

        if not source_conn.sync_id:
            return []

        sync_jobs = await sync_service.list_sync_jobs(
            db, ctx=ctx, sync_id=source_conn.sync_id, limit=limit
        )

        return [self._sync_job_to_source_connection_job(job, source_conn.id) for job in sync_jobs]

    async def cancel_job(
        self,
        db: AsyncSession,
        *,
        source_connection_id: UUID,
        job_id: UUID,
        ctx: ApiContext,
    ) -> schemas.SourceConnectionJob:
        """Cancel a running sync job for a source connection.

        Sends a cancellation request to the Temporal workflow and marks the
        job as CANCELLING locally. Final CANCELLED state is set by the
        workflow when it processes the cancellation.
        """
        # Verify source connection exists and user has access
        source_conn = await crud.source_connection.get(db, id=source_connection_id, ctx=ctx)
        if not source_conn:
            raise HTTPException(status_code=404, detail="Source connection not found")

        if not source_conn.sync_id:
            raise HTTPException(status_code=400, detail="Source connection has no associated sync")

        # Get the sync job and verify it belongs to this source connection
        sync_job = await crud.sync_job.get(db, id=job_id, ctx=ctx)
        if not sync_job:
            raise HTTPException(status_code=404, detail="Sync job not found")

        if sync_job.sync_id != source_conn.sync_id:
            raise HTTPException(
                status_code=400, detail="Sync job does not belong to this source connection"
            )

        # Check if job is in a cancellable state
        if sync_job.status not in [SyncJobStatus.PENDING, SyncJobStatus.RUNNING]:
            raise HTTPException(
                status_code=400, detail=f"Cannot cancel job in {sync_job.status} state"
            )

        # Set transitional status to CANCELLING immediately
        from contextd.core.sync_job_service import sync_job_service

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
            raise HTTPException(
                status_code=502, detail="Failed to request cancellation from Temporal"
            )

        # If workflow wasn't found, mark job as CANCELLED directly since there's nothing running
        if not cancel_result["workflow_found"]:
            ctx.logger.info(f"Workflow not found for job {job_id} - marking as CANCELLED directly")
            from contextd.core.datetime_utils import utc_now_naive

            await sync_job_service.update_status(
                sync_job_id=job_id,
                status=SyncJobStatus.CANCELLED,
                ctx=ctx,
                completed_at=utc_now_naive(),
                error="Workflow not found in Temporal - may have already completed",
            )

        # Fetch the updated job from database
        await db.refresh(sync_job)

        # Convert to SourceConnectionJob response
        sync_job_schema = schemas.SyncJob.model_validate(sync_job, from_attributes=True)
        return sync_job_schema.to_source_connection_job(source_connection_id)
