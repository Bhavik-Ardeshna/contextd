"""Graph node models."""

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    """Base node model for Neo4j graph.

    Design principles:
    - node_id matches entity.entity_id from Postgres (converted to string)
    - node_type matches entity type name (e.g., 'AsanaTaskEntity', 'PersonNode')
    - properties contain all embeddable fields from entity
    - metadata tracks lineage and sync info
    """

    # Core identity (from events)
    node_id: str = Field(description="Unique node ID (matches entity_id)")
    node_type: str = Field(description="Node type (e.g., 'AsanaTaskEntity')")

    # Properties (from event payload)
    properties: Dict[str, Any] = Field(
        default_factory=dict, description="All node properties from entity"
    )

    # Metadata (tracking info)
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Extraction metadata, source info, etc."
    )

    # Graph organization
    organization_id: UUID = Field(description="Organization/user partition")

    # Timestamps
    created_at: Optional[datetime] = Field(None, description="When node was created")
    updated_at: Optional[datetime] = Field(None, description="Last update time")

    # Source tracking
    source_sync_id: Optional[UUID] = Field(None, description="Source sync ID")
    source_entity_definition_id: Optional[UUID] = Field(None)

    # Labels for Neo4j
    labels: list[str] = Field(
        default_factory=list, description="Additional labels for categorization"
    )


class NodeOperation(BaseModel):
    """Represents a node operation to execute."""

    operation: str = Field(description="CREATE, UPDATE, or DELETE")
    node: GraphNode
