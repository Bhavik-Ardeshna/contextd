"""Schema loader and validator.

Loads schema definitions from definition modules and validates them.
"""

from typing import Dict, List

from contextd.platform.configs.database.registry import DatabaseSchemaRegistry
from contextd.platform.configs.database.schema import DatabaseTable


class SchemaValidationError(Exception):
    """Raised when schema validation fails."""

    pass


class DatabaseSchemaLoader:
    """Loader for database schema definitions."""

    @staticmethod
    def load_schema_definitions(
        database_type: str,
        schema_definitions: Dict[str, DatabaseTable],
    ) -> None:
        """Load schema definitions into the registry.

        Args:
            database_type: Database type (e.g., 'postgres', 'mysql')
            schema_definitions: Dictionary mapping table keys to DatabaseTable definitions
        """
        DatabaseSchemaRegistry.register_schemas(database_type, schema_definitions)

    @staticmethod
    def validate_schema(table_def: DatabaseTable) -> List[str]:
        """Validate a schema definition.

        Args:
            table_def: DatabaseTable definition to validate

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Validate table name
        if not table_def.table_name:
            errors.append("Table name is required")

        # Validate schema name
        if not table_def.schema_name:
            errors.append("Schema name is required")

        # Validate columns
        if not table_def.columns:
            errors.append("Table must have at least one column")

        # Validate primary keys exist in columns
        for pk in table_def.primary_keys:
            if pk not in table_def.columns:
                errors.append(f"Primary key column '{pk}' not found in columns")

        # Validate foreign keys
        for fk in table_def.foreign_keys:
            if fk.column not in table_def.columns:
                errors.append(f"Foreign key column '{fk.column}' not found in columns")

        # Validate indexes
        for idx in table_def.indexes:
            for col in idx.columns:
                if col not in table_def.columns:
                    errors.append(f"Index column '{col}' not found in columns")

        # Validate metadata columns exist
        if table_def.table_metadata:
            for col_name in table_def.table_metadata.columns:
                if col_name not in table_def.columns:
                    errors.append(
                        f"Metadata column '{col_name}' not found in table columns"
                    )

        return errors

    @staticmethod
    def validate_all_schemas(
        database_type: str,
    ) -> Dict[str, List[str]]:
        """Validate all schemas for a database type.

        Args:
            database_type: Database type (e.g., 'postgres', 'mysql')

        Returns:
            Dictionary mapping table keys to lists of validation errors
        """
        schemas = DatabaseSchemaRegistry.get_all_schemas(database_type)
        validation_results = {}

        for table_key, table_def in schemas.items():
            errors = DatabaseSchemaLoader.validate_schema(table_def)
            if errors:
                validation_results[table_key] = errors

        return validation_results

    @staticmethod
    def ensure_schema_ready(
        table_def: DatabaseTable,
        raise_on_error: bool = True,
    ) -> bool:
        """Ensure schema is valid and ready to use.

        Args:
            table_def: DatabaseTable definition
            raise_on_error: If True, raise exception on validation error

        Returns:
            True if schema is valid, False otherwise

        Raises:
            SchemaValidationError: If validation fails and raise_on_error is True
        """
        errors = DatabaseSchemaLoader.validate_schema(table_def)

        if errors:
            if raise_on_error:
                error_msg = f"Schema validation failed for {table_def.get_table_key()}: {', '.join(errors)}"
                raise SchemaValidationError(error_msg)
            return False

        return True
