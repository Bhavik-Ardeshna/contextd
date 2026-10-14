"""Authenticated source connection creation helpers."""

from __future__ import annotations

from typing import Optional, Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud, schemas
from contextd.api.context import ApiContext
from contextd.core.auth_provider_service import auth_provider_service
from contextd.core.source_connection_service_helpers import source_connection_helpers
from contextd.core.temporal_service import temporal_service
from contextd.db.unit_of_work import UnitOfWork
from contextd.platform.sources._base import BaseSource
from contextd.schemas.source_connection import (
    AuthenticationMethod,
    AuthProviderAuthentication,
    DirectAuthentication,
    OAuthTokenAuthentication,
    SourceConnection,
    SourceConnectionCreate,
)


class SourceConnectionCreationSharedMixin:
    """Create authenticated source connections and shared sync artifacts."""

    async def _create_with_direct_auth(
        self,
        db: AsyncSession,
        obj_in: SourceConnectionCreate,
        ctx: ApiContext,
    ) -> SourceConnection:
        """Create connection with direct authentication credentials."""
        source = await self._get_and_validate_source(db, obj_in.short_name)

        if not obj_in.authentication or not isinstance(obj_in.authentication, DirectAuthentication):
            raise HTTPException(
                status_code=400, detail="Direct authentication requires credentials"
            )

        validated_auth = await self._validate_auth_fields(
            db, obj_in.short_name, obj_in.authentication.credentials, ctx
        )
        validated_config = await self._validate_config_fields(
            db, obj_in.short_name, obj_in.config, ctx
        )

        await self._validate_direct_auth(db, source, validated_auth, validated_config, ctx)

        async with UnitOfWork(db) as uow:
            collection = await self._get_collection(uow.session, obj_in.readable_collection_id, ctx)

            credential = await self._create_integration_credential(
                uow.session,
                source,
                validated_auth,
                ctx,
                uow,
                AuthenticationMethod.DIRECT,
            )
            await uow.session.flush()

            connection = await self._create_connection(
                uow.session, obj_in.name, source, credential.id, ctx, uow
            )
            await uow.session.flush()
            connection_schema = schemas.Connection.model_validate(connection, from_attributes=True)

            sync_id, sync, sync_job = await self._handle_sync_creation(
                uow, obj_in, source, connection.id, collection.id, collection.readable_id, ctx
            )

            source_conn = await self._create_source_connection(
                uow.session,
                obj_in,
                connection.id,
                collection.readable_id,
                sync_id,
                validated_config,
                is_authenticated=True,
                ctx=ctx,
                uow=uow,
            )
            await uow.session.flush()

            cron_schedule = self._determine_schedule_for_source(obj_in, source, ctx)
            await self._create_temporal_schedule_if_needed(uow, cron_schedule, sync_id, ctx)

            (
                sync_schema,
                sync_job_schema,
                collection_schema,
            ) = await self._prepare_sync_schemas_for_workflow(
                uow, sync, sync_job, collection, obj_in
            )

            await uow.commit()
            await uow.session.refresh(source_conn)

        response = await self._build_source_connection_response(db, source_conn, ctx)

        if sync_job and obj_in.sync_immediately:
            await self._trigger_sync_workflow(
                db, connection_schema, sync_schema, sync_job_schema, collection_schema, ctx
            )

        return response

    async def _create_with_oauth_token(
        self,
        db: AsyncSession,
        obj_in: SourceConnectionCreate,
        ctx: ApiContext,
    ) -> SourceConnection:
        """Create connection with injected OAuth token."""
        source = await self._get_and_validate_source(db, obj_in.short_name)

        if not obj_in.authentication or not isinstance(
            obj_in.authentication, OAuthTokenAuthentication
        ):
            raise HTTPException(
                status_code=400, detail="OAuth token authentication requires an access token"
            )

        oauth_creds = {
            "access_token": obj_in.authentication.access_token,
            "refresh_token": obj_in.authentication.refresh_token,
            "token_type": "Bearer",
        }
        if obj_in.authentication.expires_at:
            oauth_creds["expires_at"] = obj_in.authentication.expires_at.isoformat()

        validated_config = await self._validate_config_fields(
            db, obj_in.short_name, obj_in.config, ctx
        )

        await self._validate_oauth_token(
            db, source, obj_in.authentication.access_token, validated_config, ctx
        )

        async with UnitOfWork(db) as uow:
            collection = await self._get_collection(uow.session, obj_in.readable_collection_id, ctx)

            credential = await self._create_integration_credential(
                uow.session,
                source,
                oauth_creds,
                ctx,
                uow,
                AuthenticationMethod.OAUTH_TOKEN,
            )
            await uow.session.flush()

            connection = await self._create_connection(
                uow.session, obj_in.name, source, credential.id, ctx, uow
            )
            await uow.session.flush()
            connection_schema = schemas.Connection.model_validate(connection, from_attributes=True)

            sync_id, sync, sync_job = await self._handle_sync_creation(
                uow, obj_in, source, connection.id, collection.id, collection.readable_id, ctx
            )

            source_conn = await self._create_source_connection(
                uow.session,
                obj_in,
                connection.id,
                collection.readable_id,
                sync_id,
                validated_config,
                is_authenticated=True,
                ctx=ctx,
                uow=uow,
            )
            await uow.session.flush()

            cron_schedule = self._determine_schedule_for_source(obj_in, source, ctx)
            await self._create_temporal_schedule_if_needed(uow, cron_schedule, sync_id, ctx)

            (
                sync_schema,
                sync_job_schema,
                collection_schema,
            ) = await self._prepare_sync_schemas_for_workflow(
                uow, sync, sync_job, collection, obj_in
            )

            await uow.commit()
            await uow.session.refresh(source_conn)

        response = await self._build_source_connection_response(db, source_conn, ctx)

        if sync_job and obj_in.sync_immediately:
            await self._trigger_sync_workflow(
                db, connection_schema, sync_schema, sync_job_schema, collection_schema, ctx
            )

        return response

    async def _create_with_auth_provider(
        self,
        db: AsyncSession,
        obj_in: SourceConnectionCreate,
        ctx: ApiContext,
    ) -> SourceConnection:
        """Create connection using external auth provider."""
        source = await self._get_and_validate_source(db, obj_in.short_name)

        if not obj_in.authentication or not isinstance(
            obj_in.authentication, AuthProviderAuthentication
        ):
            raise HTTPException(
                status_code=400,
                detail="Auth provider authentication requires provider configuration",
            )

        auth_provider_conn = await crud.connection.get_by_readable_id(
            db, readable_id=obj_in.authentication.provider_readable_id, ctx=ctx
        )
        if not auth_provider_conn:
            raise HTTPException(
                status_code=404,
                detail=f"Auth provider '{obj_in.authentication.provider_readable_id}' not found",
            )

        supported_providers = auth_provider_service.get_supported_providers_for_source(
            obj_in.short_name
        )
        if auth_provider_conn.short_name not in supported_providers:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Source '{obj_in.short_name}' does not support "
                    f"'{auth_provider_conn.short_name}' as an auth provider. "
                    f"Supported providers: {supported_providers}"
                ),
            )

        validated_auth_config = None
        if obj_in.authentication.provider_config:
            validated_auth_config = await auth_provider_service.validate_auth_provider_config(
                db, auth_provider_conn.short_name, obj_in.authentication.provider_config
            )

        validated_config = await self._validate_config_fields(
            db, obj_in.short_name, obj_in.config, ctx
        )

        async with UnitOfWork(db) as uow:
            collection = await self._get_collection(uow.session, obj_in.readable_collection_id, ctx)

            connection = await self._create_connection(
                uow.session, obj_in.name, source, None, ctx, uow
            )
            await uow.session.flush()

            sync_id, sync, sync_job = await self._handle_sync_creation(
                uow, obj_in, source, connection.id, collection.id, collection.readable_id, ctx
            )

            source_conn = await self._create_source_connection(
                uow.session,
                obj_in,
                connection.id,
                collection.readable_id,
                sync_id,
                validated_config,
                is_authenticated=True,
                ctx=ctx,
                uow=uow,
                auth_provider_id=auth_provider_conn.readable_id,
                auth_provider_config=validated_auth_config,
            )
            await uow.session.flush()

            cron_schedule = self._determine_schedule_for_source(obj_in, source, ctx)
            await self._create_temporal_schedule_if_needed(uow, cron_schedule, sync_id, ctx)

            (
                sync_schema,
                sync_job_schema,
                collection_schema,
            ) = await self._prepare_sync_schemas_for_workflow(
                uow, sync, sync_job, collection, obj_in
            )

            await uow.commit()
            await uow.session.refresh(source_conn)

        response = await self._build_source_connection_response(db, source_conn, ctx)

        if sync_job and obj_in.sync_immediately:
            connection_schema = (
                await source_connection_helpers.get_connection_for_source_connection(
                    db=db, source_connection=source_conn, ctx=ctx
                )
            )
            await self._trigger_sync_workflow(
                db, connection_schema, sync_schema, sync_job_schema, collection_schema, ctx
            )

        return response

    async def _handle_sync_creation(
        self,
        uow,
        obj_in: SourceConnectionCreate,
        source: schemas.Source,
        connection_id: UUID,
        collection_id: UUID,
        collection_readable_id: str,
        ctx: ApiContext,
    ) -> Tuple[Optional[UUID], Optional[schemas.Sync], Optional[schemas.SyncJob]]:
        """Create sync rows needed for scheduled or immediate runs."""
        source_class = self._get_source_class(source.class_name)
        if getattr(source_class, "_federated_search", False):
            ctx.logger.info(
                f"Skipping sync creation for federated search source '{source.short_name}'. "
                "Federated search sources are searched at query time."
            )
            return None, None, None

        cron_schedule = self._determine_schedule_for_source(obj_in, source, ctx)
        if not cron_schedule and not obj_in.sync_immediately:
            return None, None, None

        if cron_schedule:
            self._validate_cron_schedule_for_source(cron_schedule, source, ctx)

        sync, sync_job = await self._create_sync_without_schedule(
            uow.session,
            obj_in.name,
            connection_id,
            collection_id,
            collection_readable_id,
            cron_schedule,
            obj_in.sync_immediately,
            ctx,
            uow,
            schedule_config=obj_in.schedule,
        )
        await uow.session.flush()

        sync_id = sync.id if sync else None
        return sync_id, sync, sync_job

    async def _prepare_sync_schemas_for_workflow(
        self,
        uow,
        sync: Optional[schemas.Sync],
        sync_job: Optional[schemas.SyncJob],
        collection: schemas.Collection,
        obj_in: SourceConnectionCreate,
    ) -> Tuple[Optional[schemas.Sync], Optional[schemas.SyncJob], Optional[schemas.Collection]]:
        """Prepare sync schemas for Temporal workflow if immediate sync is requested."""
        if sync_job and obj_in.sync_immediately:
            await uow.session.flush()
            await uow.session.refresh(sync_job)
            await uow.session.refresh(collection)

            sync_schema = schemas.Sync.model_validate(sync, from_attributes=True)
            sync_job_schema = schemas.SyncJob.model_validate(sync_job, from_attributes=True)
            collection_schema = schemas.Collection.model_validate(collection, from_attributes=True)

            return sync_schema, sync_job_schema, collection_schema

        return None, None, None

    async def _trigger_sync_workflow(
        self,
        db: AsyncSession,
        connection: schemas.Connection,
        sync: schemas.Sync,
        sync_job: schemas.SyncJob,
        collection: schemas.Collection,
        ctx: ApiContext,
    ) -> None:
        """Trigger Temporal workflow for sync."""
        await temporal_service.run_source_connection_workflow(
            sync=sync,
            sync_job=sync_job,
            collection=collection,
            connection=connection,
            ctx=ctx,
        )

    async def _get_and_validate_source(self, db: AsyncSession, short_name: str) -> schemas.Source:
        """Get and validate source exists."""
        source = await crud.source.get_by_short_name(db, short_name=short_name)
        if not source:
            raise HTTPException(status_code=404, detail=f"Source '{short_name}' not found")
        return source

    def _get_source_class(self, class_name: str) -> type[BaseSource]:
        """Get source class by name."""
        module_name = class_name.replace("Source", "").lower()

        if module_name.startswith("google") and len(module_name) > 6:
            module_name = "google_" + module_name[6:]
        elif module_name.startswith("outlook") and len(module_name) > 7:
            module_name = "outlook_" + module_name[7:]
        elif module_name.startswith("zoho") and len(module_name) > 4:
            module_name = "zoho_" + module_name[4:]

        module = __import__(f"contextd.platform.sources.{module_name}", fromlist=[class_name])
        return getattr(module, class_name)
