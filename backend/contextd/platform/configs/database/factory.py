"""Entity class factory for database tables with metadata.

Creates PolymorphicEntity classes with _entity_metadata attached.
"""

import logging
from typing import Any, Dict, Optional, Type

from contextd.platform.configs.database.converter import (
    convert_foreign_keys_to_graph_edges,
    convert_table_metadata_to_entity_metadata,
    get_python_type,
)
from contextd.platform.configs.database.schema import DatabaseTable
from contextd.platform.entities._base import PolymorphicEntity

logger = logging.getLogger(__name__)


class DatabaseSchemaConverter:
    """Converts DatabaseTable definitions to entity classes with metadata."""

    @staticmethod
    def convert_table_to_entity_class(
        table_def: DatabaseTable,
        column_mapping: Dict[str, str],
        all_tables: Optional[Dict[str, DatabaseTable]] = None,
    ) -> Type[PolymorphicEntity]:
        """Convert DatabaseTable to PolymorphicEntity with metadata.

        Args:
            table_def: DatabaseTable definition
            column_mapping: Dictionary mapping original column names to normalized names
            all_tables: Optional dictionary of all tables (for FK conversion)

        Returns:
            PolymorphicEntity class with _entity_metadata attached
        """
        # Convert columns to entity fields format
        columns_dict: Dict[str, Dict[str, Any]] = {}
        for col_name, col_def in table_def.columns.items():
            normalized_name = column_mapping.get(col_name, col_name)
            python_type = get_python_type(col_def.column_type)

            columns_dict[normalized_name] = {
                "python_type": python_type,
                "nullable": col_def.nullable,
                "default": col_def.default,
            }

        # Convert foreign keys to graph edges if we have all tables
        foreign_key_edges = None
        if all_tables and table_def.foreign_keys:
            foreign_key_edges = convert_foreign_keys_to_graph_edges(
                table_def, all_tables
            )
            logger.debug(
                f"Entity class {table_def.table_name}: "
                f"{len(foreign_key_edges)} FK edge(s) "
                f"from {len(table_def.foreign_keys)} FK(s)"
            )
        else:
            logger.debug(
                f"Entity class {table_def.table_name}: "
                f"no FK edges (all_tables={bool(all_tables)}, "
                f"fks={len(table_def.foreign_keys)})"
            )

        # Convert TableMetadata → EntityMetadata
        if table_def.table_metadata:
            entity_metadata = convert_table_metadata_to_entity_metadata(
                table_def.table_metadata,
                column_mapping,
                foreign_key_edges=foreign_key_edges,
            )
        else:
            # No metadata defined, create empty EntityMetadata
            from contextd.platform.entities._metadata import EntityMetadata

            entity_metadata = EntityMetadata()

        # Create entity class using PolymorphicEntity factory
        entity_class = PolymorphicEntity.create_table_entity_class(
            table_name=table_def.table_name,
            schema_name=table_def.schema_name,
            columns=columns_dict,
            primary_keys=table_def.primary_keys,
        )

        # Attach metadata as ClassVar (like GmailEntity._entity_metadata)
        entity_class._entity_metadata = entity_metadata

        return entity_class


def create_entity_class_from_table_def(
    table_def: DatabaseTable,
    column_mapping: Dict[str, str],
    all_tables: Optional[Dict[str, DatabaseTable]] = None,
) -> Type[PolymorphicEntity]:
    """Convenience function to create entity class from table definition.

    Args:
        table_def: DatabaseTable definition
        column_mapping: Dictionary mapping original column names to normalized names
        all_tables: Optional dictionary of all tables (for FK conversion)

    Returns:
        PolymorphicEntity class with _entity_metadata attached
    """
    return DatabaseSchemaConverter.convert_table_to_entity_class(
        table_def, column_mapping, all_tables
    )
