"""Persistence helpers for source connection service."""

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud, schemas
from contextd.api.context import ApiContext
from contextd.core import credentials
from contextd.core.shared_models import ConnectionStatus, SyncStatus
from contextd.db.unit_of_work import UnitOfWork
from contextd.models.integration_credential import IntegrationType
from contextd.schemas.source_connection import AuthenticationMethod


class SourceConnectionPersistenceHelpersMixin:
    """Write-side persistence helpers for source connection service operations."""

    async def create_integration_credential(
        self,
        db: AsyncSession,
        source: schemas.Source,
        auth_fields: Dict[str, Any],
        ctx: ApiContext,
        uow: Any,
        auth_method: AuthenticationMethod = AuthenticationMethod.DIRECT,
    ) -> Any:
        """Create integration credential."""
        if hasattr(auth_fields, "model_dump"):
            auth_fields_dict = auth_fields.model_dump()
        else:
            auth_fields_dict = auth_fields

        encrypted = credentials.encrypt(auth_fields_dict)

        oauth_type = None
        if auth_method in [
            AuthenticationMethod.OAUTH_BROWSER,
            AuthenticationMethod.OAUTH_TOKEN,
            AuthenticationMethod.OAUTH_BYOC,
        ]:
            oauth_type = getattr(source, "oauth_type", None)

        cred_in = schemas.IntegrationCredentialCreateEncrypted(
            name=f"{source.name} - {ctx.organization.id}",
            description=f"Credentials for {source.name}",
            integration_short_name=source.short_name,
            integration_type=IntegrationType.SOURCE,
            authentication_method=auth_method,
            oauth_type=oauth_type,
            encrypted_credentials=encrypted,
            auth_config_class=source.auth_config_class,
        )
        return await crud.integration_credential.create(db, obj_in=cred_in, ctx=ctx, uow=uow)

    async def create_connection(
        self,
        db: AsyncSession,
        name: str,
        source: schemas.Source,
        credential_id: Optional[UUID],
        ctx: ApiContext,
        uow: Any,
    ) -> Any:
        """Create connection."""
        conn_in = schemas.ConnectionCreate(
            name=name,
            integration_type=IntegrationType.SOURCE,
            integration_credential_id=credential_id,
            status=ConnectionStatus.ACTIVE,
            short_name=source.short_name,
        )
        return await crud.connection.create(db, obj_in=conn_in, ctx=ctx, uow=uow)

    async def get_collection(
        self, db: AsyncSession, collection_id: str, ctx: ApiContext
    ) -> schemas.Collection:
        """Get or validate collection exists."""
        if not collection_id:
            raise HTTPException(status_code=400, detail="Collection is required")

        collection = await crud.collection.get_by_readable_id(
            db, readable_id=collection_id, ctx=ctx
        )
        if not collection:
            raise HTTPException(status_code=404, detail=f"Collection '{collection_id}' not found")
        return collection

    async def create_sync(
        self,
        db: AsyncSession,
        name: str,
        connection_id: UUID,
        collection_id: UUID,
        collection_readable_id: str,
        cron_schedule: Optional[str],
        run_immediately: bool,
        ctx: ApiContext,
        uow: Any,
    ) -> Tuple[schemas.Sync, Optional[schemas.SyncJob]]:
        """Create sync and optionally trigger initial run."""
        from contextd.core.sync_service import sync_service

        if cron_schedule is None:
            now_utc = datetime.now(timezone.utc)
            minute = now_utc.minute
            hour = now_utc.hour
            cron_schedule = f"{minute} {hour} * * *"
            ctx.logger.info(
                f"No cron schedule provided, defaulting to daily at {hour:02d}:{minute:02d} UTC"
            )

        destination_ids = await self._get_destination_connection_ids(db, ctx)
        await self._validate_destination_consistency(
            db, collection_readable_id, destination_ids, ctx
        )

        sync_in = schemas.SyncCreate(
            name=f"Sync for {name}",
            description=f"Auto-generated sync for {name}",
            source_connection_id=connection_id,
            destination_connection_ids=destination_ids,
            cron_schedule=cron_schedule,
            status=SyncStatus.ACTIVE,
            run_immediately=run_immediately,
        )
        return await sync_service.create_and_run_sync(db, sync_in=sync_in, ctx=ctx, uow=uow)

    async def create_sync_without_schedule(
        self,
        db: AsyncSession,
        name: str,
        connection_id: UUID,
        collection_id: UUID,
        collection_readable_id: str,
        cron_schedule: Optional[str],
        run_immediately: bool,
        ctx: ApiContext,
        uow: Any,
        schedule_config: Any = None,
    ) -> Tuple[schemas.Sync, Optional[schemas.SyncJob]]:
        """Create sync without creating Temporal schedule."""
        from contextd.core.sync_service import sync_service

        destination_ids = await self._get_destination_connection_ids(db, ctx)
        await self._validate_destination_consistency(
            db, collection_readable_id, destination_ids, ctx
        )

        sync_in = schemas.SyncCreate(
            name=f"Sync for {name}",
            description=f"Auto-generated sync for {name}",
            source_connection_id=connection_id,
            destination_connection_ids=destination_ids,
            cron_schedule=cron_schedule,
            status=SyncStatus.ACTIVE,
            run_immediately=run_immediately,
            sync_type=(
                "incremental" if getattr(schedule_config, "continuous", False) else "full"
            ),
            sync_metadata={
                "continuous": getattr(schedule_config, "continuous", False),
                "cursor_field": getattr(schedule_config, "cursor_field", None),
            },
        )
        return await sync_service._create_and_run_with_uow(
            db, sync_in=sync_in, ctx=ctx, uow=uow, skip_temporal_schedule=True
        )

    async def create_source_connection(
        self,
        db: AsyncSession,
        obj_in: Any,
        connection_id: Optional[UUID],
        collection_id: str,
        sync_id: Optional[UUID],
        config_fields: Optional[Dict[str, Any]],
        is_authenticated: bool,
        ctx: ApiContext,
        uow: Any,
        auth_provider_id: Optional[str] = None,
        auth_provider_config: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Create source connection record."""
        source_type = getattr(obj_in, "source_type", None) or getattr(obj_in, "short_name", None)
        from contextd.core.source_drift_service import source_drift_service

        config_fields = source_drift_service.ensure_initial_config_drift(config_fields)

        sc_data = {
            "name": obj_in.name,
            "description": obj_in.description,
            "short_name": source_type,
            "config_fields": config_fields,
            "connection_id": connection_id,
            "readable_collection_id": collection_id,
            "sync_id": sync_id,
            "is_authenticated": is_authenticated,
        }

        if auth_provider_id:
            sc_data["readable_auth_provider_id"] = auth_provider_id
            sc_data["auth_provider_config"] = auth_provider_config

        return await crud.source_connection.create(db, obj_in=sc_data, ctx=ctx, uow=uow)

    async def update_sync_schedule(
        self,
        db: AsyncSession,
        sync_id: UUID,
        cron_schedule: Optional[str],
        ctx: ApiContext,
        uow: UnitOfWork,
    ) -> None:
        """Update sync schedule in database and Temporal."""
        sync = await crud.sync.get(db, id=sync_id, ctx=ctx)
        if sync:
            sync_update = schemas.SyncUpdate(cron_schedule=cron_schedule)
            await crud.sync.update(db, db_obj=sync, obj_in=sync_update, ctx=ctx, uow=uow)

            from contextd.platform.temporal.schedule_service import temporal_schedule_service

            if cron_schedule is None:
                await temporal_schedule_service.delete_all_schedules_for_sync(
                    sync_id=sync_id, db=db, ctx=ctx
                )
            else:
                await temporal_schedule_service.create_or_update_schedule(
                    sync_id=sync_id,
                    cron_schedule=cron_schedule,
                    db=db,
                    ctx=ctx,
                    uow=uow,
                )

    async def update_auth_fields(
        self,
        db: AsyncSession,
        source_conn: Any,
        auth_fields: Any,
        ctx: ApiContext,
        uow: Any,
    ) -> None:
        """Update authentication fields."""
        validated_auth = await self.validate_auth_fields(
            db, source_conn.short_name, auth_fields, ctx
        )
        if hasattr(validated_auth, "model_dump"):
            serializable_auth = validated_auth.model_dump()
        elif hasattr(validated_auth, "dict"):
            serializable_auth = validated_auth.dict()
        else:
            serializable_auth = validated_auth

        connection = await crud.connection.get(db, id=source_conn.connection_id, ctx=ctx)
        if connection and connection.integration_credential_id:
            credential = await crud.integration_credential.get(
                db, id=connection.integration_credential_id, ctx=ctx
            )
            if credential:
                credential_update = schemas.IntegrationCredentialUpdate(
                    encrypted_credentials=credentials.encrypt(serializable_auth)
                )
                await crud.integration_credential.update(
                    db, db_obj=credential, obj_in=credential_update, ctx=ctx, uow=uow
                )

    async def cleanup_destination_data(
        self, db: AsyncSession, source_conn: Any, ctx: ApiContext
    ) -> None:
        """Clean up data in destinations and ARF."""
        from contextd.platform.cleanup import cleanup_service

        collection = await crud.collection.get_by_readable_id(
            db, readable_id=source_conn.readable_collection_id, ctx=ctx
        )
        if not collection:
            return

        collection_schema = schemas.Collection.model_validate(collection, from_attributes=True)
        await cleanup_service.cleanup_sync(db, source_conn.sync_id, collection_schema, ctx)
