"""Destinations context builder for sync operations.

Live sync persistence no longer writes through destination adapters. The builder
still loads the entity definition map used by entity metadata handling.
"""

import importlib
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud, schemas
from contextd.core.constants.reserved_ids import RESERVED_TABLE_ENTITY_ID
from contextd.core.logging import ContextualLogger
from contextd.db.init_db_native import init_db_with_entity_definitions
from contextd.platform.contexts.destinations import DestinationsContext
from contextd.platform.contexts.infra import InfraContext
from contextd.platform.destinations._base import BaseDestination
from contextd.platform.entities._base import BaseEntity
from contextd.platform.sync.config import SyncExecutionConfig


class DestinationsContextBuilder:
    """Builds destinations context with all required configuration."""

    @classmethod
    async def build(
        cls,
        db: AsyncSession,
        sync: schemas.Sync,
        collection: schemas.Collection,
        infra: InfraContext,
        execution_config: Optional[SyncExecutionConfig] = None,
    ) -> DestinationsContext:
        """Build complete destinations context.

        Args:
            db: Database session
            sync: Sync configuration
            collection: Target collection
            infra: Infrastructure context
            execution_config: Accepted for caller compatibility

        Returns:
            DestinationsContext with no live write destinations and the entity map.
        """
        entity_map = await cls._get_entity_definition_map(db=db)

        return DestinationsContext(
            destinations=[],
            entity_map=entity_map,
        )

    @classmethod
    async def build_for_collection(
        cls,
        db: AsyncSession,
        sync: schemas.Sync,
        collection: schemas.Collection,
        infra: InfraContext,
    ) -> DestinationsContext:
        """Build destinations context for collection-level operations.

        Simplified version without execution_config filtering.

        Args:
            db: Database session
            sync: Sync configuration
            collection: Target collection
            infra: Infrastructure context

        Returns:
            DestinationsContext with all configured destinations.
        """
        return await cls.build(
            db=db,
            sync=sync,
            collection=collection,
            infra=infra,
            execution_config=None,
        )

    @classmethod
    async def build_for_cleanup(
        cls,
        db: AsyncSession,
        collection: schemas.Collection,
        logger: ContextualLogger,
    ) -> List[BaseDestination]:
        """Build destinations for cleanup operations (no sync required).

        Live cleanup is owned by graph/ARF services, so no destination adapters are built.

        Args:
            db: Database session
            collection: Target collection
            logger: Logger for operations

        Returns:
            Empty list; destination cleanup adapters are not part of the live path.
        """
        logger.debug("No destination cleanup adapters are registered for the live path")
        return []

    # -------------------------------------------------------------------------
    # Private: Entity Definition Map
    # -------------------------------------------------------------------------

    @classmethod
    async def _get_entity_definition_map(cls, db: AsyncSession) -> Dict[type[BaseEntity], UUID]:
        """Get entity definition map (entity class -> entity_definition_id)."""
        # Ensure the reserved polymorphic entity definition exists (idempotent)
        await init_db_with_entity_definitions(db)

        entity_definitions = await crud.entity_definition.get_all(db)

        entity_definition_map = {}
        for entity_definition in entity_definitions:
            if entity_definition.id == RESERVED_TABLE_ENTITY_ID:
                continue
            # Skip LLM-extracted entity definitions (they don't have real Python classes)
            if entity_definition.module_name == "llm_extracted":
                continue

            # Handle database table entity definitions (dynamically created classes)
            if entity_definition.module_name == "contextd.platform.configs.database.definitions":
                # These are database table definitions - skip importing the config class
                # The actual entity classes are registered dynamically and will be added below
                continue

            full_module_name = f"contextd.platform.entities.{entity_definition.module_name}"
            try:
                module = importlib.import_module(full_module_name)
                entity_class = getattr(module, entity_definition.class_name)
                entity_definition_map[entity_class] = entity_definition.id
            except (ModuleNotFoundError, AttributeError):
                # Skip entity definitions that can't be imported
                # This can happen with dynamically created definitions
                continue

        # Add dynamically created database entity classes from registry
        from contextd.platform.configs.database.entity_registry import (
            DatabaseEntityClassRegistry,
        )

        registered_classes = DatabaseEntityClassRegistry.get_all_registered_classes()
        entity_definition_map.update(registered_classes)

        return entity_definition_map
