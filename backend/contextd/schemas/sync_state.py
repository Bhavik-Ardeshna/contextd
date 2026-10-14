"""Pydantic schemas for sync state objects.

Defines the structure of comprehensive state snapshots that capture:
- Entity hashes for all synced entities
- Field-level hashes for granular change detection
- Entity relationships and breadcrumbs
- Sync statistics and metadata
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EntityStateSnapshot(BaseModel):
    """State snapshot for a single entity.

    Contains all information needed to detect changes at entity and field level.
    """

    hash: str = Field(..., description="SHA256 hash of the complete entity content")
    entity_definition_id: UUID = Field(..., description="Entity definition this entity belongs to")
    created_at: Optional[str] = Field(None, description="Entity creation timestamp (ISO format)")
    modified_at: Optional[str] = Field(
        None, description="Entity last modification timestamp (ISO format)"
    )
    breadcrumbs: List[Dict[str, Any]] = Field(
        default_factory=list, description="Parent entity breadcrumbs for hierarchy tracking"
    )
    field_hashes: Dict[str, str] = Field(
        default_factory=dict,
        description="Individual hashes for each embeddable field (field_name -> hash)",
    )
    relationships: Dict[str, Any] = Field(
        default_factory=dict, description="Parent/child relationships and metadata"
    )

    model_config = ConfigDict(
        from_attributes=True,
    )


class EntityTypeState(BaseModel):
    """State for all entities of a given type.

    Groups entities by their entity_id for efficient lookup.
    """

    entities: Dict[str, EntityStateSnapshot] = Field(
        default_factory=dict, description="Mapping of entity_id to EntityStateSnapshot"
    )

    model_config = ConfigDict(
        from_attributes=True,
    )


class SyncMetadata(BaseModel):
    """Metadata about the sync job that created this state."""

    sync_job_id: str = Field(..., description="Sync job ID")
    sync_id: str = Field(..., description="Sync configuration ID")
    started_at: Optional[str] = Field(None, description="Sync start time (ISO format)")
    completed_at: Optional[str] = Field(None, description="Sync completion time (ISO format)")
    force_full_sync: bool = Field(False, description="Whether this was a forced full sync")
    cursor_had_data_at_start: bool = Field(
        False,
        description="Whether cursor state existed before this sync started",
    )
    snapshot_mode: str = Field(
        "full",
        description="How this state should be interpreted: full, incremental_merged, or incremental_delta",
    )
    snapshot_is_complete: bool = Field(
        True,
        description="Whether this state represents the full current entity snapshot",
    )
    merge_base_sync_state_id: Optional[str] = Field(
        None,
        description="Sync state row used as the merge base for an incremental snapshot",
    )

    model_config = ConfigDict(
        from_attributes=True,
    )


class SyncStatistics(BaseModel):
    """Statistics about the entities in this state snapshot."""

    total_entities: int = Field(0, description="Total number of entities in state")
    entities_by_type: Dict[str, int] = Field(
        default_factory=dict, description="Count of entities per entity type"
    )
    entities_inserted: int = Field(0, description="Number of entities inserted in this sync")
    entities_updated: int = Field(0, description="Number of entities updated in this sync")
    entities_deleted: int = Field(0, description="Number of entities deleted in this sync")
    entities_kept: int = Field(0, description="Number of entities kept unchanged in this sync")

    model_config = ConfigDict(
        from_attributes=True,
    )


class SyncStateData(BaseModel):
    """Complete sync state structure stored in JSONB.

    This is the comprehensive state snapshot that enables intelligent
    state-based comparison in Phase 2.
    """

    version: str = Field("1.0", description="State schema version for future evolution")
    sync_metadata: SyncMetadata = Field(..., description="Metadata about the sync job")
    entity_states: Dict[str, EntityTypeState] = Field(
        default_factory=dict,
        description="Entity states grouped by entity type (entity_type -> EntityTypeState)",
    )
    statistics: SyncStatistics = Field(
        default_factory=SyncStatistics, description="Statistics about this state snapshot"
    )

    model_config = ConfigDict(
        from_attributes=True,
    )


class SyncStateBase(BaseModel):
    """Base schema for SyncState."""

    sync_job_id: UUID
    sync_id: UUID
    state_data: Union[SyncStateData, Dict[str, Any]] = Field(
        ..., description="State data as Pydantic model or dict for JSONB storage"
    )
    entity_count: int = Field(0, description="Total entities in state (denormalized for queries)")
    state_version: str = Field("1.0", description="State schema version")

    model_config = ConfigDict(
        from_attributes=True,
    )


class SyncStateCreate(SyncStateBase):
    """Schema for creating a SyncState record."""

    pass


class SyncStateUpdate(BaseModel):
    """Schema for updating a SyncState record.

    Note: State objects are typically immutable after creation,
    but this schema is provided for completeness.
    """

    state_data: Optional[SyncStateData] = None
    entity_count: Optional[int] = None

    model_config = ConfigDict(
        from_attributes=True,
    )


class SyncState(SyncStateBase):
    """Complete SyncState schema with database fields."""

    id: UUID
    organization_id: UUID
    created_at: datetime
    modified_at: datetime
    created_by_email: Optional[str] = None
    modified_by_email: Optional[str] = None

    model_config = ConfigDict(
        from_attributes=True,
    )
