"""Helper methods for source connection service v2."""

from typing import List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud, schemas
from contextd.api.context import ApiContext
from contextd.core.shared_models import AuthMethod
from contextd.core.source_connection_oauth_completion_helpers import (
    SourceConnectionOAuthCompletionHelpersMixin,
)
from contextd.core.source_connection_oauth_session_helpers import (
    SourceConnectionOAuthSessionHelpersMixin,
)
from contextd.core.source_connection_persistence_helpers import (
    SourceConnectionPersistenceHelpersMixin,
)
from contextd.core.source_connection_response_helpers import (
    SourceConnectionResponseHelpersMixin,
)
from contextd.core.source_connection_validation_helpers import (
    SourceConnectionValidationHelpersMixin,
)
from contextd.models.connection_init_session import ConnectionInitSession


class SourceConnectionHelpers(
    SourceConnectionValidationHelpersMixin,
    SourceConnectionPersistenceHelpersMixin,
    SourceConnectionOAuthSessionHelpersMixin,
    SourceConnectionOAuthCompletionHelpersMixin,
    SourceConnectionResponseHelpersMixin,
):
    """Helper methods for source connection service."""

    async def _get_destination_connection_ids(
        self, db: AsyncSession, ctx: ApiContext
    ) -> list[UUID]:
        """Return persisted sync destination connection IDs.

        Args:
            db: Database session
            ctx: API context with organization and feature flags

        Returns:
            Empty list. ContextD runtime indexing is handled by IndexHandler rather than
            persisted sync destination connections.
        """
        return []

    async def _validate_destination_consistency(
        self,
        db: AsyncSession,
        collection_readable_id: str,
        new_destination_ids: List[UUID],
        ctx: ApiContext,
    ) -> None:
        """Validate destination consistency for new source connections.

        ContextD no longer persists live sync destination connections. This method is
        retained as a no-op for service call-site compatibility.

        Args:
            db: Database session
            collection_readable_id: Collection readable ID
            new_destination_ids: Destination IDs for the new source connection
            ctx: API context

        """
        return

    def _get_default_cron_schedule(self, ctx: ApiContext) -> str:
        """Generate a default daily cron schedule based on current UTC time.

        Returns:
            A cron expression for daily execution at the current UTC time.
        """
        from datetime import datetime, timezone

        now_utc = datetime.now(timezone.utc)
        minute = now_utc.minute
        hour = now_utc.hour
        # Format: minute hour day_of_month month day_of_week
        # e.g., "30 14 * * *" = run at 14:30 every day
        cron_schedule = f"{minute} {hour} * * *"
        ctx.logger.info(
            f"No cron schedule provided, defaulting to daily at {hour:02d}:{minute:02d} UTC"
        )
        return cron_schedule

    async def reconstruct_context_from_session(
        self, db: AsyncSession, init_session: ConnectionInitSession
    ) -> ApiContext:
        """Reconstruct ApiContext from stored session data.

        Used for OAuth callbacks where the user is not authenticated with the platform.

        Args:
            db: Database session
            init_session: The ConnectionInitSession containing org and user info

        Returns:
            Reconstructed ApiContext for the session's organization
        """
        import uuid

        from contextd.core.logging import logger

        # Get the organization from the session
        organization = await crud.organization.get(
            db, id=init_session.organization_id, skip_access_validation=True
        )
        organization_schema = schemas.Organization.model_validate(
            organization, from_attributes=True
        )

        # Generate a request ID for tracking
        request_id = str(uuid.uuid4())

        # Create logger with context
        base_logger = logger.with_context(
            request_id=request_id,
            organization_id=str(organization_schema.id),
            organization_name=organization_schema.name,
            auth_method=AuthMethod.OAUTH_CALLBACK.value,  # Special auth method for OAuth callbacks
            context_base="oauth",
        )

        return ApiContext(
            request_id=request_id,
            organization=organization_schema,
            user=None,  # No user context for OAuth callbacks
            auth_method=AuthMethod.OAUTH_CALLBACK,
            auth_metadata={"session_id": str(init_session.id)},
            logger=base_logger,
        )


# Singleton instance
source_connection_helpers = SourceConnectionHelpers()
