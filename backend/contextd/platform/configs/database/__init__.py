"""Database schema configuration module.

Provides schema definition, metadata, and conversion utilities for database tables
with graph/LLM/embedding configuration.
"""

from contextd.platform.configs.database.converter import (
    convert_table_metadata_to_entity_metadata,
    get_python_type,
)
from contextd.platform.configs.database.factory import (
    DatabaseSchemaConverter,
    create_entity_class_from_table_def,
)
from contextd.platform.configs.database.loader import DatabaseSchemaLoader
from contextd.platform.configs.database.metadata import ColumnMetadata, TableMetadata
from contextd.platform.configs.database.registry import DatabaseSchemaRegistry
from contextd.platform.configs.database.schema import (
    DatabaseColumn,
    DatabaseTable,
    ForeignKeyConfig,
    IndexConfig,
)

__all__ = [
    "DatabaseColumn",
    "DatabaseTable",
    "ForeignKeyConfig",
    "IndexConfig",
    "ColumnMetadata",
    "TableMetadata",
    "DatabaseSchemaRegistry",
    "DatabaseSchemaLoader",
    "DatabaseSchemaConverter",
    "create_entity_class_from_table_def",
    "convert_table_metadata_to_entity_metadata",
    "get_python_type",
]
