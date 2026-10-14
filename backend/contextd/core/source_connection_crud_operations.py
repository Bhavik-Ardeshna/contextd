"""CRUD operations for source connection service."""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud, schemas
from contextd.api.context import ApiContext
from contextd.core.shared_models import SyncJobStatus
from contextd.db.unit_of_work import UnitOfWork
from contextd.platform.cleanup.service import cleanup_service
from contextd.schemas.source_connection import (
    AuthenticationMethod,
    SourceConnection,
    SourceConnectionListItem,
    SourceConnectionUpdate,
)


class SourceConnectionCrudOperationsMixin:
    """Read, update, and delete source connections."""

    async def get(
        self,
        db: AsyncSession,
        *,
        id: UUID,
        ctx: ApiContext,
    ) -> SourceConnection:
        """Get a source connection with complete details."""
        source_conn = await crud.source_connection.get(db, id=id, ctx=ctx)
        if not source_conn:
            raise HTTPException(status_code=404, detail="Source connection not found")

        return await self._build_source_connection_response(db, source_conn, ctx)

    async def list(
        self,
        db: AsyncSession,
        *,
        ctx: ApiContext,
        readable_collection_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[SourceConnectionListItem]:
        """List source connections with complete stats."""
        connections_with_stats = await crud.source_connection.get_multi_with_stats(
            db, ctx=ctx, collection_id=readable_collection_id, skip=skip, limit=limit
        )

        result = []
        for data in connections_with_stats:
            last_job = data.get("last_job", {})
            last_job_status = last_job.get("status") if last_job else None
            drift = data.get("drift") or {}

            result.append(
                SourceConnectionListItem(
                    id=data["id"],
                    name=data["name"],
                    short_name=data["short_name"],
                    readable_collection_id=data["readable_collection_id"],
                    created_at=data["created_at"],
                    modified_at=data["modified_at"],
                    is_authenticated=data["is_authenticated"],
                    authentication_method=data.get("authentication_method"),
                    entity_count=data.get("entity_count", 0),
                    last_sync_at=data.get("last_sync_at"),
                    last_sync_started_at=last_job.get("started_at") if last_job else None,
                    is_active=data.get("is_active", True),
                    last_job_status=last_job_status,
                    drift_status=drift.get("status"),
                    drift_summary=drift.get("summary"),
                )
            )

        return result

    async def update(
        self,
        db: AsyncSession,
        *,
        id: UUID,
        obj_in: SourceConnectionUpdate,
        ctx: ApiContext,
    ) -> SourceConnection:
        """Update a source connection."""
        async with UnitOfWork(db) as uow:
            source_conn = await crud.source_connection.get(uow.session, id=id, ctx=ctx)
            if not source_conn:
                raise HTTPException(status_code=404, detail="Source connection not found")

            update_data = obj_in.model_dump(exclude_unset=True)

            if "authentication" in update_data:
                auth_payload = update_data.get("authentication") or {}
                credentials = auth_payload.get("credentials")
                if credentials:
                    update_data["credentials"] = credentials
                del update_data["authentication"]

            if "config" in update_data:
                validated_config = await self._validate_config_fields(
                    uow.session, source_conn.short_name, update_data["config"], ctx
                )
                from contextd.core.source_drift_service import source_drift_service

                update_data["config_fields"] = source_drift_service.apply_config_update(
                    source_conn.config_fields,
                    validated_config,
                )
                del update_data["config"]

            await self._handle_schedule_update(uow, source_conn, update_data, ctx)

            if "credentials" in update_data:
                from contextd.schemas.source_connection import determine_auth_method

                auth_method = determine_auth_method(source_conn)
                if auth_method != AuthenticationMethod.DIRECT:
                    raise HTTPException(
                        status_code=400,
                        detail="Credentials can only be updated for direct authentication",
                    )
                await self._update_auth_fields(
                    uow.session, source_conn, update_data["credentials"], ctx, uow
                )
                del update_data["credentials"]

            if update_data:
                source_conn = await crud.source_connection.update(
                    uow.session,
                    db_obj=source_conn,
                    obj_in=update_data,
                    ctx=ctx,
                    uow=uow,
                )

            await uow.commit()
            await uow.session.refresh(source_conn)

        return await self._build_source_connection_response(db, source_conn, ctx)

    async def delete(
        self,
        db: AsyncSession,
        *,
        id: UUID,
        ctx: ApiContext,
    ) -> SourceConnection:
        """Delete a source connection and all related data."""
        source_conn = await crud.source_connection.get(db, id=id, ctx=ctx)
        if not source_conn:
            raise HTTPException(status_code=404, detail="Source connection not found")

        sync_id = source_conn.sync_id
        collection = await crud.collection.get_by_readable_id(
            db, readable_id=source_conn.readable_collection_id, ctx=ctx
        )
        if not collection:
            raise HTTPException(status_code=404, detail="Collection not found")
        collection_schema = schemas.Collection.model_validate(collection, from_attributes=True)

        response = await self._build_source_connection_response(db, source_conn, ctx)

        if sync_id:
            latest_job = await crud.sync_job.get_latest_by_sync_id(db, sync_id=sync_id)
            if latest_job and latest_job.status in [SyncJobStatus.PENDING, SyncJobStatus.RUNNING]:
                ctx.logger.info(
                    f"Cancelling job {latest_job.id} for source connection {id} before deletion"
                )
                try:
                    await self.cancel_job(
                        db,
                        source_connection_id=id,
                        job_id=latest_job.id,
                        ctx=ctx,
                    )
                    ctx.logger.info(f"Successfully cancelled job {latest_job.id}")
                except Exception as e:
                    ctx.logger.warning(f"Failed to cancel job {latest_job.id} during deletion: {e}")

        await cleanup_service.cleanup_sync(db, sync_id, collection_schema, ctx)
        await crud.source_connection.remove(db, id=id, ctx=ctx)

        return response
