"""API endpoints for entity definitions, relations, and normalized data."""

from typing import List, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud, schemas
from contextd.api import deps
from contextd.api.context import ApiContext
from contextd.api.router import TrailingSlashRouter
from contextd.schemas.entity import EntityWithNormalized, NormalizedEntityData

router = TrailingSlashRouter()


@router.get("/definitions/", response_model=List[schemas.EntityDefinition])
async def list_entity_definitions(
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
) -> List[schemas.EntityDefinition]:
    """List all entity definitions for the current user's organization."""
    return await crud.entity_definition.get_multi(db, organization_id=ctx.organization.id)


@router.post("/definitions/", response_model=schemas.EntityDefinition)
async def create_entity_definition(
    definition: schemas.EntityDefinitionCreate,
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
) -> schemas.EntityDefinition:
    """Create a new entity definition."""
    return await crud.entity_definition.create(db, obj_in=definition, ctx=ctx)


@router.post("/definitions/by-ids/", response_model=List[schemas.EntityDefinition])
async def get_entity_definitions_by_ids(
    ids: List[UUID],
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
) -> List[schemas.EntityDefinition]:
    """Get multiple entity definitions by their IDs.

    Args:
        ids: List of entity definition IDs to fetch
        db: Database session
        ctx: Current authenticated user

    Returns:
        List of entity definitions matching the provided IDs
    """
    return await crud.entity_definition.get_multi_by_ids(db, ids=ids)


@router.get("/definitions/by-source/", response_model=List[schemas.EntityDefinition])
async def get_entity_definitions_by_source_short_name(
    source_short_name: str,
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
) -> List[schemas.EntityDefinition]:
    """Get all entity definitions for a given source."""
    entity_definitions = await crud.entity_definition.get_multi_by_source_short_name(
        db, source_short_name=source_short_name
    )
    entity_definition_schemas = [
        schemas.EntityDefinition.model_validate(entity_definition)
        for entity_definition in entity_definitions
    ]
    return entity_definition_schemas


@router.get("/count-by-sync/{sync_id}", response_model=schemas.EntityCount)
async def get_entity_count_by_sync_id(
    sync_id: UUID,
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
) -> Optional[schemas.EntityCount]:
    """Get the count of entities for a specific sync.

    Args:
        sync_id: The sync ID to count entities for
        db: Database session
        ctx: Current authenticated user

    Returns:
        Count of entities for the specified sync ID
    """
    # will throw 403 if the user doesn't have access to the sync
    sync = await crud.sync.get(db, id=sync_id, ctx=ctx)
    # or return None if the sync doesn't exist
    if not sync:
        raise HTTPException(status_code=404, detail="Sync not found")

    count = await crud.entity.get_count_by_sync_id(db, sync_id=sync_id)
    return schemas.EntityCount(count=count)


