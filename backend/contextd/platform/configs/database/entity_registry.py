"""Registry for dynamically created database entity classes.

Tracks dynamically created entity classes and maps them to their entity definition IDs.
This is needed because dynamically created classes (like LeadsTableEntity) cannot be
imported from modules, so they need to be registered separately.
"""

from typing import Dict, Optional, Type
from uuid import UUID

from contextd.platform.entities._base import BaseEntity


class DatabaseEntityClassRegistry:
    """Registry for dynamically created database entity classes.

    Maps entity classes to their entity definition IDs. This is necessary because
    dynamically created entity classes (e.g., LeadsTableEntity) cannot be imported
    from modules like regular entity classes.
    """

    _entity_class_to_definition_id: Dict[Type[BaseEntity], UUID] = {}
    _table_key_to_entity_class: Dict[str, Type[BaseEntity]] = {}

    @classmethod
    def register_entity_class(
        cls,
        table_key: str,
        entity_class: Type[BaseEntity],
        entity_definition_id: UUID,
    ) -> None:
        """Register a dynamically created entity class.

        Args:
            table_key: Table key in format 'schema.table'
            entity_class: The dynamically created entity class
            entity_definition_id: The entity definition ID from the database
        """
        cls._entity_class_to_definition_id[entity_class] = entity_definition_id
        cls._table_key_to_entity_class[table_key] = entity_class

    @classmethod
    def get_entity_definition_id(
        cls,
        entity_class: Type[BaseEntity],
    ) -> Optional[UUID]:
        """Get entity definition ID for an entity class.

        Args:
            entity_class: The entity class

        Returns:
            Entity definition ID if found, None otherwise
        """
        return cls._entity_class_to_definition_id.get(entity_class)

    @classmethod
    def get_entity_class(cls, table_key: str) -> Optional[Type[BaseEntity]]:
        """Get entity class for a table key.

        Args:
            table_key: Table key in format 'schema.table'

        Returns:
            Entity class if found, None otherwise
        """
        return cls._table_key_to_entity_class.get(table_key)

    @classmethod
    def get_all_registered_classes(cls) -> Dict[Type[BaseEntity], UUID]:
        """Get all registered entity classes and their definition IDs.

        Returns:
            Dictionary mapping entity classes to entity definition IDs
        """
        return cls._entity_class_to_definition_id.copy()

    @classmethod
    def clear(cls) -> None:
        """Clear all registered entity classes."""
        cls._entity_class_to_definition_id.clear()
        cls._table_key_to_entity_class.clear()
