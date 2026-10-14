"""Persisted Context Forge graph-schema mapping artifacts."""

from typing import Optional
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column

from contextd.models._base import OrganizationBase, UserMixin


class ContextForgeMappingArtifact(OrganizationBase, UserMixin):
    """Versioned graph-schema mapping generated and edited by Context Forge."""

    __tablename__ = "context_forge_mapping"

    source_connection_id: Mapped[Optional[UUID]] = mapped_column(
        SAUUID, ForeignKey("source_connection.id", ondelete="CASCADE"), nullable=True, index=True
    )
    setup_draft_id: Mapped[Optional[UUID]] = mapped_column(
        SAUUID,
        ForeignKey("source_connection_setup_draft.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    target_collection_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("collection.readable_id", ondelete="SET NULL"), nullable=True, index=True
    )

    provider_short_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    source_name: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft", index=True)
    generated_by: Mapped[str] = mapped_column(String, nullable=False, default="setup_discovery")

    mapping_schema: Mapped[dict] = mapped_column(JSON, nullable=False)
    graph_preview: Mapped[dict] = mapped_column(JSON, nullable=False)
    schema_fingerprint: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    drift_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    applied_at: Mapped[Optional[DateTime]] = mapped_column(DateTime, nullable=True)
