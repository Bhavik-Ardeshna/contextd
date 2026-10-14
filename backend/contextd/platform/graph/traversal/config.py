"""Graph traversal configuration.

Defines configuration options for graph traversal operations.
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class TraversalDirection(str, Enum):
    """Direction for relationship traversal."""

    OUTGOING = "outgoing"
    INCOMING = "incoming"
    BOTH = "both"


class TraversalConfig(BaseModel):
    """Configuration for graph traversal operations.

    Attributes:
        max_depth: Maximum number of hops from starting nodes (default: 2)
        direction: Relationship traversal direction (default: BOTH)
        relationship_types: Optional filter for specific relationship types.
                          If None or empty, all relationships are followed.
        node_limit: Maximum number of nodes to return per traversal (default: 100)
        include_properties: Whether to include full node properties (default: True)
        include_start_nodes: Whether to include starting nodes in results (default: True)
        deduplicate: Whether to remove duplicate nodes (default: True)
    """

    max_depth: int = Field(
        default=2, ge=1, le=10, description="Maximum number of hops from starting nodes"
    )

    direction: TraversalDirection = Field(
        default=TraversalDirection.BOTH, description="Direction for relationship traversal"
    )

    relationship_types: Optional[List[str]] = Field(
        default=None, description="Filter for specific relationship types (None = all)"
    )

    node_limit: int = Field(
        default=100, ge=1, le=1000, description="Maximum nodes to return per traversal"
    )

    include_properties: bool = Field(
        default=True, description="Include full node properties in results"
    )

    include_start_nodes: bool = Field(default=True, description="Include starting nodes in results")

    deduplicate: bool = Field(default=True, description="Remove duplicate nodes from results")

    model_config = ConfigDict(
        use_enum_values=True,
    )
