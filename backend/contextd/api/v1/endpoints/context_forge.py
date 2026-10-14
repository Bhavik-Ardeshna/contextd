"""Context Forge workbench endpoints."""

from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import schemas
from contextd.api import deps
from contextd.api.context import ApiContext
from contextd.api.router import TrailingSlashRouter
from contextd.core.context_forge_service import context_forge_service
from contextd.db.session import get_db

router = TrailingSlashRouter()


@router.get("/databases/{readable_id}", response_model=schemas.ContextForgeDatabaseSummary)
async def get_database_forge_summary(
    *,
    db: AsyncSession = Depends(get_db),
    readable_id: str,
    ctx: ApiContext = Depends(deps.get_context),
) -> schemas.ContextForgeDatabaseSummary:
    """Return a database-scoped Context Forge summary."""
    return await context_forge_service.get_database_summary(
        db,
        readable_id=readable_id,
        ctx=ctx,
    )


@router.post(
    "/sources/{source_connection_id}/regenerate",
    response_model=schemas.ContextForgeMappingArtifact,
)
async def regenerate_source_forge_mapping(
    *,
    db: AsyncSession = Depends(get_db),
    source_connection_id: UUID,
    ctx: ApiContext = Depends(deps.get_context),
) -> schemas.ContextForgeMappingArtifact:
    """Create a new editable Forge mapping version from latest source shape."""
    artifact = await context_forge_service.regenerate_source_mapping(
        db,
        source_connection_id=source_connection_id,
        ctx=ctx,
    )
    await db.commit()
    return artifact


@router.patch(
    "/mappings/{mapping_id}",
    response_model=schemas.ContextForgeMappingArtifact,
)
async def update_forge_mapping(
    *,
    db: AsyncSession = Depends(get_db),
    mapping_id: UUID,
    mapping_in: schemas.ContextForgeMappingUpdate,
    ctx: ApiContext = Depends(deps.get_context),
) -> schemas.ContextForgeMappingArtifact:
    """Persist edits to a Context Forge graph-schema mapping."""
    artifact = await context_forge_service.update_mapping(
        db,
        mapping_id=mapping_id,
        update_in=mapping_in,
        ctx=ctx,
    )
    await db.commit()
    return artifact


@router.post(
    "/mappings/{mapping_id}/apply",
    response_model=schemas.ContextForgeMappingArtifact,
)
async def apply_forge_mapping(
    *,
    db: AsyncSession = Depends(get_db),
    mapping_id: UUID,
    ctx: ApiContext = Depends(deps.get_context),
) -> schemas.ContextForgeMappingArtifact:
    """Promote a reviewed Forge mapping to the active graph schema."""
    artifact = await context_forge_service.apply_mapping(
        db,
        mapping_id=mapping_id,
        ctx=ctx,
    )
    await db.commit()
    return artifact
