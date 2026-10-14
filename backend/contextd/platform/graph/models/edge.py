"""Graph edge models."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class GraphEdge(BaseModel):
    """Base edge model for Neo4j graph.

    Design principles:
    - edge_id matches the relationship ID from event
    - Stores fact text and embedding on the edge
    - source_node_id/target_node_id reference GraphNode.node_id
    - Supports relationship properties from event payload
    """

    # Core identity
    edge_id: str = Field(description="Unique edge ID")
    relationship_type: str = Field(description="Relationship type (e.g., 'ASSIGNED_TO')")

    # Node references
    source_node_id: str = Field(description="Source node ID")
    target_node_id: str = Field(description="Target node ID")

    # Fact representation (inspired by graphiti)
    fact: Optional[str] = Field(
        None, description="Natural language fact describing the relationship"
    )
    fact_embedding: Optional[List[float]] = Field(
        None, description="Embedding of the fact for semantic search"
    )

    # Properties (from event payload)
    properties: Dict[str, Any] = Field(
        default_factory=dict, description="Additional relationship properties"
    )

    # Metadata
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Edge metadata and tracking info"
    )

    # Graph organization
    organization_id: UUID = Field(description="Organization/user partition")

    # Timestamps
    created_at: Optional[datetime] = Field(None, description="When edge was created")
    updated_at: Optional[datetime] = Field(None, description="Last update time")

    # Source tracking
    source_sync_id: Optional[UUID] = Field(None, description="Source sync ID")
    source_entity_definition_id: Optional[UUID] = Field(None)

    # Temporal validity (optional)
    valid_at: Optional[datetime] = Field(None, description="When fact became true")
    invalid_at: Optional[datetime] = Field(None, description="When fact stopped being true")


class EdgeOperation(BaseModel):
    """Represents an edge operation to execute."""

    operation: str = Field(description="CREATE, UPDATE, or DELETE")
    edge: GraphEdge
