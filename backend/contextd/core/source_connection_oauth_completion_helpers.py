"""OAuth completion helper methods for source connections."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud, schemas
from contextd.api.context import ApiContext
from contextd.core import credentials
from contextd.core.shared_models import ConnectionStatus
from contextd.crud import connection_init_session
from contextd.db.unit_of_work import UnitOfWork
from contextd.models.integration_credential import IntegrationType
from contextd.models.source_connection import SourceConnection
from contextd.platform.locator import resource_locator
from contextd.schemas.source_connection import AuthenticationMethod

if TYPE_CHECKING:
    from contextd.platform.auth.oauth1_service import OAuth1TokenResponse
    from contextd.platform.auth.schemas import OAuth2TokenResponse


class SourceConnectionOAuthCompletionHelpersMixin:
    """Complete OAuth source connections after provider callbacks."""

    async def complete_oauth1_connection(
        self,
        db: AsyncSession,
        source_conn_shell: schemas.SourceConnection,
        init_session: Any,
        token_response: "OAuth1TokenResponse",
        ctx: ApiContext,
    ) -> Any:
        """Complete OAuth1 connection after callback."""
        source = await crud.source.get_by_short_name(db, short_name=init_session.short_name)
        if not source:
            raise HTTPException(
                status_code=404, detail=f"Source '{init_session.short_name}' not found"
            )

        init_session_id = init_session.id
        payload = init_session.payload or {}
        overrides = init_session.overrides or {}

        auth_fields = {
            "oauth_token": token_response.oauth_token,
            "oauth_token_secret": token_response.oauth_token_secret,
        }

        consumer_key = overrides.get("consumer_key")
        consumer_secret = overrides.get("consumer_secret")

        if consumer_key:
            auth_fields["consumer_key"] = consumer_key
        if consumer_secret:
            auth_fields["consumer_secret"] = consumer_secret

        from contextd.platform.auth.settings import integration_settings

        try:
            platform_settings = await integration_settings.get_by_short_name(
                init_session.short_name
            )
            from contextd.platform.auth.schemas import OAuth1Settings

            if isinstance(platform_settings, OAuth1Settings):
                is_byoc = (
                    consumer_key is not None and consumer_key != platform_settings.consumer_key
                )
            else:
                is_byoc = False
        except Exception:
            is_byoc = False

        auth_method_to_save = (
            AuthenticationMethod.OAUTH_BYOC if is_byoc else AuthenticationMethod.OAUTH_BROWSER
        )

        return await self._complete_oauth_connection_common(
            db,
            source,
            source_conn_shell,
            init_session_id,
            payload,
            auth_fields,
            auth_method_to_save,
            is_oauth1=True,
            ctx=ctx,
        )

    async def complete_oauth2_connection(
        self,
        db: AsyncSession,
        source_conn_shell: schemas.SourceConnection,
        init_session: Any,
        token_response: "OAuth2TokenResponse",
        ctx: ApiContext,
    ) -> Any:
        """Complete OAuth2 connection after callback."""
        source = await crud.source.get_by_short_name(db, short_name=init_session.short_name)
        if not source:
            raise HTTPException(
                status_code=404, detail=f"Source '{init_session.short_name}' not found"
            )

        init_session_id = init_session.id
        payload = init_session.payload or {}
        overrides = init_session.overrides or {}

        auth_fields = token_response.model_dump()

        if overrides.get("client_id"):
            auth_fields["client_id"] = overrides["client_id"]
        if overrides.get("client_secret"):
            auth_fields["client_secret"] = overrides["client_secret"]

        auth_method_to_save = (
            AuthenticationMethod.OAUTH_BYOC
            if (overrides.get("client_id") and overrides.get("client_secret"))
            else AuthenticationMethod.OAUTH_BROWSER
        )

        if init_session.short_name == "salesforce" and "instance_url" in auth_fields:
            instance_url_from_response = auth_fields.get("instance_url", "")
            if instance_url_from_response:
                instance_url_normalized = instance_url_from_response.replace(
                    "https://", ""
                ).replace("http://", "")

                if not payload.get("config"):
                    payload["config"] = {}
                payload["config"]["instance_url"] = instance_url_normalized

                ctx.logger.info(
                    f"Updated Salesforce instance_url from OAuth response: "
                    f"{instance_url_normalized}"
                )

        return await self._complete_oauth_connection_common(
            db,
            source,
            source_conn_shell,
            init_session_id,
            payload,
            auth_fields,
            auth_method_to_save,
            is_oauth1=False,
            ctx=ctx,
        )

    async def _complete_oauth_connection_common(
        self,
        db: AsyncSession,
        source: Any,
        source_conn_shell: schemas.SourceConnection,
        init_session_id: UUID,
        payload: Dict[str, Any],
        auth_fields: Dict[str, Any],
        auth_method_to_save: AuthenticationMethod,
        is_oauth1: bool,
        ctx: ApiContext,
    ) -> Any:
        """Common logic for completing OAuth connections."""
        validated_config = await self.validate_config_fields(
            db, source.short_name, payload.get("config"), ctx
        )

        auth_type_name = "OAuth1" if is_oauth1 else "OAuth2"

        async with UnitOfWork(db) as uow:
            encrypted = credentials.encrypt(auth_fields)

            cred_in = schemas.IntegrationCredentialCreateEncrypted(
                name=f"{source.name} {auth_type_name} Credential",
                description=f"{auth_type_name} credentials for {source.name}",
                integration_short_name=source.short_name,
                integration_type=IntegrationType.SOURCE,
                authentication_method=auth_method_to_save,
                oauth_type=getattr(source, "oauth_type", None),
                encrypted_credentials=encrypted,
                auth_config_class=source.auth_config_class,
            )
            credential = await crud.integration_credential.create(
                uow.session, obj_in=cred_in, ctx=ctx, uow=uow
            )

            await uow.session.flush()
            await uow.session.refresh(credential)

            conn_in = schemas.ConnectionCreate(
                name=payload.get("name", f"Connection to {source.name}"),
                integration_type=IntegrationType.SOURCE,
                status=ConnectionStatus.ACTIVE,
                integration_credential_id=credential.id,
                short_name=source.short_name,
            )
            connection = await crud.connection.create(uow.session, obj_in=conn_in, ctx=ctx, uow=uow)

            collection = await self.get_collection(
                uow.session,
                payload.get("readable_collection_id") or source_conn_shell.readable_collection_id,
                ctx,
            )

            await db.flush()
            await db.refresh(connection)

            source_class = resource_locator.get_source(source)
            is_federated = getattr(source_class, "_federated_search", False)

            if is_federated:
                ctx.logger.info(
                    f"Skipping sync creation for federated search source '{source.short_name}'. "
                    "Federated search sources are searched at query time."
                )
                sc_update = {
                    "config_fields": validated_config,
                    "readable_collection_id": collection.readable_id,
                    "sync_id": None,
                    "connection_id": connection.id,
                    "is_authenticated": True,
                }
                source_conn = await crud.source_connection.update(
                    uow.session,
                    db_obj=source_conn_shell,
                    obj_in=sc_update,
                    ctx=ctx,
                    uow=uow,
                )
            else:
                cron_schedule = (
                    payload.get("schedule", {}).get("cron")
                    if isinstance(payload.get("schedule"), dict)
                    else payload.get("cron_schedule")
                )
                if cron_schedule is None:
                    if getattr(source_class, "_supports_continuous", False):
                        cron_schedule = "*/5 * * * *"
                        ctx.logger.info(
                            "No cron schedule provided for continuous source '%s', "
                            "defaulting to 5-minute incremental syncs",
                            source.short_name,
                        )
                    else:
                        now_utc = datetime.now(timezone.utc)
                        minute = now_utc.minute
                        hour = now_utc.hour
                        cron_schedule = f"{minute} {hour} * * *"
                        ctx.logger.info(
                            "No cron schedule provided, defaulting to daily full sync "
                            "at %02d:%02d UTC",
                            hour,
                            minute,
                        )

                sync, sync_job = await self.create_sync_without_schedule(
                    uow.session,
                    name=payload.get("name") or source.name,
                    connection_id=connection.id,
                    collection_id=collection.id,
                    collection_readable_id=collection.readable_id,
                    cron_schedule=cron_schedule,
                    run_immediately=True,
                    ctx=ctx,
                    uow=uow,
                )

                sc_update = {
                    "config_fields": validated_config,
                    "readable_collection_id": collection.readable_id,
                    "sync_id": sync.id,
                    "connection_id": connection.id,
                    "is_authenticated": True,
                }
                source_conn = await crud.source_connection.update(
                    uow.session,
                    db_obj=source_conn_shell,
                    obj_in=sc_update,
                    ctx=ctx,
                    uow=uow,
                )

                await uow.session.flush()
                from contextd.platform.temporal.schedule_service import temporal_schedule_service

                await temporal_schedule_service.create_or_update_schedule(
                    sync_id=sync.id,
                    cron_schedule=cron_schedule,
                    db=uow.session,
                    ctx=ctx,
                    uow=uow,
                )

            await connection_init_session.mark_completed(
                uow.session,
                session_id=init_session_id,
                final_connection_id=sc_update["connection_id"],
                ctx=ctx,
            )

            await uow.commit()
            await uow.session.refresh(source_conn)

        return source_conn

    async def get_connection_for_source_connection(
        self,
        db: AsyncSession,
        source_connection: SourceConnection,
        ctx: ApiContext,
    ) -> schemas.Connection:
        """Get the Connection object for a SourceConnection."""
        if not source_connection.connection_id:
            raise ValueError(f"Source connection {source_connection.id} has no connection_id")

        connection = await crud.connection.get(db=db, id=source_connection.connection_id, ctx=ctx)
        if not connection:
            raise ValueError(f"Connection {source_connection.connection_id} not found")

        return schemas.Connection.model_validate(connection, from_attributes=True)
