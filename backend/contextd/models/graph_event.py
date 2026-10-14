"""Graph event database model."""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from contextd.models._base import Base


class GraphEvent(Base):
    """Graph event generated from entity field changes.

    Stores events that represent graph operations (nodes, edges, metadata)
    detected during sync state comparison.

    Two-Phase Commit Architecture:
    - Phase 1: Events are inserted with commit_status='pending' (parallel batches)
    - Phase 2: Events are committed to Neo4j atomically, then marked 'committed'

    Commit Status Values:
    - 'pending': Event created, waiting for Phase 2 commit
    - 'committed': Successfully written to Neo4j
    - 'failed': Phase 2 failed, error recorded in commit_error
    - 'skipped': Duplicate event, not written to Neo4j
    """

    __tablename__ = "graph_events"

    # Primary key
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    modified_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Link to entity
    entity_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    entity_definition_id: Mapped[UUID] = mapped_column(nullable=False, index=True)

    # Link to sync
    sync_id: Mapped[UUID] = mapped_column(
        ForeignKey("sync.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sync_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("sync_job.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organization.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Event details
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # NODE_CREATE, EDGE_UPDATE, etc.
    field_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Node ID for deduplication (extracted from event payload for NODE events)
    node_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)

    # Event payload (JSONB for flexibility)
    event_data: Mapped[dict] = mapped_column(JSON, nullable=False)

    # State tracking (legacy)
    state_version: Mapped[str] = mapped_column(
        String(20), default="1.0", nullable=False
    )
    processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Two-phase commit status tracking
    # Status values: 'pending', 'committed', 'failed', 'skipped'
    commit_status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True
    )
    commit_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    committed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
