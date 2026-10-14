"""Entity definition registration for database tables.

Registers database tables as entity definitions so they appear in the
entity registry and can be used by the sync pipeline.
"""

from typing import Dict
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud, schemas
from contextd.models.entity_definition import EntityType
from contextd.platform.configs.database.registry import DatabaseSchemaRegistry


async def register_database_tables(
    db: AsyncSession,
    database_type: str = "postgres",
) -> Dict[str, UUID]:
    """Register database tables as entity definitions.

    Args:
        db: Database session
        database_type: Database type (e.g., 'postgres', 'mysql')

    Returns:
        Dictionary mapping entity names to entity_definition_ids
    """
    # Get all schema definitions for this database type
    schemas_dict = DatabaseSchemaRegistry.get_all_schemas(database_type)

    if not schemas_dict:
        return {}

    entity_definitions = []

    for _table_key, table_def in schemas_dict.items():
        # Create entity name from table key
        # Format: DatabaseTable_{schema}_{table}
        entity_name = f"DatabaseTable_{table_def.schema_name}_{table_def.table_name}"

        # Create entity definition
        entity_def = schemas.EntityDefinitionCreate(
            name=entity_name,
            description=table_def.description
            or f"Database table: {table_def.schema_name}.{table_def.table_name}",
            type=EntityType.JSON,
            entity_schema=table_def.model_dump(),
            module_name="contextd.platform.configs.database.definitions",
            class_name=table_def.__class__.__name__,
        )
        entity_definitions.append(entity_def)

    # Sync entity definitions (creates or updates)
    await crud.entity_definition.sync(db, entity_definitions, unique_field="name")

    # Get all entities to build the mapping
    all_entities = await crud.entity_definition.get_all(db)

    # Create mapping: entity_name -> entity_definition_id
    entity_map = {}
    for entity_def in all_entities:
        if entity_def.name.startswith(f"DatabaseTable_{database_type}_"):
            entity_map[entity_def.name] = entity_def.id

    return entity_map
