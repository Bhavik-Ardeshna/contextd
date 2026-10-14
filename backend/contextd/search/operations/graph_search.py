"""Graph search operation.

Search combines:
1. Fulltext search via Neo4j
2. Graph traversal for context expansion

This operation enables rich, context-aware search across the knowledge graph.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from contextd.api.context import ApiContext
from contextd.platform.graph.driver.neo4j_driver import convert_neo4j_types
from contextd.search.context import SearchContext

from ._base import SearchOperation

logger = logging.getLogger(__name__)


def _ensure_serializable(obj: Any) -> Any:
    """Ensure object is JSON-serializable.

    Uses the centralized convert_neo4j_types from the driver module.
    This is a thin wrapper that also handles datetime to ISO string conversion
    for API responses that expect strings rather than datetime objects.
    """
    # First, convert any Neo4j types to Python native types
    obj = convert_neo4j_types(obj)

    # Then ensure datetime objects are ISO strings for JSON serialization
    if isinstance(obj, datetime):
        return obj.isoformat()

    if isinstance(obj, dict):
        return {k: _ensure_serializable(v) for k, v in obj.items()}

    if isinstance(obj, (list, tuple)):
        converted = [_ensure_serializable(item) for item in obj]
        return type(obj)(converted) if isinstance(obj, tuple) else converted

    return obj


class GraphSearch(SearchOperation):
    """Graph search combining fulltext and graph traversal.

    Search Flow:
    1. Fulltext Search (Neo4j): Query fulltext indexes, get matching node_ids
    2. Graph Expansion: When graph_depth > 0, use PPR (or configured traversal strategy)
       for relevance-weighted expansion; falls back to simple 1-hop if traversal unavailable.
    """

    def __init__(
        self,
        collection_id: UUID,
        organization_id: UUID,
        limit: int = 20,
        graph_depth: int = 2,
        include_related: bool = True,
        semantic_weight: float = 0.0,
        fulltext_weight: float = 1.0,
        min_score: float = 0.0,
        source_type_filter: Optional[str] = None,
    ) -> None:
        """Initialize graph search operation.

        Args:
            collection_id: Collection to search
            organization_id: Organization filter
            limit: Maximum primary results
            graph_depth: Depth for graph traversal (0 = no traversal)
            include_related: Whether to include related nodes from traversal
            semantic_weight: Retained for request compatibility; unused by the live path
            fulltext_weight: Weight for fulltext search scores (0-1)
            min_score: Minimum score threshold
            source_type_filter: If set (e.g. from @gmail), restrict to this connector.
        """
        self.collection_id = collection_id
        self.organization_id = organization_id
        self.limit = limit
        self.graph_depth = graph_depth
        self.include_related = include_related
        self.semantic_weight = semantic_weight
        self.fulltext_weight = fulltext_weight
        self.min_score = min_score
        self.source_type_filter = source_type_filter

    def depends_on(self) -> List[str]:
        """Dependencies for graph search.

        Neo4j fulltext does not require client-side embeddings.
        """
        return []

    async def execute(
        self,
        context: SearchContext,
        state: dict[str, Any],
        ctx: ApiContext,
    ) -> None:
        """Execute graph search.

        Args:
            context: Search context
            state: Shared search operation state
            ctx: API context
        """
        ctx.logger.info(f"[GraphSearch] Executing graph search for: {context.query[:50]}...")

        fulltext_results = []

        try:
            fulltext_results = await self._fulltext_search(
                query=context.query,
                limit=self.limit,
                ctx=ctx,
                readable_collection_id=context.readable_collection_id,
            )
            ctx.logger.debug(
                f"[GraphSearch] Fulltext search returned {len(fulltext_results)} results"
            )
        except Exception as e:
            ctx.logger.warning(f"[GraphSearch] Fulltext search failed: {e}")

        primary_results = fulltext_results[: self.limit]
        ctx.logger.debug(f"[GraphSearch] Primary fulltext results: {len(primary_results)}")

        # Expand with graph traversal if enabled
        expanded_results = {}
        related_nodes = []

        if self.include_related and self.graph_depth > 0 and primary_results:
            try:
                node_ids = [r["node_id"] for r in primary_results]
                expanded_results = await self._expand_with_graph(
                    node_ids=node_ids,
                    depth=self.graph_depth,
                    ctx=ctx,
                    readable_collection_id=context.readable_collection_id,
                )

                # Extract related nodes not in primary results
                primary_node_ids = set(node_ids)
                for node_id, data in expanded_results.items():
                    if node_id not in primary_node_ids:
                        related_nodes.append(data)

                ctx.logger.debug(
                    f"[GraphSearch] Graph expansion found {len(related_nodes)} related nodes"
                )
            except Exception as e:
                ctx.logger.warning(f"[GraphSearch] Graph expansion failed: {e}")

        # Build final results
        final_results = []

        for result in primary_results:
            # Enrich with graph data if available
            node_id = result["node_id"]
            graph_data = expanded_results.get(node_id, {})

            final_results.append(
                {
                    "id": result.get("id", node_id),
                    "node_id": node_id,
                    "node_type": result.get("node_type"),
                    "name": result.get("name"),
                    "score": result["score"],
                    "payload": result.get("payload", {}),
                    "source": result.get("source", "unknown"),
                    "graph_context": graph_data.get("context", {}),
                    "relationships": graph_data.get("relationships", []),
                }
            )

        # Write to state
        state["graph_results"] = final_results
        state["related_nodes"] = related_nodes[: self.limit // 2]  # Limit related nodes
        state["graph_search_stats"] = {
            "fulltext_count": len(fulltext_results),
            "primary_count": len(final_results),
            "related_count": len(related_nodes),
        }

        # Report metrics
        self._report_metrics(
            state,
            fulltext_count=len(fulltext_results),
            primary_count=len(final_results),
            related_count=len(related_nodes),
            graph_depth=self.graph_depth,
            fulltext_weight=self.fulltext_weight,
        )

        ctx.logger.info(
            f"[GraphSearch] Complete: {len(final_results)} primary, "
            f"{len(related_nodes)} related nodes"
        )

    async def _fulltext_search(
        self,
        query: str,
        limit: int,
        ctx: ApiContext,
        readable_collection_id: str,
    ) -> List[Dict[str, Any]]:
        """Search fulltext indexes in Neo4j.

        Args:
            query: Text query
            limit: Max results
            ctx: API context

        Returns:
            List of search results with node_ids
        """
        from contextd.platform.graph.fulltext_service import FulltextService

        try:
            service = await FulltextService.create(
                organization_id=self.organization_id,
                readable_collection_id=readable_collection_id,
            )
        except Exception as e:
            ctx.logger.warning(f"[GraphSearch] Could not create fulltext service: {e}")
            return []

        try:
            search_limit = limit * 5 if self.source_type_filter else limit
            results = await service.search_fulltext(
                query=query,
                limit=search_limit,
                min_score=self.min_score,
                organization_id=str(self.organization_id),
            )
            results = self._filter_by_source_type(results)

            # Convert Neo4j types to JSON-serializable Python types
            return [
                {
                    "id": r["node_id"],
                    "node_id": r["node_id"],
                    "node_type": r.get("node_type"),
                    "name": r.get("name"),
                    "score": r.get("score", 0),
                    "payload": _ensure_serializable(r.get("properties", {})),
                    "source": "fulltext",
                }
                for r in results[:limit]
            ]
        finally:
            await service.close()

    def _filter_by_source_type(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply connector scoping parsed from @connector graph-chat queries."""
        if not self.source_type_filter:
            return results

        expected = self.source_type_filter.strip().lower()
        if not expected:
            return results

        filtered: List[Dict[str, Any]] = []
        for result in results:
            props = result.get("properties") or {}
            source_type = result.get("source_type")
            if not source_type and isinstance(props, dict):
                source_type = props.get("source_type")
            if source_type and str(source_type).strip().lower() == expected:
                filtered.append(result)
        return filtered

    async def _expand_with_graph(
        self,
        node_ids: List[str],
        depth: int,
        ctx: ApiContext,
        readable_collection_id: str,
    ) -> Dict[str, Dict[str, Any]]:
        """Expand search results using graph traversal.

        Fetches connected nodes and relationship context for each result.

        Args:
            node_ids: Node IDs to expand from
            depth: Traversal depth
            ctx: API context

        Returns:
            Dict mapping node_id to expanded context
        """
        from contextd.platform.graph.config import get_graph_config
        from contextd.platform.graph.traversal import TraversalConfig, TraversalService

        config = get_graph_config()
        if not config.enabled:
            return {}

        # Prefer PPR (or configured strategy) for relevance-weighted expansion
        try:
            service = await TraversalService.create()
            try:
                node_limit = getattr(config, "ppr_top_k", 100)
                traversal_config = TraversalConfig(
                    max_depth=max(1, depth),
                    node_limit=node_limit,
                    include_properties=True,
                )
                traversal_result = await service.traverse(
                    node_ids=node_ids,
                    organization_id=self.organization_id,
                    config=traversal_config,
                    strategy_name=config.traversal_strategy,
                    readable_collection_id=readable_collection_id,
                )
                return self._traversal_result_to_expanded(
                    traversal_result=traversal_result,
                    seed_node_ids=node_ids,
                )
            finally:
                await service.close()
        except Exception as e:
            ctx.logger.debug(
                "[GraphSearch] Traversal (PPR/strategy) failed, using simple expansion: %s",
                e,
            )
            return await self._expand_with_graph_simple(
                node_ids,
                depth,
                ctx,
                readable_collection_id=readable_collection_id,
            )

    def _traversal_result_to_expanded(
        self,
        traversal_result: Any,
        seed_node_ids: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """Convert TraversalResult to expanded_results format (context + relationships per node)."""
        from contextd.platform.graph.traversal._base import TraversedNode

        node_map: Dict[str, TraversedNode] = {n.node_id: n for n in traversal_result.nodes}
        results: Dict[str, Dict[str, Any]] = {}

        for nid in node_map:
            node = node_map[nid]
            context = {
                "node_type": node.node_type,
                "name": node.name,
                "properties": _ensure_serializable(node.properties) if node.properties else {},
            }
            rels = [
                e for e in traversal_result.edges if e.from_node_id == nid or e.to_node_id == nid
            ]
            relationships = []
            for e in rels:
                other = e.to_node_id if e.from_node_id == nid else e.from_node_id
                other_node = node_map.get(other)
                direction = "outgoing" if e.from_node_id == nid else "incoming"
                relationships.append(
                    _ensure_serializable(
                        {
                            "related_id": other,
                            "related_type": other_node.node_type if other_node else None,
                            "related_name": other_node.name if other_node else None,
                            "relationship_type": e.relationship_type,
                            "direction": direction,
                        }
                    )
                )
            results[nid] = {"context": context, "relationships": relationships[:10]}

        return results

    async def _expand_with_graph_simple(
        self,
        node_ids: List[str],
        depth: int,
        ctx: ApiContext,
        readable_collection_id: str,
    ) -> Dict[str, Dict[str, Any]]:
        """Simple expansion: per-node 1-hop context (fallback when PPR/traversal unavailable)."""
        from contextd.platform.graph.config import get_graph_config
        from contextd.platform.graph.driver.neo4j_driver import Neo4jDriver

        config = get_graph_config()
        if not config.enabled:
            return {}

        driver = Neo4jDriver(
            uri=config.neo4j_uri,
            user=config.neo4j_user,
            password=config.neo4j_password,
            database=config.neo4j_database,
        )
        try:
            await driver.connect()
            target_database = await driver.ensure_context_database(
                self.organization_id,
                readable_collection_id,
            )
            scoped_driver = driver.for_database(target_database)
            results = {}
            for node_id in node_ids:
                context_data = await self._get_node_context(
                    driver=scoped_driver,
                    node_id=node_id,
                    depth=depth,
                    organization_id=str(self.organization_id),
                )
                results[node_id] = context_data
            return results
        finally:
            await driver.close()

    async def _get_node_context(
        self,
        driver,
        node_id: str,
        depth: int,
        organization_id: str,
    ) -> Dict[str, Any]:
        """Get context for a single node.

        Args:
            driver: Neo4j driver
            node_id: Node to get context for
            depth: Traversal depth
            organization_id: Organization filter

        Returns:
            Node context including relationships
        """
        # Query for node and immediate relationships
        query = """
        MATCH (n {node_id: $node_id, organization_id: $org_id})
        OPTIONAL MATCH (n)-[r]-(related)
        WHERE related.organization_id = $org_id
        RETURN n.node_id AS node_id,
               n.node_type AS node_type,
               n.name AS name,
               properties(n) AS properties,
               collect(DISTINCT {
                   related_id: related.node_id,
                   related_type: related.node_type,
                   related_name: related.name,
                   relationship_type: type(r),
                   direction: CASE WHEN startNode(r) = n THEN 'outgoing' ELSE 'incoming' END
               }) AS relationships
        """

        try:
            records = await driver.execute_read(
                query,
                {
                    "node_id": node_id,
                    "org_id": organization_id,
                },
            )

            if not records:
                return {"context": {}, "relationships": []}

            record = records[0]

            # Filter out empty relationships and ensure JSON serializable
            # Note: Neo4j driver now handles type conversion automatically,
            # but we use _ensure_serializable for datetime -> ISO string conversion
            relationships = [
                _ensure_serializable(r)
                for r in record.get("relationships", [])
                if r.get("related_id")
            ]

            # Ensure properties are JSON serializable
            properties = _ensure_serializable(record.get("properties", {}))

            return {
                "context": {
                    "node_type": record.get("node_type"),
                    "name": record.get("name"),
                    "properties": properties,
                },
                "relationships": relationships[:10],  # Limit relationships
            }

        except Exception as e:
            logger.warning(f"Failed to get context for node {node_id}: {e}")
            return {"context": {}, "relationships": []}


class GraphSearchRequest:
    """Request object for graph search."""

    def __init__(
        self,
        query: str,
        collection_id: UUID,
        organization_id: UUID,
        limit: int = 20,
        graph_depth: int = 2,
        include_related: bool = True,
        retrieval_strategy: str = "hybrid",
    ):
        self.query = query
        self.collection_id = collection_id
        self.organization_id = organization_id
        self.limit = limit
        self.graph_depth = graph_depth
        self.include_related = include_related
        self.retrieval_strategy = retrieval_strategy


class GraphSearchResponse:
    """Response object for graph search."""

    def __init__(
        self,
        results: List[Dict[str, Any]],
        related_nodes: List[Dict[str, Any]],
        stats: Dict[str, Any],
    ):
        self.results = results
        self.related_nodes = related_nodes
        self.stats = stats
        self.total = len(results)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "results": self.results,
            "related_nodes": self.related_nodes,
            "total": self.total,
            "stats": self.stats,
        }
