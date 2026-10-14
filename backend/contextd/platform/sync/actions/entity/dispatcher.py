"""Action dispatcher for entity persistence handlers."""

from typing import TYPE_CHECKING, List

from contextd.platform.sync.actions.entity.types import EntityActionBatch
from contextd.platform.sync.exceptions import SyncFailureError
from contextd.platform.sync.handlers.arf import ArfHandler
from contextd.platform.sync.handlers.entity_postgres import EntityPostgresHandler
from contextd.platform.sync.handlers.protocol import EntityActionHandler

if TYPE_CHECKING:
    from contextd.platform.contexts import SyncContext


class EntityActionDispatcher:
    """Dispatches resolved entity actions to ARF and PostgreSQL handlers."""

    def __init__(self, handlers: List[EntityActionHandler]):
        """Initialize dispatcher with handlers.

        Args:
            handlers: List of handlers to dispatch to (configured at factory time)
                     ArfHandler and EntityPostgresHandler are separated so ARF
                     capture happens before metadata writes.
        """
        self._arf_handler: ArfHandler | None = None
        self._postgres_handler: EntityPostgresHandler | None = None

        for handler in handlers:
            if isinstance(handler, EntityPostgresHandler):
                self._postgres_handler = handler
            elif isinstance(handler, ArfHandler):
                self._arf_handler = handler
            else:
                raise ValueError(f"Unsupported entity action handler: {handler.__class__.__name__}")

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def dispatch(
        self,
        batch: EntityActionBatch,
        sync_context: "SyncContext",
    ) -> None:
        """Dispatch action batch to the live persistence handlers.

        Args:
            batch: Resolved and processed action batch (with chunk_entities populated)
            sync_context: Sync context

        Raises:
            SyncFailureError: If any handler fails
        """
        if not batch.has_mutations:
            sync_context.logger.debug("[EntityDispatcher] No mutations to dispatch")
            return

        sync_context.logger.debug(
            f"[EntityDispatcher] Dispatching {batch.summary()} to ARF + PostgreSQL"
        )

        await self.dispatch_to_postgres_only(batch, sync_context)

    async def dispatch_to_postgres_only(
        self,
        batch: EntityActionBatch,
        sync_context: "SyncContext",
    ) -> None:
        """Dispatch action batch to ARF + PostgreSQL.

        Args:
            batch: Resolved action batch
            sync_context: Sync context

        Raises:
            SyncFailureError: If ARF or postgres handler fails
        """
        if not batch.has_mutations:
            sync_context.logger.debug("[EntityDispatcher] No mutations to dispatch")
            return

        sync_context.logger.debug(
            f"[EntityDispatcher] Dispatching {batch.summary()} to ARF + PostgreSQL"
        )

        # Execute ARF handler first (raw entity capture)
        if self._arf_handler:
            try:
                await self._dispatch_to_handler(self._arf_handler, batch, sync_context)
            except Exception as e:
                sync_context.logger.error(f"[EntityDispatcher] ARF handler failed: {e}")
                raise SyncFailureError(f"ARF handler failed: {e}")
        else:
            sync_context.logger.warning("[EntityDispatcher] No ARF handler configured")

        # Execute postgres handler (metadata storage)
        if self._postgres_handler:
            await self._dispatch_to_postgres(batch, sync_context)
        else:
            sync_context.logger.warning("[EntityDispatcher] No PostgreSQL handler configured")

        sync_context.logger.debug("[EntityDispatcher] ARF + PostgreSQL handlers completed successfully")

    async def dispatch_orphan_cleanup(
        self,
        orphan_entity_ids: List[str],
        sync_context: "SyncContext",
    ) -> None:
        """Dispatch orphan cleanup to ARF + PostgreSQL.

        Args:
            orphan_entity_ids: Entity IDs to clean up
            sync_context: Sync context

        Raises:
            SyncFailureError: If any handler fails cleanup
        """
        await self.dispatch_orphan_cleanup_postgres_only(orphan_entity_ids, sync_context)

    async def dispatch_orphan_cleanup_postgres_only(
        self,
        orphan_entity_ids: List[str],
        sync_context: "SyncContext",
    ) -> None:
        """Dispatch orphan cleanup to ARF + PostgreSQL.

        Args:
            orphan_entity_ids: Entity IDs to clean up
            sync_context: Sync context

        Raises:
            SyncFailureError: If ARF or postgres handler fails cleanup
        """
        if not orphan_entity_ids:
            return

        sync_context.logger.info(
            f"[EntityDispatcher] Dispatching orphan cleanup for {len(orphan_entity_ids)} entities "
            f"to ARF + PostgreSQL"
        )

        # Cleanup from ARF first
        if self._arf_handler:
            try:
                await self._dispatch_orphan_to_handler(
                    self._arf_handler, orphan_entity_ids, sync_context
                )
            except Exception as e:
                sync_context.logger.error(f"[EntityDispatcher] ARF orphan cleanup failed: {e}")
                # Don't raise - continue to postgres cleanup
        else:
            sync_context.logger.warning("[EntityDispatcher] No ARF handler for orphan cleanup")

        # Cleanup from PostgreSQL
        if self._postgres_handler:
            try:
                await self._dispatch_orphan_to_handler(
                    self._postgres_handler, orphan_entity_ids, sync_context
                )
            except Exception as e:
                raise SyncFailureError(f"[EntityDispatcher] PostgreSQL orphan cleanup failed: {e}")
        else:
            sync_context.logger.warning("[EntityDispatcher] No PostgreSQL handler for orphan cleanup")

    # -------------------------------------------------------------------------
    # Internal Methods
    # -------------------------------------------------------------------------

    async def _dispatch_to_postgres(
        self,
        batch: EntityActionBatch,
        sync_context: "SyncContext",
    ) -> None:
        """Dispatch to PostgreSQL metadata handler.

        Args:
            batch: Action batch
            sync_context: Sync context

        Raises:
            SyncFailureError: If postgres handler fails
        """
        try:
            await self._postgres_handler.handle_batch(batch, sync_context)
        except SyncFailureError:
            raise
        except Exception as e:
            sync_context.logger.error(
                f"[EntityDispatcher] PostgreSQL handler failed: {e}", exc_info=True
            )
            raise SyncFailureError(f"[EntityDispatcher] PostgreSQL failed: {e}")

    async def _dispatch_to_handler(
        self,
        handler: EntityActionHandler,
        batch: EntityActionBatch,
        sync_context: "SyncContext",
    ) -> None:
        """Dispatch to single handler with error wrapping.

        Args:
            handler: Handler to dispatch to
            batch: Action batch
            sync_context: Sync context

        Raises:
            SyncFailureError: If handler fails
        """
        try:
            await handler.handle_batch(batch, sync_context)
        except SyncFailureError:
            raise
        except Exception as e:
            sync_context.logger.error(
                f"[EntityDispatcher] Handler {handler.name} failed: {e}", exc_info=True
            )
            raise SyncFailureError(f"Handler {handler.name} failed: {e}")

    async def _dispatch_orphan_to_handler(
        self,
        handler: EntityActionHandler,
        orphan_entity_ids: List[str],
        sync_context: "SyncContext",
    ) -> None:
        """Dispatch orphan cleanup to single handler.

        Args:
            handler: Handler to dispatch to
            orphan_entity_ids: Entity IDs to clean up
            sync_context: Sync context

        Raises:
            SyncFailureError: If handler fails
        """
        try:
            await handler.handle_orphan_cleanup(orphan_entity_ids, sync_context)
        except SyncFailureError:
            raise
        except Exception as e:
            sync_context.logger.error(
                f"[EntityDispatcher] Handler {handler.name} orphan cleanup failed: {e}",
                exc_info=True,
            )
            raise SyncFailureError(f"Handler {handler.name} orphan cleanup failed: {e}")
