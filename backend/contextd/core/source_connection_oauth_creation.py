"""OAuth browser source connection creation helpers."""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from contextd.api.context import ApiContext
from contextd.core.config import settings as core_settings
from contextd.db.unit_of_work import UnitOfWork
from contextd.platform.auth.oauth2_service import oauth2_service
from contextd.platform.auth.settings import integration_settings
from contextd.schemas.source_connection import (
    OAuthBrowserAuthentication,
    SourceConnection,
    SourceConnectionCreate,
)

if TYPE_CHECKING:
    from contextd.platform.auth.schemas import OAuth1Settings, OAuth2Settings


class SourceConnectionOAuthCreationMixin:
    """Create shell source connections for browser OAuth flows."""

    async def _create_with_oauth1_browser(
        self,
        db: AsyncSession,
        obj_in: SourceConnectionCreate,
        oauth_settings: OAuth1Settings,
        ctx: ApiContext,
        custom_consumer_key: Optional[str] = None,
        custom_consumer_secret: Optional[str] = None,
    ) -> SourceConnection:
        """Create shell connection and start OAuth1 browser flow."""
        source = await self._get_and_validate_source(db, obj_in.short_name)

        validated_config = await self._validate_config_fields(
            db, obj_in.short_name, obj_in.config, ctx
        )

        state = secrets.token_urlsafe(24)
        api_callback = f"{core_settings.api_url}/source-connections/callback"

        consumer_key = custom_consumer_key or oauth_settings.consumer_key
        consumer_secret = custom_consumer_secret or oauth_settings.consumer_secret

        from contextd.platform.auth.oauth1_service import oauth1_service

        flow_type = "OAuth1 BYOC" if custom_consumer_key else "OAuth1"
        ctx.logger.info(f"Starting {flow_type} flow for {source.short_name}")

        request_token_response = await oauth1_service.get_request_token(
            request_token_url=oauth_settings.request_token_url,
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            callback_url=api_callback,
            logger=ctx.logger,
        )

        oauth1_overrides = {
            "oauth_token": request_token_response.oauth_token,
            "oauth_token_secret": request_token_response.oauth_token_secret,
            "consumer_key": consumer_key,
            "consumer_secret": consumer_secret,
        }

        provider_auth_url = oauth1_service.build_authorization_url(
            authorization_url=oauth_settings.authorization_url,
            oauth_token=request_token_response.oauth_token,
            scope=oauth_settings.scope,
            expiration=oauth_settings.expiration,
        )

        ctx.logger.debug(f"OAuth1 request token obtained for {source.short_name}")

        async with UnitOfWork(db) as uow:
            source_conn = await self._create_source_connection(
                uow.session,
                obj_in,
                connection_id=None,
                collection_id=obj_in.readable_collection_id,
                sync_id=None,
                config_fields=validated_config,
                is_authenticated=False,
                ctx=ctx,
                uow=uow,
            )

            proxy_url, proxy_expiry, redirect_session_id = await self._create_proxy_url(
                uow.session, provider_auth_url, ctx, uow
            )

            init_session = await self._create_init_session(
                uow.session,
                obj_in,
                state,
                ctx,
                uow,
                redirect_session_id=redirect_session_id,
                additional_overrides=oauth1_overrides,
            )

            source_conn.connection_init_session_id = init_session.id
            uow.session.add(source_conn)

            source_conn.authentication_url = proxy_url
            source_conn.authentication_url_expiry = proxy_expiry

            await uow.commit()
            await uow.session.refresh(source_conn)

        return await self._build_source_connection_response(db, source_conn, ctx)

    async def _create_with_oauth2_browser(
        self,
        db: AsyncSession,
        obj_in: SourceConnectionCreate,
        oauth_settings: OAuth2Settings,
        ctx: ApiContext,
    ) -> SourceConnection:
        """Create shell connection and start OAuth2 browser flow."""
        source = await self._get_and_validate_source(db, obj_in.short_name)

        oauth_auth = None
        if obj_in.authentication is not None:
            if not isinstance(obj_in.authentication, OAuthBrowserAuthentication):
                raise HTTPException(
                    status_code=400, detail="Invalid authentication type for OAuth browser"
                )
            oauth_auth = obj_in.authentication
        else:
            oauth_auth = OAuthBrowserAuthentication()

        if source.requires_byoc:
            if not oauth_auth.client_id or not oauth_auth.client_secret:
                raise HTTPException(
                    status_code=400,
                    detail=f"Source '{source.name}' requires BYOC (Bring Your Own Credentials). "
                    f"You must provide both client_id and client_secret in the auth object.",
                )

        validated_config = await self._validate_config_fields(
            db, obj_in.short_name, obj_in.config, ctx
        )
        template_configs = await self._validate_and_extract_template_configs(
            db, source, validated_config, ctx
        )

        oauth_settings = await integration_settings.get_by_short_name(source.short_name)
        if not oauth_settings:
            raise HTTPException(
                status_code=400,
                detail=f"OAuth not configured for source: {source.short_name}",
            )

        state = secrets.token_urlsafe(24)
        api_callback = f"{core_settings.api_url}/source-connections/callback"
        client_id = oauth_auth.client_id if oauth_auth.client_id else None

        provider_auth_url, code_verifier = await oauth2_service.generate_auth_url_with_redirect(
            oauth_settings,
            redirect_uri=api_callback,
            client_id=client_id,
            state=state,
            template_configs=template_configs,
        )

        oauth2_overrides = {}
        if code_verifier:
            oauth2_overrides["code_verifier"] = code_verifier
            ctx.logger.debug(
                f"Generated PKCE challenge for {source.short_name} (code_verifier stored)"
            )

        async with UnitOfWork(db) as uow:
            source_conn = await self._create_source_connection(
                uow.session,
                obj_in,
                connection_id=None,
                collection_id=obj_in.readable_collection_id,
                sync_id=None,
                config_fields=validated_config,
                is_authenticated=False,
                ctx=ctx,
                uow=uow,
            )

            proxy_url, proxy_expiry, redirect_session_id = await self._create_proxy_url(
                uow.session, provider_auth_url, ctx, uow
            )

            init_session = await self._create_init_session(
                uow.session,
                obj_in,
                state,
                ctx,
                uow,
                redirect_session_id=redirect_session_id,
                template_configs=template_configs,
                additional_overrides=oauth2_overrides,
            )

            source_conn.connection_init_session_id = init_session.id
            uow.session.add(source_conn)

            source_conn.authentication_url = proxy_url
            source_conn.authentication_url_expiry = proxy_expiry

            await uow.commit()
            await uow.session.refresh(source_conn)

        return await self._build_source_connection_response(db, source_conn, ctx)

    async def _create_with_oauth1_byoc(
        self,
        db: AsyncSession,
        obj_in: SourceConnectionCreate,
        oauth_settings: OAuth1Settings,
        ctx: ApiContext,
    ) -> SourceConnection:
        """Create connection with bring-your-own-client OAuth1."""
        if not obj_in.authentication or not isinstance(
            obj_in.authentication, OAuthBrowserAuthentication
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "OAuth1 BYOC requires OAuth browser authentication with consumer credentials"
                ),
            )

        if not obj_in.authentication.consumer_key or not obj_in.authentication.consumer_secret:
            raise HTTPException(
                status_code=400, detail="OAuth1 BYOC requires consumer_key and consumer_secret"
            )

        return await self._create_with_oauth1_browser(
            db,
            obj_in=obj_in,
            oauth_settings=oauth_settings,
            ctx=ctx,
            custom_consumer_key=obj_in.authentication.consumer_key,
            custom_consumer_secret=obj_in.authentication.consumer_secret,
        )

    async def _create_with_oauth2_byoc(
        self,
        db: AsyncSession,
        obj_in: SourceConnectionCreate,
        oauth_settings: OAuth2Settings,
        ctx: ApiContext,
    ) -> SourceConnection:
        """Create connection with bring-your-own-client OAuth2."""
        if not obj_in.authentication or not isinstance(
            obj_in.authentication, OAuthBrowserAuthentication
        ):
            raise HTTPException(
                status_code=400,
                detail="OAuth2 BYOC requires OAuth browser authentication with client credentials",
            )

        if not obj_in.authentication.client_id or not obj_in.authentication.client_secret:
            raise HTTPException(
                status_code=400, detail="OAuth2 BYOC requires client_id and client_secret"
            )

        return await self._create_with_oauth2_browser(
            db, obj_in=obj_in, oauth_settings=oauth_settings, ctx=ctx
        )
