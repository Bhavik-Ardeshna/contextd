"""Persistent alias to canonical node ID mappings for semantic merge."""

from typing import Optional
from uuid import UUID

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from contextd.models._base import OrganizationBase


class EntityAliasMapping(OrganizationBase):
    """Maps normalized alias keys (name/email) to a canonical graph node id."""

    __tablename__ = "entity_alias_mapping"

    entity_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    alias_key: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    canonical_node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    match_method: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_seen_sync_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sync.id", ondelete="SET NULL"),
        nullable=True,
    )


class EntityCanonicalProfile(OrganizationBase):
    """Merged properties and optional embedding vector for a canonical node."""

    __tablename__ = "entity_canonical_profile"

    entity_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    canonical_node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    merged_properties_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    merged_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    embedding_text_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    embedding_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
