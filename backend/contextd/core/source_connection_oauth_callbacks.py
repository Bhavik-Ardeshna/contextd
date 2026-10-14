"""OAuth callback completion for source connection service."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud, schemas
from contextd.api.context import ApiContext
from contextd.core.shared_models import SyncJobStatus
from contextd.core.temporal_service import temporal_service
from contextd.crud import connection_init_session
from contextd.models.connection_init_session import ConnectionInitStatus
from contextd.platform.auth.schemas import OAuth1Settings
from contextd.platform.auth.settings import integration_settings


class SourceConnectionOAuthCallbacksMixin:
    """Complete OAuth callbacks and trigger immediate syncs when needed."""

    async def complete_oauth1_callback(
        self,
        db: AsyncSession,
        *,
        oauth_token: str,
        oauth_verifier: str,
    ) -> schemas.SourceConnection:
        """Complete OAuth1 flow from callback."""
        init_session = await connection_init_session.get_by_oauth_token_no_auth(
            db, oauth_token=oauth_token
        )
        if not init_session:
            raise HTTPException(
                status_code=404,
                detail=(
                    "OAuth1 session not found or expired. Request token may have been used already."
                ),
            )

        if init_session.status != ConnectionInitStatus.PENDING:
            raise HTTPException(
                status_code=400, detail=f"OAuth session already {init_session.status}"
            )

        ctx = await self._reconstruct_context_from_session(db, init_session)

        source_conn_shell = await crud.source_connection.get_by_query_and_org(
            db, ctx=ctx, connection_init_session_id=init_session.id
        )
        if not source_conn_shell:
            raise HTTPException(status_code=404, detail="Source connection shell not found")

        oauth_settings = await integration_settings.get_by_short_name(init_session.short_name)
        if not isinstance(oauth_settings, OAuth1Settings):
            raise HTTPException(
                status_code=400,
                detail=f"Source {init_session.short_name} is not configured for OAuth1",
            )

        token_response = await self._exchange_oauth1_code(
            init_session.short_name,
            oauth_verifier,
            init_session.overrides,
            oauth_settings,
            ctx,
        )

        source_conn = await self._complete_oauth1_connection(
            db, source_conn_shell, init_session, token_response, ctx
        )

        return await self._finalize_oauth_callback(db, source_conn, ctx)

    async def complete_oauth2_callback(
        self,
        db: AsyncSession,
        *,
        state: str,
        code: str,
    ) -> schemas.SourceConnection:
        """Complete OAuth2 flow from callback."""
        init_session = await connection_init_session.get_by_state_no_auth(db, state=state)
        if not init_session:
            raise HTTPException(status_code=404, detail="OAuth2 session not found or expired")

        if init_session.status != ConnectionInitStatus.PENDING:
            raise HTTPException(
                status_code=400, detail=f"OAuth session already {init_session.status}"
            )

        ctx = await self._reconstruct_context_from_session(db, init_session)

        source_conn_shell = await crud.source_connection.get_by_query_and_org(
            db, ctx=ctx, connection_init_session_id=init_session.id
        )
        if not source_conn_shell:
            raise HTTPException(status_code=404, detail="Source connection shell not found")

        token_response = await self._exchange_oauth2_code(
            init_session.short_name, code, init_session.overrides, ctx
        )

        await self._validate_oauth_token(
            db,
            await crud.source.get_by_short_name(db, short_name=init_session.short_name),
            token_response.access_token,
            None,
            ctx,
        )

        source_conn = await self._complete_oauth2_connection(
            db, source_conn_shell, init_session, token_response, ctx
        )

        return await self._finalize_oauth_callback(db, source_conn, ctx)

    async def _finalize_oauth_callback(
        self,
        db: AsyncSession,
        source_conn: Any,
        ctx: ApiContext,
    ) -> schemas.SourceConnection:
        """Build the OAuth response and trigger the pending immediate sync."""
        source_conn_response = await self._build_source_connection_response(db, source_conn, ctx)

        if source_conn.sync_id:
            sync = await crud.sync.get(db, id=source_conn.sync_id, ctx=ctx)
            if sync:
                jobs = await crud.sync_job.get_all_by_sync_id(db, sync_id=sync.id)
                if jobs and len(jobs) > 0:
                    sync_job = jobs[0]
                    if sync_job.status == SyncJobStatus.PENDING:
                        collection = await crud.collection.get_by_readable_id(
                            db, readable_id=source_conn.readable_collection_id, ctx=ctx
                        )
                        if collection:
                            collection_schema = schemas.Collection.model_validate(
                                collection, from_attributes=True
                            )
                            sync_job_schema = schemas.SyncJob.model_validate(
                                sync_job, from_attributes=True
                            )
                            sync_schema = schemas.Sync.model_validate(sync, from_attributes=True)

                            connection_schema = await self._get_connection_for_source_connection(
                                db=db, source_connection=source_conn, ctx=ctx
                            )

                            await temporal_service.run_source_connection_workflow(
                                sync=sync_schema,
                                sync_job=sync_job_schema,
                                collection=collection_schema,
                                connection=connection_schema,
                                ctx=ctx,
                            )

        return source_conn_response
