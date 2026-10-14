"""Entity schema with normalized data fields."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from contextd.platform.entities._normalized import (
    CustomFieldRef,
    NormalizedEntity,
    PersonRef,
    PriorityRef,
    RelationRef,
    StatusRef,
    TagRef,
)


class NormalizedEntityData(BaseModel):
    """Normalized entity data for storage and display.

    This schema represents the normalized portion of an entity
    that can be stored and retrieved from the database.
    """

    # Core content
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    web_url: Optional[str] = None
    source_type: Optional[str] = None
    entity_type: Optional[str] = None

    # Normalized references
    people: List[PersonRef] = Field(default_factory=list)
    tags: List[TagRef] = Field(default_factory=list)
    relations: List[RelationRef] = Field(default_factory=list)
    status: Optional[StatusRef] = None
    priority: Optional[PriorityRef] = None
    custom_fields: List[CustomFieldRef] = Field(default_factory=list)

    # Timestamps
    entity_created_at: Optional[datetime] = None
    entity_updated_at: Optional[datetime] = None
    due_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Extension
    properties: Dict[str, Any] = Field(default_factory=dict)

    # Breadcrumbs
    breadcrumb_ids: List[str] = Field(default_factory=list)
    breadcrumb_names: List[str] = Field(default_factory=list)

    model_config = ConfigDict(
        from_attributes=True,
    )

    @classmethod
    def from_normalized_entity(cls, normalized: NormalizedEntity) -> "NormalizedEntityData":
        """Create from a NormalizedEntity instance.

        Args:
            normalized: The NormalizedEntity to convert

        Returns:
            NormalizedEntityData instance
        """
        return cls(
            name=normalized.name,
            description=normalized.description,
            content=normalized.content,
            web_url=normalized.web_url,
            source_type=normalized.source_type,
            entity_type=normalized.entity_type,
            people=normalized.people,
            tags=normalized.tags,
            relations=normalized.relations,
            status=normalized.status,
            priority=normalized.priority,
            custom_fields=normalized.custom_fields,
            entity_created_at=normalized.created_at,
            entity_updated_at=normalized.updated_at,
            due_at=normalized.due_at,
            completed_at=normalized.completed_at,
            properties=normalized.properties,
            breadcrumb_ids=normalized.breadcrumb_ids,
            breadcrumb_names=normalized.breadcrumb_names,
        )


class EntityBase(BaseModel):
    """Base schema for Entity."""

    sync_job_id: UUID
    sync_id: UUID
    entity_id: str
    entity_definition_id: Optional[UUID] = None
    hash: str

    model_config = ConfigDict(
        from_attributes=True,
    )


class EntityCreate(EntityBase):
    """Schema for creating an Entity object with normalized data."""

    # Normalized schema fields
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    web_url: Optional[str] = None
    source_type: Optional[str] = None
    entity_type: Optional[str] = None

    # Normalized references (stored as JSONB)
    people: Optional[List[Dict[str, Any]]] = None
    tags: Optional[List[Dict[str, Any]]] = None
    relations: Optional[List[Dict[str, Any]]] = None
    status: Optional[Dict[str, Any]] = None
    priority: Optional[Dict[str, Any]] = None
    custom_fields: Optional[List[Dict[str, Any]]] = None

    # Timestamps
    entity_created_at: Optional[datetime] = None
    entity_updated_at: Optional[datetime] = None
    due_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Extension
    properties: Optional[Dict[str, Any]] = None

    # Breadcrumbs
    breadcrumb_ids: Optional[List[str]] = None
    breadcrumb_names: Optional[List[str]] = None

    @classmethod
    def from_normalized_entity(
        cls,
        normalized: NormalizedEntity,
        sync_job_id: UUID,
        sync_id: UUID,
        entity_definition_id: Optional[UUID],
        hash_value: str,
    ) -> "EntityCreate":
        """Create EntityCreate from a NormalizedEntity.

        Args:
            normalized: The NormalizedEntity to convert
            sync_job_id: The sync job UUID
            sync_id: The sync UUID
            entity_definition_id: The entity definition UUID
            hash_value: The entity hash

        Returns:
            EntityCreate instance with all normalized data
        """
        return cls(
            sync_job_id=sync_job_id,
            sync_id=sync_id,
            entity_id=normalized.entity_id,
            entity_definition_id=entity_definition_id,
            hash=hash_value,
            name=normalized.name,
            description=normalized.description,
            content=normalized.content,
            web_url=normalized.web_url,
            source_type=normalized.source_type,
            entity_type=normalized.entity_type,
            people=[p.model_dump() for p in normalized.people] if normalized.people else [],
            tags=[t.model_dump() for t in normalized.tags] if normalized.tags else [],
            relations=[r.model_dump() for r in normalized.relations]
            if normalized.relations
            else [],
            status=normalized.status.model_dump() if normalized.status else None,
            priority=normalized.priority.model_dump() if normalized.priority else None,
            custom_fields=[cf.model_dump() for cf in normalized.custom_fields]
            if normalized.custom_fields
            else [],
            entity_created_at=normalized.created_at,
            entity_updated_at=normalized.updated_at,
            due_at=normalized.due_at,
            completed_at=normalized.completed_at,
            properties=normalized.properties,
            breadcrumb_ids=normalized.breadcrumb_ids,
            breadcrumb_names=normalized.breadcrumb_names,
        )


class EntityUpdate(BaseModel):
    """Schema for updating an Entity object."""

    sync_job_id: Optional[UUID] = None
    sync_id: Optional[UUID] = None
    entity_id: Optional[str] = None
    entity_definition_id: Optional[UUID] = None
    hash: Optional[str] = None

    # Normalized schema fields
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    web_url: Optional[str] = None
    source_type: Optional[str] = None
    entity_type: Optional[str] = None

    # Normalized references
    people: Optional[List[Dict[str, Any]]] = None
    tags: Optional[List[Dict[str, Any]]] = None
    relations: Optional[List[Dict[str, Any]]] = None
    status: Optional[Dict[str, Any]] = None
    priority: Optional[Dict[str, Any]] = None
    custom_fields: Optional[List[Dict[str, Any]]] = None

    # Timestamps
    entity_created_at: Optional[datetime] = None
    entity_updated_at: Optional[datetime] = None
    due_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Extension
    properties: Optional[Dict[str, Any]] = None

    # Breadcrumbs
    breadcrumb_ids: Optional[List[str]] = None
    breadcrumb_names: Optional[List[str]] = None


class EntityInDBBase(EntityBase):
    """Base schema for Entity stored in DB with normalized data."""

    id: UUID
    organization_id: UUID
    created_at: datetime
    modified_at: datetime

    # Normalized schema fields
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    web_url: Optional[str] = None
    source_type: Optional[str] = None
    entity_type: Optional[str] = None

    # Normalized references
    people: Optional[List[Dict[str, Any]]] = None
    tags: Optional[List[Dict[str, Any]]] = None
    relations: Optional[List[Dict[str, Any]]] = None
    status: Optional[Dict[str, Any]] = None
    priority: Optional[Dict[str, Any]] = None
    custom_fields: Optional[List[Dict[str, Any]]] = None

    # Timestamps
    entity_created_at: Optional[datetime] = None
    entity_updated_at: Optional[datetime] = None
    due_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Extension
    properties: Optional[Dict[str, Any]] = None

    # Breadcrumbs
    breadcrumb_ids: Optional[List[str]] = None
    breadcrumb_names: Optional[List[str]] = None

    model_config = ConfigDict(
        from_attributes=True,
    )

    def to_normalized_entity_data(self) -> NormalizedEntityData:
        """Convert to NormalizedEntityData for display."""
        return NormalizedEntityData(
            name=self.name,
            description=self.description,
            content=self.content,
            web_url=self.web_url,
            source_type=self.source_type,
            entity_type=self.entity_type,
            people=[PersonRef(**p) for p in (self.people or [])],
            tags=[TagRef(**t) for t in (self.tags or [])],
            relations=[RelationRef(**r) for r in (self.relations or [])],
            status=StatusRef(**self.status) if self.status else None,
            priority=PriorityRef(**self.priority) if self.priority else None,
            custom_fields=[CustomFieldRef(**cf) for cf in (self.custom_fields or [])],
            entity_created_at=self.entity_created_at,
            entity_updated_at=self.entity_updated_at,
            due_at=self.due_at,
            completed_at=self.completed_at,
            properties=self.properties or {},
            breadcrumb_ids=self.breadcrumb_ids or [],
            breadcrumb_names=self.breadcrumb_names or [],
        )


class Entity(EntityInDBBase):
    """Schema for Entity with full normalized data."""

    pass


class EntityWithNormalized(Entity):
    """Entity with typed normalized data for API responses."""

    normalized: Optional[NormalizedEntityData] = None

    @classmethod
    def from_entity(cls, entity: Entity) -> "EntityWithNormalized":
        """Create from an Entity with typed normalized data."""
        data = entity.model_dump()
        data["normalized"] = entity.to_normalized_entity_data()
        return cls(**data)


class EntityCount(BaseModel):
    """Schema for entity count."""

    count: int