@router.get("/samples/{sync_id}", response_model=List[dict])
async def get_sample_entities(
    sync_id: UUID,
    entity_type: Optional[str] = None,
    limit: int = 5,
    include_normalized: bool = Query(True, description="Include normalized data from PostgreSQL"),
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
) -> List[dict]:
    """Get sample entity data for UI display.

    This endpoint retrieves entity data from ARF storage and enriches it
    with normalized data from PostgreSQL for display in the UI.

    Args:
        sync_id: The sync ID to fetch entities from
        entity_type: Optional entity type filter (e.g., "AsanaTaskEntity")
        limit: Maximum number of samples to return (default: 5, max: 20)
        include_normalized: Include normalized data from PostgreSQL (default: True)
        db: Database session
        ctx: Current authenticated user

    Returns:
        List of entity dictionaries with full data and normalized schema for display

    Raises:
        HTTPException: If sync not found or user doesn't have access
    """
    from contextd.platform.storage.arf_reader import ArfReader
    from contextd.platform.storage.exceptions import StorageNotFoundError

    # Verify access to sync
    sync = await crud.sync.get(db, id=sync_id, ctx=ctx)
    if not sync:
        raise HTTPException(status_code=404, detail="Sync not found")

    # Limit maximum samples
    limit = min(limit, 20)

    try:
        # Initialize ARF reader
        reader = ArfReader(
            sync_id=sync_id,
            logger=ctx.logger,
            restore_files=False,  # Don't restore files for display
        )

        # Read entity dictionaries from ARF storage
        samples = []
        entity_ids = []
        async for entity_dict in reader.iter_entity_dicts(batch_size=limit * 2):
            # Filter by entity type if specified
            if entity_type:
                entity_class = entity_dict.get("__entity_class__")
                if entity_class != entity_type:
                    continue

            # Remove internal metadata fields for cleaner display
            display_dict = {
                k: v
                for k, v in entity_dict.items()
                if not k.startswith("__") and k != "contextd_system_metadata"
            }

            # Add entity type for display
            display_dict["__entity_type__"] = entity_dict.get("__entity_class__", "Unknown")

            # Track entity_id for fetching normalized data
            if "entity_id" in entity_dict:
                entity_ids.append(entity_dict["entity_id"])

            samples.append(display_dict)

            if len(samples) >= limit:
                break

        # Enrich with normalized data from PostgreSQL if requested
        if include_normalized and entity_ids:
            normalized_map = await crud.entity.bulk_get_by_entity_and_sync(
                db=db,
                sync_id=sync_id,
                entity_ids=entity_ids,
            )

            for sample in samples:
                entity_id = sample.get("entity_id")
                if entity_id and entity_id in normalized_map:
                    db_entity = normalized_map[entity_id]
                    # Add normalized schema data
                    sample["__normalized__"] = {
                        "name": db_entity.name,
                        "description": db_entity.description,
                        "content": db_entity.content,
                        "web_url": db_entity.web_url,
                        "source_type": db_entity.source_type,
                        "entity_type": db_entity.entity_type,
                        "people": db_entity.people or [],
                        "tags": db_entity.tags or [],
                        "relations": db_entity.relations or [],
                        "status": db_entity.status,
                        "priority": db_entity.priority,
                        "custom_fields": db_entity.custom_fields or [],
                        "entity_created_at": db_entity.entity_created_at.isoformat() if db_entity.entity_created_at else None,
                        "entity_updated_at": db_entity.entity_updated_at.isoformat() if db_entity.entity_updated_at else None,
                        "due_at": db_entity.due_at.isoformat() if db_entity.due_at else None,
                        "completed_at": db_entity.completed_at.isoformat() if db_entity.completed_at else None,
                        "properties": db_entity.properties or {},
                        "breadcrumb_ids": db_entity.breadcrumb_ids or [],
                        "breadcrumb_names": db_entity.breadcrumb_names or [],
                    }

        ctx.logger.info(
            f"Retrieved {len(samples)} sample entities for sync {sync_id} "
            f"(type: {entity_type or 'all'}, normalized: {include_normalized})"
        )

        return samples

    except StorageNotFoundError:
        ctx.logger.warning(f"No ARF storage found for sync {sync_id}")
        # Return empty list instead of error - sync might not have ARF data yet
        return []
    except Exception as e:
        ctx.logger.error(f"Failed to retrieve sample entities: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve sample entities: {str(e)}"
        )


# -------------------------------------------------------------------------
# Normalized Entity Data Endpoints
# -------------------------------------------------------------------------


