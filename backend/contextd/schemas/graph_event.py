"""Graph event Pydantic schemas."""

from datetime import datetime
from typing import Any, Dict, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Event Payload Schemas


class NodeReference(BaseModel):
    """Reference to a node in the graph."""

    node_type: str = Field(..., description="Type of the node (e.g., PersonEntity)")
    node_id: str = Field(..., description="Unique identifier for the node")


class NodeEventPayload(BaseModel):
    """Payload for node-related events."""

    node_id: str = Field(..., description="Unique identifier for the node")
    node_type: str = Field(..., description="Type of the node entity")
    node_properties: Dict[str, Any] = Field(
        default_factory=dict, description="Properties of the node"
    )
    operation: Literal["CREATE", "UPDATE", "DELETE"] = Field(
        ..., description="Operation to perform on the node"
    )


class EdgeEventPayload(BaseModel):
    """Payload for edge-related events."""

    from_node: NodeReference = Field(..., description="Source node of the edge")
    to_node: NodeReference = Field(..., description="Target node of the edge")
    edge_type: str = Field(..., description="Type/name of the edge relationship")
    direction: str = Field(
        ..., description="Direction of the edge (outgoing, incoming, bidirectional)"
    )
    edge_properties: Dict[str, Any] = Field(
        default_factory=dict, description="Additional edge metadata"
    )
    operation: Literal["CREATE", "UPDATE", "DELETE"] = Field(
        ..., description="Operation to perform on the edge"
    )
    is_reverse_edge: bool = Field(default=False, description="Whether this is a reverse edge")


class MetadataEventPayload(BaseModel):
    """Payload for metadata-related events."""

    category: str = Field(..., description="Category of metadata (description, tags, properties)")
    old_value_hash: Optional[str] = Field(
        None, description="Hash of previous value (None for new metadata)"
    )
    new_value_hash: str = Field(..., description="Hash of current value")
    indexed: bool = Field(default=True, description="Whether this metadata should be indexed")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata including source entity data"
    )


# Main Event Schema


class GraphEventBase(BaseModel):
    """Base schema for graph events."""

    entity_id: str = Field(..., description="ID of the entity that generated this event")
    entity_type: str = Field(..., description="Type of the entity")
    entity_definition_id: UUID = Field(..., description="Entity definition UUID")
    sync_id: UUID = Field(..., description="Sync configuration ID")
    sync_job_id: UUID = Field(..., description="Sync job ID")
    organization_id: UUID = Field(..., description="Organization ID")
    event_type: Literal[
        "NODE_CREATE",
        "NODE_UPDATE",
        "NODE_DELETE",
        "EDGE_CREATE",
        "EDGE_UPDATE",
        "EDGE_DELETE",
        "METADATA_UPDATE",
    ] = Field(..., description="Type of graph event")
    field_name: Optional[str] = Field(None, description="Field that triggered the event")
    node_id: Optional[str] = Field(
        None, description="Node ID for deduplication (extracted for NODE events)"
    )
    event_data: Dict[str, Any] = Field(..., description="Event payload data")
    state_version: str = Field(default="1.0", description="State version")
    commit_status: str = Field(
        default="pending", description="Two-phase commit status: pending|committed|failed|skipped"
    )


class GraphEventCreate(GraphEventBase):
    """Schema for creating a graph event."""

    pass


class GraphEventUpdate(BaseModel):
    """Schema for updating a graph event."""

    processed: Optional[bool] = None
    processed_at: Optional[datetime] = None

    # Two-phase commit updates
    commit_status: Optional[str] = Field(
        None, description="Two-phase commit status: pending|committed|failed|skipped"
    )
    commit_error: Optional[str] = Field(None, description="Error message if commit failed")
    committed_at: Optional[datetime] = Field(None, description="When the event was committed")


class GraphEvent(GraphEventBase):
    """Complete graph event schema with all fields."""

    id: UUID = Field(..., description="Unique event ID")
    created_at: datetime = Field(..., description="When the event was created")
    modified_at: datetime = Field(..., description="When the event was last modified")
    processed: bool = Field(default=False, description="Whether the event has been processed")
    processed_at: Optional[datetime] = Field(None, description="When the event was processed")
    commit_error: Optional[str] = Field(None, description="Error message if commit failed")
    committed_at: Optional[datetime] = Field(
        None, description="When the event was committed to Neo4j"
    )

    model_config = ConfigDict(
        from_attributes=True,
    )


# Typed Event Models for Generation


class TypedGraphEvent(BaseModel):
    """Typed graph event for generation (not stored directly)."""

    event_id: UUID = Field(default_factory=lambda: UUID(int=0), description="Event UUID")
    event_type: Literal[
        "NODE_CREATE",
        "NODE_UPDATE",
        "NODE_DELETE",
        "EDGE_CREATE",
        "EDGE_UPDATE",
        "EDGE_DELETE",
        "METADATA_UPDATE",
    ]
    entity_id: str
    entity_type: str
    entity_definition_id: UUID
    field_name: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    payload: Union[NodeEventPayload, EdgeEventPayload, MetadataEventPayload]

    # Event-level metadata (not stored in node/edge properties)
    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Event metadata for tracking extraction source, confidence, etc.",
    )
