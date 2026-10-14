"""Normalized entity schemas for canonical data model.

This module provides standardized schemas that all connector entities
are normalized to during pipeline processing. This ensures consistent
data structure across PostgreSQL storage and Neo4j graph indexing.

Key Design Principles:
- entity_id is universal: same ID in PostgreSQL and Graph nodes
- Nested data (assignees, tags) use standardized reference schemas
- Connector-specific fields go in the `properties` dict
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PersonRole(str, Enum):
    """Standard roles for person references."""

    ASSIGNEE = "assignee"
    OWNER = "owner"
    MEMBER = "member"
    FOLLOWER = "follower"
    CREATOR = "creator"
    EDITOR = "editor"
    AUTHOR = "author"
    REVIEWER = "reviewer"
    APPROVER = "approver"
    WATCHER = "watcher"
    MENTIONED = "mentioned"
    OTHER = "other"


class RelationType(str, Enum):
    """Standard relationship types between entities."""

    PARENT = "parent"
    CHILD = "child"
    DEPENDS_ON = "depends_on"
    BLOCKS = "blocks"
    RELATED_TO = "related_to"
    DUPLICATE_OF = "duplicate_of"
    PART_OF = "part_of"
    CONTAINS = "contains"
    REFERENCES = "references"
    ATTACHMENT_OF = "attachment_of"
    COMMENT_ON = "comment_on"
    OTHER = "other"


class PersonRef(BaseModel):
    """Standardized person reference.

    Used to represent any person-related data extracted from connectors,
    including assignees, owners, members, followers, creators, etc.

    The `id` field should be the original ID from the source system,
    ensuring traceability back to the source.
    """

    id: str = Field(..., description="Original ID from source system")
    name: Optional[str] = Field(None, description="Display name of the person")
    email: Optional[str] = Field(None, description="Email address if available")
    role: PersonRole = Field(
        PersonRole.OTHER, description="Role this person has (assignee, owner, etc.)"
    )
    avatar_url: Optional[str] = Field(None, description="URL to avatar/profile image")
    username: Optional[str] = Field(None, description="Username in the source system")

    # Additional properties from source (e.g., initials, color, team)
    properties: Dict[str, Any] = Field(
        default_factory=dict, description="Additional person properties from source"
    )

    model_config = ConfigDict(
        use_enum_values=True,
    )


class TagRef(BaseModel):
    """Standardized tag/label reference.

    Used to represent tags, labels, categories, or any other
    categorization data from connectors.
    """

    id: str = Field(..., description="Original ID from source system")
    name: str = Field(..., description="Display name of the tag")
    color: Optional[str] = Field(None, description="Tag color (hex or name)")
    tag_type: Optional[str] = Field(
        None, description="Type of tag if source distinguishes (e.g., status, priority)"
    )

    # Additional properties from source
    properties: Dict[str, Any] = Field(
        default_factory=dict, description="Additional tag properties from source"
    )


class RelationRef(BaseModel):
    """Standardized entity relationship reference.

    Used to represent relationships between entities such as
    parent-child, dependencies, or other connections.
    """

    entity_id: str = Field(..., description="ID of the related entity")
    entity_type: str = Field(..., description="Type of the related entity")
    relation_type: RelationType = Field(RelationType.RELATED_TO, description="Type of relationship")
    name: Optional[str] = Field(None, description="Name of the related entity for display")

    # Additional relationship metadata
    properties: Dict[str, Any] = Field(
        default_factory=dict, description="Additional relationship properties"
    )

    model_config = ConfigDict(
        use_enum_values=True,
    )


class StatusRef(BaseModel):
    """Standardized status reference.

    Used to represent status information with consistent structure.
    """

    id: Optional[str] = Field(None, description="Status ID from source")
    name: str = Field(..., description="Status name/label")
    color: Optional[str] = Field(None, description="Status color")
    category: Optional[str] = Field(
        None, description="Status category (e.g., 'todo', 'in_progress', 'done')"
    )

    # Additional properties from source
    properties: Dict[str, Any] = Field(
        default_factory=dict, description="Additional status properties"
    )


class PriorityRef(BaseModel):
    """Standardized priority reference.

    Used to represent priority information with consistent structure.
    """

    id: Optional[str] = Field(None, description="Priority ID from source")
    name: str = Field(..., description="Priority name/label")
    level: Optional[int] = Field(None, description="Numeric priority level (higher = more urgent)")
    color: Optional[str] = Field(None, description="Priority color")

    # Additional properties from source
    properties: Dict[str, Any] = Field(
        default_factory=dict, description="Additional priority properties"
    )


class CustomFieldRef(BaseModel):
    """Standardized custom field reference.

    Used to represent custom fields from various connectors
    in a consistent format.
    """

    id: str = Field(..., description="Custom field ID from source")
    name: str = Field(..., description="Custom field name")
    field_type: str = Field(..., description="Type of the field (text, number, date, etc.)")
    value: Any = Field(None, description="The field value")
    display_value: Optional[str] = Field(None, description="Human-readable display value")

    # Additional properties from source
    properties: Dict[str, Any] = Field(
        default_factory=dict, description="Additional field properties"
    )


class RelatedPersonRef(BaseModel):
    """Reference to a person related to an LLM-extracted entity.

    Used to create edges from extracted entities (like ActionItems) to PersonNodes.
    """

    email: str = Field(..., description="Email address of the related person")
    role: str = Field(
        "RELATES_TO",
        description="Role/relationship type (e.g., ASSIGNED_TO, MENTIONED, SCHEDULED_WITH)",
    )
    name: Optional[str] = Field(None, description="Person's name if known")
    canonical_node_id: Optional[str] = Field(
        None,
        description="Resolved PersonNode id after semantic merge (optional)",
    )


class LLMExtractionRef(BaseModel):
    """Standardized LLM-extracted entity reference.

    Used to represent entities extracted by LLM from unstructured content.
    The edge_type determines how this extraction relates to its source entity.

    This follows the same pattern as PersonRef, TagRef, etc. for unified
    graph event generation.

    Related persons (related_persons field) enable creating edges from the
    extracted entity to PersonNodes in the graph, e.g.:
    - ActionItem --ASSIGNED_TO--> PersonNode
    - Meeting --SCHEDULED_WITH--> PersonNode
    """

    id: str = Field(..., description="Generated stable node ID for the extracted entity")
    entity_type: str = Field(
        ..., description="Full type including subtype (e.g., 'EmailExtract:ActionItem')"
    )
    name: str = Field(..., description="Name/title of the extracted entity")
    edge_type: str = Field(
        ..., description="Edge type from source to this entity (e.g., 'CONTAINS_ACTION_ITEM')"
    )
    description: Optional[str] = Field(None, description="Description of the extracted entity")
    related_to: Optional[str] = Field(
        None,
        description="Primary person this relates to (email address) - deprecated, use related_persons",
    )
    related_persons: List[RelatedPersonRef] = Field(
        default_factory=list,
        description="Persons related to this extracted entity (creates edges to PersonNodes)",
    )
    confidence: float = Field(0.0, description="LLM extraction confidence score (0.0-1.0)")
    extraction_model: Optional[str] = Field(None, description="Model used for extraction")
    source_field: str = Field("_dynamic", description="Field the extraction came from")

    # Additional properties from LLM extraction
    properties: Dict[str, Any] = Field(
        default_factory=dict, description="Additional extracted properties"
    )


class NormalizedEntity(BaseModel):
    """Canonical entity format for pipeline processing.

    This is the standardized format that all connector entities are
    normalized to. It ensures consistent structure for:
    - PostgreSQL storage (entity table)
    - Neo4j graph nodes
    - Neo4j fulltext indexing

    Key principle: `entity_id` is the universal identifier used
    across all storage systems for traceability.
    """

    # -------------------------------------------------------------------------
    # Core Identity (same everywhere: PostgreSQL and Graph)
    # -------------------------------------------------------------------------
    entity_id: str = Field(..., description="Universal ID: PostgreSQL entity_id and Graph node_id")
    entity_type: str = Field(
        ..., description="Original entity class name (e.g., ClickUpTaskEntity)"
    )
    source_type: str = Field(..., description="Source connector short_name (e.g., 'clickup')")

    # -------------------------------------------------------------------------
    # Content
    # -------------------------------------------------------------------------
    name: str = Field(..., description="Primary display name")
    description: Optional[str] = Field(None, description="Description or summary")
    content: Optional[str] = Field(None, description="Main embeddable text content")
    web_url: Optional[str] = Field(None, description="URL to view in source application")

    # -------------------------------------------------------------------------
    # Standardized References (normalized from nested JSON)
    # -------------------------------------------------------------------------
    people: List[PersonRef] = Field(
        default_factory=list, description="All person references (assignees, owners, members, etc.)"
    )
    tags: List[TagRef] = Field(default_factory=list, description="All tags/labels")
    relations: List[RelationRef] = Field(
        default_factory=list, description="Parent/child/dependency relations"
    )
    status: Optional[StatusRef] = Field(None, description="Current status")
    priority: Optional[PriorityRef] = Field(None, description="Priority level")
    custom_fields: List[CustomFieldRef] = Field(
        default_factory=list, description="Custom field values"
    )

    # -------------------------------------------------------------------------
    # LLM Extractions (entities extracted from unstructured content)
    # -------------------------------------------------------------------------
    llm_extractions: List[LLMExtractionRef] = Field(
        default_factory=list,
        description="Entities extracted by LLM from unstructured content fields",
    )

    # -------------------------------------------------------------------------
    # Timestamps
    # -------------------------------------------------------------------------
    created_at: Optional[datetime] = Field(None, description="When entity was created in source")
    updated_at: Optional[datetime] = Field(None, description="When entity was last modified")
    due_at: Optional[datetime] = Field(None, description="Due date/time if applicable")
    completed_at: Optional[datetime] = Field(None, description="Completion date/time if applicable")

    # -------------------------------------------------------------------------
    # Flexible Extension
    # -------------------------------------------------------------------------
    properties: Dict[str, Any] = Field(
        default_factory=dict, description="Connector-specific fields that don't fit canonical model"
    )

    # -------------------------------------------------------------------------
    # Breadcrumbs (hierarchy context)
    # -------------------------------------------------------------------------
    breadcrumb_ids: List[str] = Field(
        default_factory=list, description="List of parent entity IDs for hierarchy context"
    )
    breadcrumb_names: List[str] = Field(
        default_factory=list, description="List of parent entity names for display"
    )

    def get_embeddable_text(self) -> str:
        """Generate combined embeddable text from all relevant fields.

        Returns:
            Combined text suitable for embedding/vectorization
        """
        parts = [self.name]

        if self.description:
            parts.append(self.description)

        if self.content:
            parts.append(self.content)

        # Add people names
        for person in self.people:
            if person.name:
                parts.append(f"{person.role}: {person.name}")

        # Add tags
        for tag in self.tags:
            parts.append(f"tag: {tag.name}")

        # Add status
        if self.status:
            parts.append(f"status: {self.status.name}")

        # Add priority
        if self.priority:
            parts.append(f"priority: {self.priority.name}")

        # Add custom field values
        for cf in self.custom_fields:
            if cf.display_value:
                parts.append(f"{cf.name}: {cf.display_value}")

        return "\n".join(parts)

    def get_people_by_role(self, role: PersonRole) -> List[PersonRef]:
        """Get all people with a specific role.

        Args:
            role: The role to filter by

        Returns:
            List of PersonRef with the specified role
        """
        return [p for p in self.people if p.role == role]

    def get_relations_by_type(self, relation_type: RelationType) -> List[RelationRef]:
        """Get all relations of a specific type.

        Args:
            relation_type: The relation type to filter by

        Returns:
            List of RelationRef with the specified type
        """
        return [r for r in self.relations if r.relation_type == relation_type]


class NormalizedFileEntity(NormalizedEntity):
    """Normalized entity for file attachments.

    Extends NormalizedEntity with file-specific fields.
    """

    # File-specific fields
    file_url: str = Field(..., description="URL to download the file")
    file_size: Optional[int] = Field(None, description="File size in bytes")
    file_type: Optional[str] = Field(None, description="File type/extension")
    mime_type: Optional[str] = Field(None, description="MIME type of the file")
    local_path: Optional[str] = Field(None, description="Local path after download")

    # File content (extracted text)
    extracted_text: Optional[str] = Field(None, description="Text extracted from file")
