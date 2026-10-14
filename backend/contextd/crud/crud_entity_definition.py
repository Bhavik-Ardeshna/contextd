"""CRUD operations for entity definitions."""

from typing import List
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from contextd.core.exceptions import NotFoundException
from contextd.models.entity_definition import EntityDefinition
from contextd.schemas.entity_definition import EntityDefinitionCreate, EntityDefinitionUpdate

from ._base_public import CRUDPublic


class CRUDEntityDefinition(
    CRUDPublic[EntityDefinition, EntityDefinitionCreate, EntityDefinitionUpdate]
):
    """CRUD operations for Entity Definition."""

    async def get_multi_by_ids(
        self, db: AsyncSession, *, ids: List[UUID]
    ) -> List[EntityDefinition]:
        """Get multiple entity definitions by their IDs.

        Args:
            db (AsyncSession): The database session
            ids (List[UUID]): List of entity definition IDs to fetch

        Returns:
            List[EntityDefinition]: List of found entity definitions
        """
        result = await db.execute(select(self.model).where(self.model.id.in_(ids)))
        return list(result.unique().scalars().all())

    async def get_by_entity_class_name(
        self, db: AsyncSession, *, entity_class_name: str
    ) -> EntityDefinition:
        """Get an entity definition by its entity class name."""
        result = await db.execute(select(self.model).where(self.model.name == entity_class_name))
        db_obj = result.scalar_one_or_none()
        if not db_obj:
            raise NotFoundException(f"Entity definition with name {entity_class_name} not found")
        return db_obj

    async def get_multi_by_source_short_name(
        self, db: AsyncSession, *, source_short_name: str
    ) -> List[EntityDefinition]:
        """Get all entity definitions for a given source."""
        result = await db.execute(
            select(self.model).where(self.model.module_name == source_short_name)
        )
        entity_definitions = result.unique().scalars().all()
        return entity_definitions


entity_definition = CRUDEntityDefinition(EntityDefinition)
