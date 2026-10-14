"""OAuth session helper methods for source connections."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud
from contextd.api.context import ApiContext
from contextd.core.config import settings as core_settings
from contextd.crud import connection_init_session, redirect_session
from contextd.models.connection_init_session import ConnectionInitStatus
from contextd.models.source_connection import SourceConnection
from contextd.platform.auth.oauth1_service import oauth1_service
from contextd.platform.auth.oauth2_service import oauth2_service
from contextd.platform.auth.schemas import OAuth1Settings

if TYPE_CHECKING:
    from contextd.platform.auth.oauth1_service import OAuth1TokenResponse
    from contextd.platform.auth.schemas import OAuth2TokenResponse


class SourceConnectionOAuthSessionHelpersMixin:
    """Create OAuth sessions, proxy URLs, and exchange OAuth callback codes."""

    async def create_init_session(  # noqa: C901
        self,
        db: AsyncSession,
        obj_in: Any,
        state: str,
        ctx: ApiContext,
        uow: Any,
        redirect_session_id: Optional[UUID] = None,
        template_configs: Optional[dict] = None,
        additional_overrides: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Create connection init session for OAuth flow."""
        source_type = getattr(obj_in, "source_type", None) or getattr(obj_in, "short_name", None)

        exclude_fields = {
            "client_id",
            "client_secret",
            "token_inject",
            "redirect_url",
            "auth_mode",
            "custom_client",
            "auth_method",
            "authentication",
        }
        payload = obj_in.model_dump(
            exclude=exclude_fields,
            exclude_none=True,
        )

        client_id: Optional[str] = None
        client_secret: Optional[str] = None
        oauth_client_mode = "platform_default"

        def _require_both_or_neither(cid: Optional[str], csec: Optional[str]) -> None:
            if (cid and not csec) or (csec and not cid):
                raise HTTPException(
                    status_code=422,
                    detail="Custom OAuth requires both client_id and client_secret or neither",
                )

        auth_obj = getattr(obj_in, "authentication", None)
        nested_id = getattr(auth_obj, "client_id", None) if auth_obj is not None else None
        nested_secret = getattr(auth_obj, "client_secret", None) if auth_obj is not None else None
        if nested_id or nested_secret:
            _require_both_or_neither(nested_id, nested_secret)
            if nested_id and nested_secret:
                client_id, client_secret = nested_id, nested_secret
                oauth_client_mode = "byoc_nested"
        else:
            custom_client = getattr(obj_in, "custom_client", None)
            if custom_client:
                cc_id = getattr(custom_client, "client_id", None)
                cc_secret = getattr(custom_client, "client_secret", None)
                if cc_id or cc_secret:
                    _require_both_or_neither(cc_id, cc_secret)
                    if cc_id and cc_secret:
                        client_id, client_secret = cc_id, cc_secret
                        oauth_client_mode = "byoc_custom_client"
            elif hasattr(obj_in, "client_id") or hasattr(obj_in, "client_secret"):
                top_id = getattr(obj_in, "client_id", None)
                top_secret = getattr(obj_in, "client_secret", None)
                if top_id or top_secret:
                    _require_both_or_neither(top_id, top_secret)
                    if top_id and top_secret:
                        client_id, client_secret = top_id, top_secret
                        oauth_client_mode = "byoc_top_level"

        overrides = {
            "client_id": client_id,
            "client_secret": client_secret,
            "oauth_client_mode": oauth_client_mode,
            "redirect_url": getattr(obj_in, "redirect_url", core_settings.app_url),
            "oauth_redirect_uri": f"{core_settings.api_url}/source-connections/callback",
            "template_configs": template_configs,
        }

        if additional_overrides:
            overrides.update(additional_overrides)

        expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)

        return await connection_init_session.create(
            db,
            obj_in={
                "organization_id": ctx.organization.id,
                "short_name": source_type,
                "payload": payload,
                "overrides": overrides,
                "state": state,
                "status": ConnectionInitStatus.PENDING,
                "expires_at": expires_at,
                "redirect_session_id": redirect_session_id,
            },
            ctx=ctx,
            uow=uow,
        )

    async def create_proxy_url(
        self, db: AsyncSession, provider_auth_url: str, ctx: ApiContext, uow: Any = None
    ) -> Tuple[str, datetime, UUID]:
        """Create proxy URL for OAuth flow."""
        proxy_ttl = 1440
        proxy_expires = datetime.now(timezone.utc) + timedelta(minutes=proxy_ttl)
        code8 = await redirect_session.generate_unique_code(db, length=8)

        redirect_sess = await redirect_session.create(
            db,
            code=code8,
            final_url=provider_auth_url,
            expires_at=proxy_expires,
            ctx=ctx,
            uow=uow,
        )

        proxy_url = f"{core_settings.api_url}/source-connections/authorize/{code8}"
        return proxy_url, proxy_expires, redirect_sess.id

    async def exchange_oauth1_code(
        self,
        short_name: str,
        verifier: str,
        overrides: Dict[str, Any],
        oauth_settings: OAuth1Settings,
        ctx: ApiContext,
    ) -> "OAuth1TokenResponse":
        """Exchange OAuth1 verifier for access token."""
        ctx.logger.info(f"Exchanging OAuth1 verifier for access token: {short_name}")

        return await oauth1_service.exchange_token(
            access_token_url=oauth_settings.access_token_url,
            consumer_key=oauth_settings.consumer_key,
            consumer_secret=oauth_settings.consumer_secret,
            oauth_token=overrides.get("oauth_token", ""),
            oauth_token_secret=overrides.get("oauth_token_secret", ""),
            oauth_verifier=verifier,
            logger=ctx.logger,
        )

    async def exchange_oauth2_code(
        self,
        short_name: str,
        code: str,
        overrides: Dict[str, Any],
        ctx: ApiContext,
    ) -> "OAuth2TokenResponse":
        """Exchange OAuth2 authorization code for access token."""
        redirect_uri = (
            overrides.get("oauth_redirect_uri")
            or f"{core_settings.api_url}/source-connections/callback"
        )

        template_configs = overrides.get("template_configs")
        code_verifier = overrides.get("code_verifier")

        return await oauth2_service.exchange_authorization_code_for_token_with_redirect(
            ctx=ctx,
            source_short_name=short_name,
            code=code,
            redirect_uri=redirect_uri,
            client_id=overrides.get("client_id"),
            client_secret=overrides.get("client_secret"),
            template_configs=template_configs,
            code_verifier=code_verifier,
        )

    async def _regenerate_oauth_url(
        self,
        db: AsyncSession,
        source_conn: SourceConnection,
        ctx: ApiContext,
    ) -> Tuple[Optional[str], Optional[datetime]]:
        """Regenerate OAuth authentication URL for an unauthenticated connection."""
        if source_conn.is_authenticated:
            return None, None

        if (
            not hasattr(source_conn, "connection_init_session_id")
            or not source_conn.connection_init_session_id
        ):
            return None, None

        init_session = await connection_init_session.get(
            db, id=source_conn.connection_init_session_id, ctx=ctx
        )
        if not init_session or init_session.status != ConnectionInitStatus.PENDING:
            return None, None

        source = await crud.source.get_by_short_name(db, short_name=source_conn.short_name)
        if not source:
            return None, None

        from contextd.platform.auth.settings import integration_settings

        oauth_settings = await integration_settings.get_by_short_name(source.short_name)
        if not oauth_settings:
            return None, None

        state = init_session.state
        api_callback = (
            init_session.overrides.get("oauth_redirect_uri")
            or f"{core_settings.api_url}/source-connections/callback"
        )

        template_configs = init_session.overrides.get("template_configs")
        provider_auth_url, code_verifier = await oauth2_service.generate_auth_url_with_redirect(
            oauth_settings,
            redirect_uri=api_callback,
            client_id=init_session.overrides.get("client_id"),
            state=state,
            template_configs=template_configs,
        )

        if code_verifier:
            init_session.overrides["code_verifier"] = code_verifier
            await crud.source_connection_init_session.update(
                db=db, db_obj=init_session, obj_in={"overrides": init_session.overrides}, ctx=ctx
            )

        proxy_url, proxy_expiry, _ = await self.create_proxy_url(db, provider_auth_url, ctx)

        return proxy_url, proxy_expiry
