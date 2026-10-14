"""Clean source connection service with auth method inference."""

from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import schemas
from contextd.analytics import business_events
from contextd.api.context import ApiContext
from contextd.core.source_connection_creation_shared import (
    SourceConnectionCreationSharedMixin,
)
from contextd.core.source_connection_crud_operations import (
    SourceConnectionCrudOperationsMixin,
)
from contextd.core.source_connection_jobs import SourceConnectionJobsMixin
from contextd.core.source_connection_oauth_callbacks import (
    SourceConnectionOAuthCallbacksMixin,
)
from contextd.core.source_connection_oauth_creation import (
    SourceConnectionOAuthCreationMixin,
)
from contextd.core.source_connection_schedule import SourceConnectionScheduleMixin
from contextd.models.source_connection import SourceConnection as SourceConnectionModel
from contextd.platform.auth.settings import integration_settings
from contextd.platform.sources._base import BaseSource
from contextd.schemas.source_connection import (
    AuthenticationMethod,
    AuthProviderAuthentication,
    DirectAuthentication,
    OAuthBrowserAuthentication,
    OAuthTokenAuthentication,
    SourceConnection,
    SourceConnectionCreate,
)


class SourceConnectionService(
    SourceConnectionScheduleMixin,
    SourceConnectionCrudOperationsMixin,
    SourceConnectionJobsMixin,
    SourceConnectionCreationSharedMixin,
    SourceConnectionOAuthCreationMixin,
    SourceConnectionOAuthCallbacksMixin,
):
    """Service for managing source connections and their lifecycle."""

    async def _validate_and_extract_template_configs(
        self,
        db: AsyncSession,
        source: schemas.Source,
        validated_config: Optional[dict],
        ctx: ApiContext,
    ) -> Optional[dict]:
        """Validate and extract template config fields for OAuth flows.

        Template configs are config fields that are required before OAuth can begin
        (e.g., instance URLs like Zendesk subdomain).

        Args:
            db: Database session
            source: Source model
            validated_config: Already validated config dictionary
            ctx: API context

        Returns:
            Dictionary of template configs or None if not applicable

        Raises:
            HTTPException: If required template configs are missing or invalid
        """
        template_configs = None
        if source.config_class and validated_config is not None:
            from contextd.platform.locator import resource_locator

            try:
                config_class = resource_locator.get_config(source.config_class)

                # Check if this source has template config fields
                template_config_fields = config_class.get_template_config_fields()

                if template_config_fields:
                    # Validate template config fields are present
                    # (even if validated_config is empty dict)
                    try:
                        config_class.validate_template_configs(validated_config)
                        template_configs = config_class.extract_template_configs(
                            validated_config
                        )

                        ctx.logger.info(
                            f"✅ Validated template configs for {source.short_name}: "
                            f"{list(template_configs.keys())}"
                        )
                    except ValueError as e:
                        raise HTTPException(status_code=422, detail=str(e))
            except HTTPException:
                # Re-raise HTTP exceptions (like validation errors)
                raise
            except Exception as e:
                # Log but don't fail if config class not found (backward compatibility)
                ctx.logger.warning(
                    f"Could not load config class for {source.short_name}: {e}"
                )

        return template_configs

    """Clean service with automatic auth method inference.

    Key improvements:
    - Auth method automatically inferred from request body
    - Uses AuthenticationMethod enum consistently
    - Clean separation of concerns
    """

    async def ensure_single_connection_slot(
        self,
        db: AsyncSession,
        *,
        readable_collection_id: str,
        ctx: ApiContext,
    ) -> None:
        """Enforce the current one-source-per-context-database product limit."""
        lock_key = f"{ctx.organization.id}:{readable_collection_id}:source_connection"
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": lock_key},
        )
        result = await db.execute(
            select(func.count(SourceConnectionModel.id))
            .where(SourceConnectionModel.organization_id == ctx.organization.id)
            .where(
                SourceConnectionModel.readable_collection_id == readable_collection_id
            )
        )
        existing_count = result.scalar_one() or 0
        if existing_count:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This context database already has a source connection. "
                    "Only one connection per database is supported in this phase."
                ),
            )

    def _determine_auth_method(
        self, obj_in: SourceConnectionCreate, source_class: type[BaseSource]
    ) -> AuthenticationMethod:
        """Determine authentication method from the nested authentication object.

        Args:
            obj_in: The source connection creation request
            source_class: The source class to check supported auth methods

        Returns:
            The determined authentication method

        Raises:
            HTTPException: If authentication type cannot be determined
        """
        auth = obj_in.authentication

        # If no authentication provided, infer based on source capabilities
        if auth is None:
            return AuthenticationMethod.OAUTH_BROWSER

        if isinstance(auth, DirectAuthentication):
            return AuthenticationMethod.DIRECT
        elif isinstance(auth, OAuthTokenAuthentication):
            return AuthenticationMethod.OAUTH_TOKEN
        elif isinstance(auth, OAuthBrowserAuthentication):
            # Check if BYOC based on presence of custom credentials
            # OAuth2 BYOC: client_id + client_secret
            # OAuth1 BYOC: consumer_key + consumer_secret
            has_oauth2_byoc = auth.client_id and auth.client_secret
            has_oauth1_byoc = auth.consumer_key and auth.consumer_secret

            if has_oauth2_byoc or has_oauth1_byoc:
                return AuthenticationMethod.OAUTH_BYOC
            else:
                return AuthenticationMethod.OAUTH_BROWSER
        elif isinstance(auth, AuthProviderAuthentication):
            return AuthenticationMethod.AUTH_PROVIDER
        else:
            raise HTTPException(
                status_code=400, detail="Invalid authentication configuration"
            )

    async def create(  # noqa: C901
        self,
        db: AsyncSession,
        *,
        obj_in: SourceConnectionCreate,
        ctx: ApiContext,
    ) -> SourceConnection:
        """Create a source connection with nested authentication.

        The authentication method is determined by the type of the authentication field.
        """
        await self.ensure_single_connection_slot(
            db,
            readable_collection_id=obj_in.readable_collection_id,
            ctx=ctx,
        )

        # Get source and validate
        source = await self._get_and_validate_source(db, obj_in.short_name)
        source_class = self._get_source_class(source.class_name)

        # Generate default name if not provided
        if obj_in.name is None:
            obj_in.name = f"{source.name} Connection"

        # Determine auth method from nested authentication type
        auth_method = self._determine_auth_method(obj_in, source_class)

        # Validate that source supports the auth method
        if not source_class.supports_auth_method(auth_method):
            supported = source_class.get_supported_auth_methods()
            raise HTTPException(
                status_code=400,
                detail=f"Source {obj_in.short_name} does not support this authentication method. "
                f"Supported methods: {[m.value for m in supported]}",
            )

        # Validate BYOC requirement: If source requires BYOC, auth method must be OAUTH_BYOC
        if (
            source_class.requires_byoc()
            and auth_method == AuthenticationMethod.OAUTH_BROWSER
        ):
            raise HTTPException(
                status_code=400,
                detail=f"Source {obj_in.short_name} requires custom OAuth client credentials. "
                "Please provide client_id and client_secret in the authentication configuration.",
            )

        # Handle the edge case where authentication was None (defaults to OAuth browser)
        # and Pydantic couldn't determine the default
        if obj_in.sync_immediately is None:
            if auth_method in [
                AuthenticationMethod.OAUTH_BROWSER,
                AuthenticationMethod.OAUTH_BYOC,
            ]:
                obj_in.sync_immediately = False
            else:
                # Direct, OAuth token, and auth provider default to True
                obj_in.sync_immediately = True

        # Validate OAuth browser/BYOC cannot have sync_immediately=true
        if auth_method in [
            AuthenticationMethod.OAUTH_BROWSER,
            AuthenticationMethod.OAUTH_BYOC,
        ]:
            if obj_in.sync_immediately:
                raise HTTPException(
                    status_code=400,
                    detail="OAuth connections cannot use sync_immediately. "
                    "Sync will start after authentication.",
                )

        # Route based on auth method
        if auth_method == AuthenticationMethod.DIRECT:
            source_connection = await self._create_with_direct_auth(
                db, obj_in=obj_in, ctx=ctx
            )
        elif auth_method == AuthenticationMethod.OAUTH_BROWSER:
            # Determine OAuth1 vs OAuth2
            oauth_settings = await integration_settings.get_by_short_name(
                obj_in.short_name
            )
            from contextd.platform.auth.schemas import OAuth1Settings

            if isinstance(oauth_settings, OAuth1Settings):
                source_connection = await self._create_with_oauth1_browser(
                    db, obj_in=obj_in, oauth_settings=oauth_settings, ctx=ctx
                )
            else:
                source_connection = await self._create_with_oauth2_browser(
                    db, obj_in=obj_in, oauth_settings=oauth_settings, ctx=ctx
                )
        elif auth_method == AuthenticationMethod.OAUTH_TOKEN:
            source_connection = await self._create_with_oauth_token(
                db, obj_in=obj_in, ctx=ctx
            )
        elif auth_method == AuthenticationMethod.OAUTH_BYOC:
            # Determine OAuth1 vs OAuth2 BYOC
            oauth_settings = await integration_settings.get_by_short_name(
                obj_in.short_name
            )
            from contextd.platform.auth.schemas import OAuth1Settings

            if isinstance(oauth_settings, OAuth1Settings):
                source_connection = await self._create_with_oauth1_byoc(
                    db, obj_in=obj_in, oauth_settings=oauth_settings, ctx=ctx
                )
            else:
                source_connection = await self._create_with_oauth2_byoc(
                    db, obj_in=obj_in, oauth_settings=oauth_settings, ctx=ctx
                )
        elif auth_method == AuthenticationMethod.AUTH_PROVIDER:
            source_connection = await self._create_with_auth_provider(
                db, obj_in=obj_in, ctx=ctx
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported authentication method: {auth_method.value}",
            )

        # Track analytics
        business_events.track_source_connection_created(
            ctx=ctx,
            connection_id=source_connection.id,
            source_short_name=source_connection.short_name,
        )

        return source_connection

    # Import helper methods from existing helpers
    from contextd.core.source_connection_service_helpers import (
        source_connection_helpers,
    )

    _validate_auth_fields = source_connection_helpers.validate_auth_fields
    _validate_config_fields = source_connection_helpers.validate_config_fields
    _validate_direct_auth = source_connection_helpers.validate_direct_auth
    _validate_oauth_token = source_connection_helpers.validate_oauth_token
    _create_integration_credential = (
        source_connection_helpers.create_integration_credential
    )
    _create_connection = source_connection_helpers.create_connection
    _get_collection = source_connection_helpers.get_collection
    _get_connection_for_source_connection = (
        source_connection_helpers.get_connection_for_source_connection
    )
    _create_sync = source_connection_helpers.create_sync
    _create_sync_without_schedule = (
        source_connection_helpers.create_sync_without_schedule
    )
    _create_source_connection = source_connection_helpers.create_source_connection
    _build_source_connection_response = (
        source_connection_helpers.build_source_connection_response
    )
    _create_init_session = source_connection_helpers.create_init_session
    _create_proxy_url = source_connection_helpers.create_proxy_url
    _update_sync_schedule = source_connection_helpers.update_sync_schedule
    _update_auth_fields = source_connection_helpers.update_auth_fields
    _sync_job_to_source_connection_job = (
        source_connection_helpers.sync_job_to_source_connection_job
    )
    _reconstruct_context_from_session = (
        source_connection_helpers.reconstruct_context_from_session
    )
    _exchange_oauth1_code = source_connection_helpers.exchange_oauth1_code
    _exchange_oauth2_code = source_connection_helpers.exchange_oauth2_code
    _complete_oauth1_connection = source_connection_helpers.complete_oauth1_connection
    _complete_oauth2_connection = source_connection_helpers.complete_oauth2_connection


# Singleton instance
source_connection_service = SourceConnectionService()
