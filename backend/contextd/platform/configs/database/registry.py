"""Schema registry for database table definitions.

Central registry for managing schema definitions by database type and table name.
"""

from typing import Dict, Optional

from contextd.platform.configs.database.schema import DatabaseTable


class DatabaseSchemaRegistry:
    """Central registry for database schema definitions.

    Supports multiple database types (postgres, mysql, etc.) and provides
    table-keyed lookup: {schema}.{table} → DatabaseTable
    """

    _schemas: Dict[str, Dict[str, DatabaseTable]] = {}

    @classmethod
    def register_schema(
        cls,
        database_type: str,
        table_key: str,
        table_def: DatabaseTable,
    ) -> None:
        """Register a schema definition for a database type.

        Args:
            database_type: Database type (e.g., 'postgres', 'mysql')
            table_key: Table key in format 'schema.table'
            table_def: DatabaseTable definition
        """
        if database_type not in cls._schemas:
            cls._schemas[database_type] = {}

        cls._schemas[database_type][table_key] = table_def

    @classmethod
    def register_schemas(
        cls,
        database_type: str,
        schemas: Dict[str, DatabaseTable],
    ) -> None:
        """Register multiple schema definitions at once.

        Args:
            database_type: Database type (e.g., 'postgres', 'mysql')
            schemas: Dictionary mapping table keys to DatabaseTable definitions
        """
        if database_type not in cls._schemas:
            cls._schemas[database_type] = {}

        cls._schemas[database_type].update(schemas)

    @classmethod
    def get_schema(
        cls,
        database_type: str,
        table_key: str,
    ) -> Optional[DatabaseTable]:
        """Get schema definition for a table.

        Args:
            database_type: Database type (e.g., 'postgres', 'mysql')
            table_key: Table key in format 'schema.table'

        Returns:
            DatabaseTable if found, None otherwise
        """
        return cls._schemas.get(database_type, {}).get(table_key)

    @classmethod
    def get_all_schemas(
        cls,
        database_type: str,
    ) -> Dict[str, DatabaseTable]:
        """Get all schema definitions for a database type.

        Args:
            database_type: Database type (e.g., 'postgres', 'mysql')

        Returns:
            Dictionary mapping table keys to DatabaseTable definitions
        """
        return cls._schemas.get(database_type, {}).copy()

    @classmethod
    def has_schema(
        cls,
        database_type: str,
        table_key: str,
    ) -> bool:
        """Check if a schema is registered.

        Args:
            database_type: Database type (e.g., 'postgres', 'mysql')
            table_key: Table key in format 'schema.table'

        Returns:
            True if schema exists, False otherwise
        """
        return table_key in cls._schemas.get(database_type, {})

    @classmethod
    def clear_schemas(cls, database_type: Optional[str] = None) -> None:
        """Clear all schemas or schemas for a specific database type.

        Args:
            database_type: Optional database type to clear. If None, clears all.
        """
        if database_type is None:
            cls._schemas.clear()
        elif database_type in cls._schemas:
            del cls._schemas[database_type]
