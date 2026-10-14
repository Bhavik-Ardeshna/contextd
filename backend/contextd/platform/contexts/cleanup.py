"""Cleanup context for deletion operations."""

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from contextd.platform.contexts.destinations import DestinationsContext
from contextd.platform.contexts.infra import InfraContext
from contextd.platform.contexts.scope import ScopeContext

if TYPE_CHECKING:
    from contextd.api.context import ApiContext
    from contextd.core.logging import ContextualLogger


@dataclass
class CleanupContext:
    """Minimal context for cleanup/deletion operations.

    Implements HandlerContext protocol. Use for operations that need
    to delete entities without a full sync context.

    Sub-contexts:
    - scope: Scopes the operation
    - infra: Core infrastructure
    - destinations: Destinations to delete from
    """

    scope: ScopeContext
    infra: InfraContext
    destinations: DestinationsContext

    # -------------------------------------------------------------------------
    # HandlerContext Protocol Implementation
    # -------------------------------------------------------------------------

    @property
    def sync_id(self) -> UUID:
        """Sync ID for scoping operations."""
        return self.scope.sync_id

    @property
    def organization_id(self) -> UUID:
        """Organization ID for access control."""
        return self.scope.organization_id

    @property
    def logger(self) -> "ContextualLogger":
        """Logger for operations."""
        return self.infra.logger

    @property
    def ctx(self) -> "ApiContext":
        """API context for CRUD operations."""
        return self.infra.ctx

    # -------------------------------------------------------------------------
    # Convenience
    # -------------------------------------------------------------------------

    @property
    def collection_id(self) -> UUID:
        """Collection ID from scope."""
        return self.scope.collection_id

    @property
    def destination_list(self):
        """Shortcut to destinations.destinations."""
        return self.destinations.destinations
