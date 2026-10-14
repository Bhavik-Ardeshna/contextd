"""Base interface for graph traversal strategies.

Defines the abstract interface that all traversal strategies must implement.
This enables easy swapping of algorithms and addition of custom implementations.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID

from .config import TraversalConfig

logger = logging.getLogger(__name__)


@dataclass
class TraversedNode:
    """Represents a node discovered during traversal.

    Attributes:
        node_id: Unique identifier for the node
        node_type: Type/label of the node
        name: Display name of the node
        properties: Full node properties (if include_properties=True)
        depth: Distance from starting node (0 = start node)
        source_node_id: The starting node this was discovered from
    """

    node_id: str
    node_type: str
    name: Optional[str] = None
    properties: Dict[str, Any] = field(default_factory=dict)
    depth: int = 0
    source_node_id: Optional[str] = None


@dataclass
class TraversedEdge:
    """Represents an edge discovered during traversal.

    Attributes:
        from_node_id: Source node ID
        to_node_id: Target node ID
        relationship_type: Type of the relationship
        properties: Edge properties
        direction: Direction relative to traversal (outgoing/incoming)
    """

    from_node_id: str
    to_node_id: str
    relationship_type: str
    properties: Dict[str, Any] = field(default_factory=dict)
    direction: str = "outgoing"


@dataclass
class TraversalResult:
    """Result of a graph traversal operation.

    Attributes:
        nodes: List of discovered nodes
        edges: List of discovered edges
        start_node_ids: Original starting node IDs
        config: Configuration used for traversal
        stats: Statistics about the traversal
    """

    nodes: List[TraversedNode] = field(default_factory=list)
    edges: List[TraversedEdge] = field(default_factory=list)
    start_node_ids: List[str] = field(default_factory=list)
    config: Optional[TraversalConfig] = None
    stats: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "nodes": [
                {
                    "node_id": n.node_id,
                    "node_type": n.node_type,
                    "name": n.name,
                    "properties": n.properties,
                    "depth": n.depth,
                    "source_node_id": n.source_node_id,
                }
                for n in self.nodes
            ],
            "edges": [
                {
                    "from_node_id": e.from_node_id,
                    "to_node_id": e.to_node_id,
                    "relationship_type": e.relationship_type,
                    "properties": e.properties,
                    "direction": e.direction,
                }
                for e in self.edges
            ],
            "start_node_ids": self.start_node_ids,
            "stats": self.stats,
        }

    def get_nodes_by_depth(self, depth: int) -> List[TraversedNode]:
        """Get all nodes at a specific depth."""
        return [n for n in self.nodes if n.depth == depth]

    def get_connected_nodes(self, node_id: str) -> List[TraversedNode]:
        """Get all nodes directly connected to a given node."""
        connected_ids = set()
        for edge in self.edges:
            if edge.from_node_id == node_id:
                connected_ids.add(edge.to_node_id)
            elif edge.to_node_id == node_id:
                connected_ids.add(edge.from_node_id)

        return [n for n in self.nodes if n.node_id in connected_ids]


class TraversalStrategy(ABC):
    """Abstract base class for graph traversal strategies.

    Implement this interface to add new traversal algorithms.
    The strategy pattern allows runtime selection of algorithms.

    Example implementation:
        class CustomStrategy(TraversalStrategy):
            @property
            def name(self) -> str:
                return "custom"

            async def traverse(self, node_ids, org_id, config) -> TraversalResult:
                # Custom traversal logic
                pass
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name for this strategy."""
        pass

    @abstractmethod
    async def traverse(
        self,
        node_ids: List[str],
        organization_id: UUID,
        config: TraversalConfig,
        neo4j_database: Optional[str] = None,
    ) -> TraversalResult:
        """Execute graph traversal from starting nodes.

        Args:
            node_ids: Starting node IDs for traversal
            organization_id: Organization ID for multi-tenant filtering
            config: Traversal configuration
            neo4j_database: Optional Neo4j database to execute against

        Returns:
            TraversalResult containing discovered nodes and edges
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources."""
        pass
