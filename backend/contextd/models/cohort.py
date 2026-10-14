"""Saved cohort (structured single node_type + stored Cypher)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional
from uuid import UUID

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from contextd.models._base import OrganizationBase, UserMixin

if TYPE_CHECKING:
    from contextd.models.collection import Collection


class Cohort(OrganizationBase, UserMixin):
    """A reusable cohort definition scoped to a collection."""

    __tablename__ = "cohort"

    collection_id: Mapped[UUID] = mapped_column(
        ForeignKey("collection.id", ondelete="CASCADE", name="fk_cohort_collection_id"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    target_node_type: Mapped[str] = mapped_column(String(512), nullable=False)
    cypher_text: Mapped[str] = mapped_column(Text, nullable=False)
    display_property_keys: Mapped[List[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="[]",
    )
    identifier_property_keys: Mapped[List[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="[]",
    )
    cohort_mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default="list",
    )
    scoring_spec: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    distribution_probe_snapshot: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    cutoff_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cutoff_iterations_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    score_breakdown_keys: Mapped[Optional[List[str]]] = mapped_column(JSONB, nullable=True)
    cypher_params: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    collection: Mapped["Collection"] = relationship(
        "Collection",
        lazy="noload",
    )
