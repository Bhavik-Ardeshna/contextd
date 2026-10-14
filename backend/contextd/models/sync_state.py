"""Sync state model for storing comprehensive entity state snapshots."""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from contextd.models._base import OrganizationBase, UserMixin

if TYPE_CHECKING:
    from contextd.models.sync import Sync
    from contextd.models.sync_job import SyncJob


class SyncState(OrganizationBase, UserMixin):
    """Sync state model for storing comprehensive entity state snapshots.

    Each sync job creates a state snapshot containing:
    - Entity hashes for all synced entities
    - Field-level hashes for granular change detection
    - Entity relationships and breadcrumbs
    - Sync statistics and metadata

    This enables intelligent state-based comparison in Phase 2.
    """

    __tablename__ = "sync_state"

    # Foreign keys
    sync_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("sync_job.id", ondelete="CASCADE", name="fk_sync_state_sync_job_id"),
        nullable=False,
        comment="The sync job that created this state snapshot",
    )

    sync_id: Mapped[UUID] = mapped_column(
        ForeignKey("sync.id", ondelete="CASCADE", name="fk_sync_state_sync_id"),
        nullable=False,
        comment="The sync configuration this state belongs to",
    )

    # State snapshot (JSONB for flexibility and future evolution)
    state_data: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="Comprehensive state snapshot containing entity hashes, field hashes, relationships",
    )

    # Metadata for quick filtering and statistics
    entity_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Total number of entities in this state snapshot",
    )

    state_version: Mapped[str] = mapped_column(
        String(20),
        default="1.0",
        nullable=False,
        comment="State schema version for future evolution",
    )

    # Relationships
    sync_job: Mapped["SyncJob"] = relationship(
        "SyncJob",
        back_populates="sync_state",
        lazy="noload",
    )

    sync: Mapped["Sync"] = relationship(
        "Sync",
        back_populates="sync_states",
        lazy="noload",
    )

    __table_args__ = (
        # Index for finding states by sync_id (most common query pattern)
        Index("idx_sync_state_sync_id", "sync_id"),
        # Index for finding state by sync_job_id (exact lookup)
        Index("idx_sync_state_sync_job_id", "sync_job_id"),
        # Composite index for latest state queries (sync_id + created_at DESC)
        Index("idx_sync_state_sync_id_created_at", "sync_id", "created_at"),
    )
