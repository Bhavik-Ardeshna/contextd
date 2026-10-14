"""Graph traversal service.

High-level service for executing graph traversals with strategy selection,
caching, and error handling.
"""

import logging
from typing import Dict, List, Optional, Type
from uuid import UUID

from contextd.platform.graph.config import get_graph_config

from ._base import TraversalResult, TraversalStrategy
from .apoc_strategy import APOCTraversalStrategy
from .config import TraversalConfig
from .g_retriever_strategy import PCSTTraversalStrategy
from .ppr_strategy import PPRTraversalStrategy

logger = logging.getLogger(__name__)


# Registry of available strategies
_STRATEGY_REGISTRY: Dict[str, Type[TraversalStrategy]] = {
    "apoc": APOCTraversalStrategy,
    "pcst": PCSTTraversalStrategy,
    "ppr": PPRTraversalStrategy,
}


def register_strategy(name: str, strategy_class: Type[TraversalStrategy]) -> None:
    """Register a custom traversal strategy.

    Use this to add custom algorithms at runtime:

        from contextd.platform.graph.traversal import register_strategy

        class MyCustomStrategy(TraversalStrategy):
            ...

        register_strategy("custom", MyCustomStrategy)

    Args:
        name: Unique strategy name
        strategy_class: Strategy class implementing TraversalStrategy
    """
    _STRATEGY_REGISTRY[name] = strategy_class
    logger.info(f"[TraversalService] Registered strategy: {name}")


class TraversalService:
    """High-level service for graph traversal operations.

    Provides:
    - Strategy selection and management
    - Default configuration handling
    - Error handling and logging
    - Resource cleanup

    Usage:
        service = await TraversalService.create()
        result = await service.traverse(
            node_ids=["node-1"],
            organization_id=org_id,
            config=TraversalConfig(max_depth=3),
        )
        await service.close()
    """

    def __init__(self):
        """Initialize service (use create() factory method)."""
        self._strategies: Dict[str, TraversalStrategy] = {}
        self._default_config = TraversalConfig()
        self._default_strategy = get_graph_config().traversal_strategy

    @classmethod
    async def create(
        cls,
        default_strategy: Optional[str] = None,
        default_config: Optional[TraversalConfig] = None,
    ) -> "TraversalService":
        """Factory method to create service.

        Args:
            default_strategy: Default strategy name
            default_config: Default traversal configuration

        Returns:
            Initialized TraversalService
        """
        service = cls()

        if default_config:
            service._default_config = default_config

        if default_strategy:
            service._default_strategy = default_strategy

        # Initialize default strategy
        await service._get_or_create_strategy(service._default_strategy)

        logger.info(
            f"[TraversalService] Initialized with strategy={service._default_strategy}, "
            f"default_depth={service._default_config.max_depth}"
        )

        return service

    async def _get_or_create_strategy(
        self,
        strategy_name: str,
    ) -> TraversalStrategy:
        """Get or create a strategy instance.

        Strategies are cached for reuse.

        Args:
            strategy_name: Name of the strategy

        Returns:
            Strategy instance

        Raises:
            ValueError: If strategy not registered
        """
        if strategy_name in self._strategies:
            return self._strategies[strategy_name]

        if strategy_name not in _STRATEGY_REGISTRY:
            available = list(_STRATEGY_REGISTRY.keys())
            raise ValueError(
                f"Unknown strategy '{strategy_name}'. Available: {available}"
            )

        strategy_class = _STRATEGY_REGISTRY[strategy_name]
        strategy = strategy_class()
        self._strategies[strategy_name] = strategy

        return strategy

    async def traverse(
        self,
        node_ids: List[str],
        organization_id: UUID,
        config: Optional[TraversalConfig] = None,
        strategy_name: Optional[str] = None,
        readable_collection_id: Optional[str] = None,
    ) -> TraversalResult:
        """Execute graph traversal from starting nodes.

        Args:
            node_ids: Starting node IDs
            organization_id: Organization for multi-tenant filtering
            config: Traversal configuration (uses default if not provided)
            strategy_name: Strategy to use (uses default if not provided)

        Returns:
            TraversalResult containing nodes and edges
        """
        effective_config = config or self._default_config
        effective_strategy = strategy_name or self._default_strategy
        neo4j_database: Optional[str] = None
        if readable_collection_id:
            from contextd.platform.graph.factory import get_graph_driver

            driver = await get_graph_driver()
            neo4j_database = await driver.ensure_context_database(
                organization_id,
                readable_collection_id,
            )

        logger.info(
            f"[TraversalService] Starting traversal: "
            f"nodes={len(node_ids)}, depth={effective_config.max_depth}, "
            f"strategy={effective_strategy}"
        )

        try:
            strategy = await self._get_or_create_strategy(effective_strategy)

            result = await strategy.traverse(
                node_ids=node_ids,
                organization_id=organization_id,
                config=effective_config,
                neo4j_database=neo4j_database,
            )

            logger.info(
                f"[TraversalService] Traversal complete: "
                f"{len(result.nodes)} nodes, {len(result.edges)} edges"
            )

            return result

        except Exception as e:
            logger.error(f"[TraversalService] Traversal failed: {e}", exc_info=True)
            raise

    async def traverse_from_search_results(
        self,
        search_results: List[Dict],
        organization_id: UUID,
        config: Optional[TraversalConfig] = None,
    ) -> TraversalResult:
        """Traverse from search result node IDs.

        Convenience method for integrating with search operations.
        Extracts node_ids from search results and traverses.

        Args:
            search_results: Search results with node_id field
            organization_id: Organization ID
            config: Traversal configuration

        Returns:
            TraversalResult
        """
        # Extract node IDs from search results
        node_ids = []
        for result in search_results:
            node_id = result.get("node_id")
            if node_id:
                node_ids.append(node_id)

        if not node_ids:
            logger.warning("[TraversalService] No node IDs found in search results")
            return TraversalResult(start_node_ids=[], config=config)

        return await self.traverse(
            node_ids=node_ids,
            organization_id=organization_id,
            config=config,
        )

    def get_available_strategies(self) -> List[str]:
        """Get list of registered strategy names."""
        return list(_STRATEGY_REGISTRY.keys())

    async def close(self) -> None:
        """Close all strategy resources."""
        for name, strategy in self._strategies.items():
            try:
                await strategy.close()
                logger.debug(f"[TraversalService] Closed strategy: {name}")
            except Exception as e:
                logger.warning(f"[TraversalService] Error closing {name}: {e}")

        self._strategies.clear()
