"""Collection service."""

from typing import Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud, schemas
from contextd.api.context import ApiContext
from contextd.core.config import settings
from contextd.core.exceptions import NotFoundException
from contextd.db.unit_of_work import UnitOfWork


def _default_embedding_profile() -> tuple[int, str]:
    """Return the collection embedding profile used by LLM-assisted graph features."""
    if settings.OPENAI_API_KEY:
        return (3072, "text-embedding-3-large")
    return (384, "sentence-transformers/all-MiniLM-L6-v2")


class CollectionService:
    """Service for managing collections.

    Manages the lifecycle of collections across the SQL datamodel.
    """

    async def create(
        self,
        db: AsyncSession,
        collection_in: schemas.CollectionCreate,
        ctx: ApiContext,
        uow: Optional[UnitOfWork] = None,
    ) -> schemas.Collection:
        """Create a new collection."""
        if uow is None:
            # Unit of work is not provided, so we create a new one
            async with UnitOfWork(db) as uow:
                collection = await self._create(db, collection_in=collection_in, ctx=ctx, uow=uow)
        else:
            # Unit of work is provided, so we just create the collection
            collection = await self._create(db, collection_in=collection_in, ctx=ctx, uow=uow)

        return collection

    async def _create(
        self,
        db: AsyncSession,
        collection_in: schemas.CollectionCreate,
        ctx: ApiContext,
        uow: UnitOfWork,
    ) -> schemas.Collection:
        """Create a new collection."""
        # Check if the collection already exists
        try:
            existing_collection = await crud.collection.get_by_readable_id(
                db, readable_id=collection_in.readable_id, ctx=ctx
            )
        except NotFoundException:
            existing_collection = None

        if existing_collection:
            raise HTTPException(
                status_code=400, detail="Collection with this readable_id already exists"
            )

        vector_size, embedding_model_name = _default_embedding_profile()

        # Persist the embedding profile for LLM-assisted graph features.
        collection_data = collection_in.model_dump()
        collection_data["vector_size"] = vector_size
        collection_data["embedding_model_name"] = embedding_model_name

        collection = await crud.collection.create(db, obj_in=collection_data, ctx=ctx, uow=uow)
        await uow.session.flush()

        ctx.logger.info(
            f"Created collection {collection.readable_id} with Neo4j fulltext search defaults"
        )

        return schemas.Collection.model_validate(collection, from_attributes=True)


# Singleton instance
collection_service = CollectionService()
