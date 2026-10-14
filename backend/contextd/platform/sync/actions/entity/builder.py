"""Builder for entity action dispatcher."""

from typing import List, Optional

from contextd.core.logging import ContextualLogger
from contextd.platform.contexts.destinations import DestinationsContext
from contextd.platform.sync.actions.entity.dispatcher import EntityActionDispatcher
from contextd.platform.sync.config import SyncExecutionConfig
from contextd.platform.sync.handlers.arf import ArfHandler
from contextd.platform.sync.handlers.entity_postgres import EntityPostgresHandler
from contextd.platform.sync.handlers.protocol import EntityActionHandler


class EntityDispatcherBuilder:
    """Builds entity action dispatcher with configured handlers."""

    @classmethod
    def build(
        cls,
        destinations: DestinationsContext,
        execution_config: Optional[SyncExecutionConfig] = None,
        logger: Optional[ContextualLogger] = None,
    ) -> EntityActionDispatcher:
        """Build dispatcher with handlers based on config.

        Args:
            destinations: Destinations context retained for dispatcher signature compatibility
            execution_config: Optional config to enable/disable handlers
            logger: Optional logger for logging handler creation

        Returns:
            EntityActionDispatcher with configured handlers.
        """
        handlers = cls._build_handlers(destinations, execution_config, logger)
        return EntityActionDispatcher(handlers=handlers)

    @classmethod
    def build_for_cleanup(
        cls,
        destinations: DestinationsContext,
        logger: Optional[ContextualLogger] = None,
    ) -> EntityActionDispatcher:
        """Build dispatcher for cleanup operations (all handlers enabled).

        Args:
            destinations: Destinations context
            logger: Optional logger

        Returns:
            EntityActionDispatcher for cleanup.
        """
        return cls.build(destinations=destinations, execution_config=None, logger=logger)

    @classmethod
    def _build_handlers(
        cls,
        destinations: DestinationsContext,
        execution_config: Optional[SyncExecutionConfig],
        logger: Optional[ContextualLogger],
    ) -> List[EntityActionHandler]:
        """Build handler list based on config."""
        config = execution_config or SyncExecutionConfig.default()
        enable_arf = config.enable_raw_data_handler
        enable_postgres = config.enable_postgres_handler

        handlers: List[EntityActionHandler] = []

        if destinations.destinations and logger:
            logger.warning("Ignoring configured destinations; live sync persists through ARF/Postgres")

        cls._add_arf_handler(handlers, enable_arf, logger)
        cls._add_postgres_handler(handlers, enable_postgres, logger)

        if not handlers and logger:
            logger.warning("No handlers created - sync will fetch entities but not persist them")

        return handlers

    @classmethod
    def _add_arf_handler(
        cls,
        handlers: List[EntityActionHandler],
        enabled: bool,
        logger: Optional[ContextualLogger],
    ) -> None:
        """Add ARF handler if enabled."""
        if enabled:
            handlers.append(ArfHandler())
            if logger:
                logger.debug("Added ArfHandler")
        elif logger:
            logger.info("Skipping ArfHandler (disabled by execution_config)")

    @classmethod
    def _add_postgres_handler(
        cls,
        handlers: List[EntityActionHandler],
        enabled: bool,
        logger: Optional[ContextualLogger],
    ) -> None:
        """Add Postgres metadata handler if enabled (always last)."""
        if enabled:
            handlers.append(EntityPostgresHandler())
            if logger:
                logger.debug("Added EntityPostgresHandler")
        elif logger:
            logger.info("Skipping EntityPostgresHandler (disabled by execution_config)")
