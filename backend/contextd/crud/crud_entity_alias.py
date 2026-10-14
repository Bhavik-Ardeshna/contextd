"""CRUD for semantic merge alias mappings and canonical profiles (sync-friendly, no ApiContext)."""

from typing import List, Optional, Sequence
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from contextd.core.datetime_utils import utc_now_naive
from contextd.models.entity_alias_mapping import EntityAliasMapping, EntityCanonicalProfile


class CRUDEntityAlias:
    """Database access for entity alias and canonical profile tables."""

    async def get_canonical_by_alias_any_type(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        alias_key: str,
    ) -> Optional[str]:
        stmt = select(EntityAliasMapping.canonical_node_id).where(
            EntityAliasMapping.organization_id == organization_id,
            EntityAliasMapping.alias_key == alias_key,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_canonical_by_alias(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        entity_type: str,
        alias_key: str,
    ) -> Optional[str]:
        stmt = select(EntityAliasMapping.canonical_node_id).where(
            EntityAliasMapping.organization_id == organization_id,
            EntityAliasMapping.entity_type == entity_type,
            EntityAliasMapping.alias_key == alias_key,
        )
        result = await db.execute(stmt)
        row = result.scalar_one_or_none()
        return row

    async def upsert_alias_mapping(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        entity_type: str,
        alias_key: str,
        canonical_node_id: str,
        confidence: Optional[float] = None,
        match_method: Optional[str] = None,
        last_seen_sync_id: Optional[UUID] = None,
    ) -> EntityAliasMapping:
        """Insert or update alias mapping (atomic upsert; avoids unique races on concurrent syncs)."""
        now = utc_now_naive()
        ins = insert(EntityAliasMapping).values(
            id=uuid4(),
            organization_id=organization_id,
            entity_type=entity_type,
            alias_key=alias_key,
            canonical_node_id=canonical_node_id,
            confidence=confidence,
            match_method=match_method,
            last_seen_sync_id=last_seen_sync_id,
            created_at=now,
            modified_at=now,
        )
        stmt = ins.on_conflict_do_update(
            index_elements=["organization_id", "entity_type", "alias_key"],
            set_={
                "canonical_node_id": ins.excluded.canonical_node_id,
                "confidence": ins.excluded.confidence,
                "match_method": ins.excluded.match_method,
                "last_seen_sync_id": ins.excluded.last_seen_sync_id,
                "modified_at": ins.excluded.modified_at,
            },
        )
        await db.execute(stmt)
        result = await db.execute(
            select(EntityAliasMapping).where(
                EntityAliasMapping.organization_id == organization_id,
                EntityAliasMapping.entity_type == entity_type,
                EntityAliasMapping.alias_key == alias_key,
            )
        )
        row = result.scalar_one()
        return row

    async def list_profiles_for_entity_type(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        entity_type: str,
        limit: int = 500,
    ) -> Sequence[EntityCanonicalProfile]:
        stmt = (
            select(EntityCanonicalProfile)
            .where(
                EntityCanonicalProfile.organization_id == organization_id,
                EntityCanonicalProfile.entity_type == entity_type,
            )
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def list_profiles_any_type(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        limit: int = 500,
    ) -> Sequence[EntityCanonicalProfile]:
        stmt = (
            select(EntityCanonicalProfile)
            .where(EntityCanonicalProfile.organization_id == organization_id)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_profile(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        entity_type: str,
        canonical_node_id: str,
    ) -> Optional[EntityCanonicalProfile]:
        stmt = select(EntityCanonicalProfile).where(
            EntityCanonicalProfile.organization_id == organization_id,
            EntityCanonicalProfile.entity_type == entity_type,
            EntityCanonicalProfile.canonical_node_id == canonical_node_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_profile_any_type(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        canonical_node_id: str,
    ) -> Optional[EntityCanonicalProfile]:
        stmt = select(EntityCanonicalProfile).where(
            EntityCanonicalProfile.organization_id == organization_id,
            EntityCanonicalProfile.canonical_node_id == canonical_node_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_canonical_profile(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        entity_type: str,
        canonical_node_id: str,
        merged_properties_json: Optional[dict] = None,
        merged_summary: Optional[str] = None,
        embedding_text_hash: Optional[str] = None,
        embedding_json: Optional[List[float]] = None,
    ) -> EntityCanonicalProfile:
        now = utc_now_naive()
        existing = await self.get_profile(
            db,
            organization_id=organization_id,
            entity_type=entity_type,
            canonical_node_id=canonical_node_id,
        )
        # Merge semantics: keep existing JSON/summary/hash/embed if caller omits (None).
        mpj = (
            merged_properties_json
            if merged_properties_json is not None
            else (existing.merged_properties_json if existing else None)
        )
        ms = (
            merged_summary
            if merged_summary is not None
            else (existing.merged_summary if existing else None)
        )
        eth = (
            embedding_text_hash
            if embedding_text_hash is not None
            else (existing.embedding_text_hash if existing else None)
        )
        ej = (
            embedding_json if embedding_json is not None else (existing.embedding_json if existing else None)
        )

        ins = insert(EntityCanonicalProfile).values(
            id=uuid4(),
            organization_id=organization_id,
            entity_type=entity_type,
            canonical_node_id=canonical_node_id,
            merged_properties_json=mpj,
            merged_summary=ms,
            embedding_text_hash=eth,
            embedding_json=ej,
            created_at=now,
            modified_at=now,
        )
        stmt = ins.on_conflict_do_update(
            index_elements=["organization_id", "entity_type", "canonical_node_id"],
            set_={
                "merged_properties_json": ins.excluded.merged_properties_json,
                "merged_summary": ins.excluded.merged_summary,
                "embedding_text_hash": ins.excluded.embedding_text_hash,
                "embedding_json": ins.excluded.embedding_json,
                "modified_at": ins.excluded.modified_at,
            },
        )
        await db.execute(stmt)
        out = await self.get_profile(
            db,
            organization_id=organization_id,
            entity_type=entity_type,
            canonical_node_id=canonical_node_id,
        )
        assert out is not None
        return out


entity_alias = CRUDEntityAlias()
