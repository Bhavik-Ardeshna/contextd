"""Graph traversal module.

Provides efficient graph traversal algorithms for extracting subgraphs
from Neo4j based on starting nodes and hop depth.

Architecture:
- Strategy pattern for pluggable traversal algorithms
- Default: APOC-based traversal (most efficient)
- Extensible for custom algorithms

Usage:
    from contextd.platform.graph.traversal import TraversalService, TraversalConfig

    service = await TraversalService.create()
    result = await service.traverse(
        node_ids=["node-1", "node-2"],
        organization_id=org_id,
        config=TraversalConfig(max_depth=2),
    )
"""

from ._base import TraversalResult, TraversalStrategy
from .config import TraversalConfig, TraversalDirection
from .formatter import GraphContextFormatter
from .service import TraversalService

__all__ = [
    "TraversalService",
    "TraversalConfig",
    "TraversalDirection",
    "TraversalStrategy",
    "TraversalResult",
    "GraphContextFormatter",
]
