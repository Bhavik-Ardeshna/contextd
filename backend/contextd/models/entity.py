"""Entity model."""

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from contextd.models._base import OrganizationBase

if TYPE_CHECKING:
    from contextd.models.entity_definition import EntityDefinition
    from contextd.models.sync import Sync
    from contextd.models.sync_job import SyncJob


class Entity(OrganizationBase):
    """Entity model with normalized schema fields.

    Stores both the entity hash (for change detection) and the full
    normalized schema fields for direct querying and display.
    """

    __tablename__ = "entity"

    # Override organization_id to disable index (table too large, better indexes exist)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False,
        index=False,  # Disabled: billions of rows, not selective, better indexes on sync_id
    )

    sync_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("sync_job.id", ondelete="CASCADE", name="fk_entity_sync_job_id"), nullable=False
    )
    sync_id: Mapped[UUID] = mapped_column(
        ForeignKey("sync.id", ondelete="CASCADE", name="fk_entity_sync_id"), nullable=False
    )
    entity_id: Mapped[str] = mapped_column(String, nullable=False)
    entity_definition_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(
            "entity_definition.id", ondelete="CASCADE", name="fk_entity_entity_definition_id"
        ),
        nullable=True,
        comment="Entity definition this entity belongs to",
    )
    hash: Mapped[str] = mapped_column(String, nullable=False)

    # -------------------------------------------------------------------------
    # Normalized Schema Fields
    # -------------------------------------------------------------------------

    # Core content fields
    name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    web_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_type: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, comment="Source connector short_name"
    )
    entity_type: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, comment="Original entity class name"
    )

    # Normalized references (JSONB for complex nested data)
    people: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(
        JSONB, nullable=True, server_default="[]",
        comment="List of PersonRef (assignees, owners, members, etc.)"
    )
    tags: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(
        JSONB, nullable=True, server_default="[]",
        comment="List of TagRef (labels, categories)"
    )
    relations: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(
        JSONB, nullable=True, server_default="[]",
        comment="List of RelationRef (parent/child/dependencies)"
    )
    status: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=True, comment="StatusRef for current status"
    )
    priority: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=True, comment="PriorityRef for priority level"
    )
    custom_fields: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(
        JSONB, nullable=True, server_default="[]",
        comment="List of CustomFieldRef"
    )

    # Timestamps from source system
    entity_created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, comment="When entity was created in source system"
    )
    entity_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, comment="When entity was last modified in source system"
    )
    due_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, comment="Due date/time if applicable"
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, comment="Completion date/time if applicable"
    )

    # Flexible extension for connector-specific fields
    properties: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=True, server_default="{}",
        comment="Connector-specific fields that don't fit canonical model"
    )

    # Breadcrumbs for hierarchy context
    breadcrumb_ids: Mapped[Optional[List[str]]] = mapped_column(
        JSONB, nullable=True, server_default="[]",
        comment="List of parent entity IDs"
    )
    breadcrumb_names: Mapped[Optional[List[str]]] = mapped_column(
        JSONB, nullable=True, server_default="[]",
        comment="List of parent entity names"
    )

    # Add back references
    sync_job: Mapped["SyncJob"] = relationship(
        "SyncJob",
        back_populates="entities",
        lazy="noload",
    )

    sync: Mapped["Sync"] = relationship(
        "Sync",
        back_populates="entities",
        lazy="noload",
    )

    entity_definition: Mapped[Optional["EntityDefinition"]] = relationship(
        "EntityDefinition",
        lazy="noload",
    )

    __table_args__ = (
        UniqueConstraint(
            "sync_id",
            "entity_id",
            "entity_definition_id",
            name="uq_sync_id_entity_id_entity_definition_id",
        ),
        # Performance indexes based on common query patterns
        Index("idx_entity_sync_id", "sync_id"),
        Index("idx_entity_sync_job_id", "sync_job_id"),
        Index("idx_entity_entity_id", "entity_id"),
        Index("idx_entity_entity_definition_id", "entity_definition_id"),
        # Composite index for the most common lookup pattern
        Index("idx_entity_entity_id_sync_id", "entity_id", "sync_id"),
        # Composite index for entity counts aggregation
        Index("idx_entity_sync_id_entity_def_id", "sync_id", "entity_definition_id"),
        # Indexes for normalized schema columns
        Index("ix_entity_source_type", "source_type"),
        Index("ix_entity_entity_type", "entity_type"),
        # GIN indexes for JSONB columns (defined in migration)
        Index("ix_entity_people_gin", "people", postgresql_using="gin"),
        Index("ix_entity_tags_gin", "tags", postgresql_using="gin"),
        Index("ix_entity_relations_gin", "relations", postgresql_using="gin"),
    )