@router.get(
    "/normalized/by-sync/{sync_id}",
    response_model=List[EntityWithNormalized],
)
async def get_normalized_entities_by_sync(
    sync_id: UUID,
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(50, ge=1, le=500, description="Maximum records to return"),
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
) -> List[EntityWithNormalized]:
    """Get all normalized entities for a specific sync.

    Returns entities with their full normalized schema data including
    people, tags, relations, status, priority, and custom fields.

    Args:
        sync_id: The sync ID to fetch entities from
        entity_type: Optional filter by entity type
        skip: Pagination offset
        limit: Maximum entities to return
        db: Database session
        ctx: Current authenticated user

    Returns:
        List of entities with normalized data

    Raises:
        HTTPException: If sync not found or user doesn't have access
    """
    # Verify access to sync
    sync = await crud.sync.get(db, id=sync_id, ctx=ctx)
    if not sync:
        raise HTTPException(status_code=404, detail="Sync not found")

    # Get entities for this sync
    from sqlalchemy import select

    from contextd.models.entity import Entity

    stmt = select(Entity).where(Entity.sync_id == sync_id)

    if entity_type:
        stmt = stmt.where(Entity.entity_type == entity_type)

    stmt = stmt.offset(skip).limit(limit)

    result = await db.execute(stmt)
    entities = list(result.scalars().all())

    # Convert to response with normalized data
    response = []
    for entity in entities:
        entity_schema = schemas.Entity.model_validate(entity)
        entity_with_normalized = EntityWithNormalized.from_entity(entity_schema)
        response.append(entity_with_normalized)

    ctx.logger.info(
        f"Retrieved {len(response)} normalized entities for sync {sync_id}"
    )

    return response


@router.get(
    "/normalized/{entity_id}",
    response_model=NormalizedEntityData,
)
async def get_normalized_entity_by_id(
    entity_id: str,
    sync_id: UUID = Query(..., description="Sync ID for the entity"),
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
) -> NormalizedEntityData:
    """Get normalized data for a specific entity.

    Returns the full normalized schema data for a single entity,
    including people, tags, relations, status, and priority.

    Args:
        entity_id: The entity ID to fetch
        sync_id: The sync ID the entity belongs to
        db: Database session
        ctx: Current authenticated user

    Returns:
        Normalized entity data

    Raises:
        HTTPException: If entity not found or user doesn't have access
    """
    # Verify access to sync
    sync = await crud.sync.get(db, id=sync_id, ctx=ctx)
    if not sync:
        raise HTTPException(status_code=404, detail="Sync not found")

    # Get entity
    from sqlalchemy import select

    from contextd.models.entity import Entity

    stmt = select(Entity).where(
        Entity.sync_id == sync_id,
        Entity.entity_id == entity_id,
    )

    result = await db.execute(stmt)
    entity = result.scalar_one_or_none()

    if not entity:
        raise HTTPException(
            status_code=404,
            detail=f"Entity {entity_id} not found in sync {sync_id}",
        )

    # Convert to response schema
    entity_schema = schemas.Entity.model_validate(entity)

    return entity_schema.to_normalized_entity_data()


@router.get(
    "/normalized/by-sync-job/{sync_job_id}",
    response_model=List[EntityWithNormalized],
)
async def get_normalized_entities_by_sync_job(
    sync_job_id: UUID,
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(50, ge=1, le=500, description="Maximum records to return"),
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
) -> List[EntityWithNormalized]:
    """Get all normalized entities for a specific sync job.

    Returns entities processed in a specific sync job run with their
    full normalized schema data.

    Args:
        sync_job_id: The sync job ID to fetch entities from
        entity_type: Optional filter by entity type
        skip: Pagination offset
        limit: Maximum entities to return
        db: Database session
        ctx: Current authenticated user

    Returns:
        List of entities with normalized data

    Raises:
        HTTPException: If sync job not found or user doesn't have access
    """
    # Verify access to sync job
    sync_job = await crud.sync_job.get(db, id=sync_job_id, ctx=ctx)
    if not sync_job:
        raise HTTPException(status_code=404, detail="Sync job not found")

    # Get entities for this sync job
    from sqlalchemy import select

    from contextd.models.entity import Entity

    stmt = select(Entity).where(Entity.sync_job_id == sync_job_id)

    if entity_type:
        stmt = stmt.where(Entity.entity_type == entity_type)

    stmt = stmt.offset(skip).limit(limit)

    result = await db.execute(stmt)
    entities = list(result.scalars().all())

    # Convert to response with normalized data
    response = []
    for entity in entities:
        entity_schema = schemas.Entity.model_validate(entity)
        entity_with_normalized = EntityWithNormalized.from_entity(entity_schema)
        response.append(entity_with_normalized)

    ctx.logger.info(
        f"Retrieved {len(response)} normalized entities for sync job {sync_job_id}"
    )

    return response
