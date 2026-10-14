"""Database configuration loader and validator.

Loads and validates database configuration before sync starts.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from contextd.platform.configs.database.config import DatabaseGraphConfig
from contextd.platform.configs.database.loader import DatabaseSchemaLoader
from contextd.platform.configs.database.registry import DatabaseSchemaRegistry


class DatabaseConfigLoader:
    """Loader for database configuration."""

    @staticmethod
    async def load_database_config(
        db: AsyncSession,
        collection_id: UUID,
        connection_config: Optional[dict] = None,
        database_type: str = "postgres",
    ) -> Optional[DatabaseGraphConfig]:
        """Load database configuration for a collection.

        Args:
            db: Database session
            collection_id: Collection ID
            connection_config: Optional connection configuration
            database_type: Database type (e.g., 'postgres')

        Returns:
            DatabaseGraphConfig if database source, None otherwise
        """
        # Get schema definitions from registry
        schema_definitions = DatabaseSchemaRegistry.get_all_schemas(database_type)

        if not schema_definitions:
            return None

        # Build config
        config = DatabaseGraphConfig.from_collection(
            collection_id=collection_id,
            connection_config=connection_config,
            schema_definitions=schema_definitions,
        )

        return config

    @staticmethod
    def validate_config(config: DatabaseGraphConfig) -> list[str]:
        """Validate database configuration.

        Args:
            config: DatabaseGraphConfig to validate

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Validate schema definitions
        for table_key, table_def in config.schema_definitions.items():
            schema_errors = DatabaseSchemaLoader.validate_schema(table_def)
            if schema_errors:
                errors.extend([f"{table_key}: {error}" for error in schema_errors])

        # Validate connection config if provided
        if config.connection:
            if not config.connection.host:
                errors.append("Connection host is required")
            if not config.connection.database:
                errors.append("Connection database is required")

        return errors

    @staticmethod
    async def ensure_services_ready(
        config: DatabaseGraphConfig,
    ) -> None:
        """Ensure LLM/embedding services are configured.

        This is a placeholder for future service initialization.
        Currently, services are initialized on-demand during sync.

        Args:
            config: DatabaseGraphConfig
        """
        # Future: Initialize LLM service with config.graph_llm
        # Future: Initialize embedding service with config.embedding
        pass
