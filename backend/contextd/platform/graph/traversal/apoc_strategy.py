"""APOC-based graph traversal strategy.

Uses Neo4j APOC library's path expansion procedures for efficient
subgraph extraction with configurable depth and filtering.

APOC Procedures Used:
- apoc.path.subgraphAll: Extract complete subgraph within N hops
- Supports BFS traversal, relationship filtering, and node limits
"""

import json
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from contextd.platform.graph.config import get_graph_config
from contextd.platform.graph.driver.neo4j_driver import Neo4jDriver

from ._base import (
    TraversalConfig,
    TraversalResult,
    TraversalStrategy,
    TraversedEdge,
    TraversedNode,
)
from .config import TraversalDirection

logger = logging.getLogger(__name__)


class APOCTraversalStrategy(TraversalStrategy):
    """APOC-based graph traversal using subgraphAll procedure.

    This strategy leverages Neo4j's APOC library for efficient
    subgraph extraction. It's optimized for:
    - Variable-depth traversal (1-10 hops)
    - Relationship type filtering
    - Directional traversal (outgoing/incoming/both)
    - Multi-tenant isolation via organization_id

    Performance Notes:
    - Uses BFS by default for shortest paths first
    - Limits nodes to prevent memory issues
    - Deduplicates results automatically
    """

    def __init__(self, driver: Optional[Neo4jDriver] = None):
        """Initialize APOC strategy.

        Args:
            driver: Optional Neo4j driver. If not provided, creates one.
        """
        self._driver = driver
        self._owns_driver = driver is None

    @property
    def name(self) -> str:
        return "apoc"

    async def _ensure_driver(self) -> Neo4jDriver:
        """Ensure Neo4j driver is available."""
        if self._driver is None:
            graph_config = get_graph_config()
            self._driver = Neo4jDriver(
                uri=graph_config.neo4j_uri,
                user=graph_config.neo4j_user,
                password=graph_config.neo4j_password,
            )
            await self._driver.connect()
            self._owns_driver = True
        return self._driver

    async def traverse(
        self,
        node_ids: List[str],
        organization_id: UUID,
        config: TraversalConfig,
        neo4j_database: Optional[str] = None,
    ) -> TraversalResult:
        """Execute APOC subgraph traversal.

        Uses apoc.path.subgraphAll for efficient traversal with:
        - BFS exploration (closest nodes first)
        - Configurable max depth
        - Relationship and direction filtering
        - Organization-scoped results

        Args:
            node_ids: Starting node IDs
            organization_id: Organization for multi-tenant filtering
            config: Traversal configuration

        Returns:
            TraversalResult with nodes and edges
        """
        if not node_ids:
            return TraversalResult(start_node_ids=[], config=config)

        driver = await self._ensure_driver()
        if neo4j_database:
            driver = driver.for_database(neo4j_database)

        # Build relationship filter for APOC
        rel_filter = self._build_relationship_filter(
            config.relationship_types,
            config.direction,
        )

        # Build APOC query
        query = self._build_apoc_query(config, rel_filter)

        params = {
            "node_ids": node_ids,
            "org_id": str(organization_id),
            "max_depth": config.max_depth,
            "node_limit": config.node_limit,
        }

        logger.debug(
            f"[APOCStrategy] Traversing from {len(node_ids)} nodes, "
            f"depth={config.max_depth}, rel_filter={rel_filter}"
        )

        try:
            records = await driver.execute_read(query, params)

            result = self._parse_results(
                records,
                node_ids,
                config,
            )

            logger.info(
                f"[APOCStrategy] Traversal complete: "
                f"{len(result.nodes)} nodes, {len(result.edges)} edges"
            )

            return result

        except Exception as e:
            # Check if APOC is not available
            if "apoc" in str(e).lower() and "not found" in str(e).lower():
                logger.warning(
                    f"[APOCStrategy] APOC not available, falling back to Cypher: {e}"
                )
                return await self._fallback_cypher_traverse(
                    driver, node_ids, organization_id, config
                )
            raise

    def _build_relationship_filter(
        self,
        relationship_types: Optional[List[str]],
        direction: TraversalDirection,
    ) -> str:
        """Build APOC relationship filter string.

        APOC filter syntax:
        - "TYPE" = both directions
        - "TYPE>" = outgoing only
        - "<TYPE" = incoming only
        - "TYPE1|TYPE2" = multiple types

        Args:
            relationship_types: Optional list of relationship types
            direction: Traversal direction

        Returns:
            APOC relationship filter string or empty string for all
        """
        if not relationship_types:
            # All relationships in specified direction
            if direction == TraversalDirection.OUTGOING:
                return ">"
            elif direction == TraversalDirection.INCOMING:
                return "<"
            else:
                return ""  # Both directions, all types

        # Build filter with types
        types_str = "|".join(relationship_types)

        if direction == TraversalDirection.OUTGOING:
            return f"{types_str}>"
        elif direction == TraversalDirection.INCOMING:
            return f"<{types_str}"
        else:
            return types_str  # Both directions

    def _build_apoc_query(
        self,
        config: TraversalConfig,
        rel_filter: str,
    ) -> str:
        """Build APOC subgraphAll query.

        Uses apoc.path.subgraphAll which returns both nodes and relationships
        in a single call, making it more efficient than separate queries.

        Args:
            config: Traversal configuration
            rel_filter: APOC relationship filter

        Returns:
            Cypher query string
        """
        # Build APOC config map
        apoc_config_parts = [
            "maxLevel: $max_depth",
            "bfs: true",  # Breadth-first for shortest paths
            "limit: $node_limit",
        ]

        if rel_filter:
            apoc_config_parts.append(f"relationshipFilter: '{rel_filter}'")

        apoc_config = "{" + ", ".join(apoc_config_parts) + "}"

        # Main query: find start nodes, expand subgraph, filter by org
        query = f"""
        // Find starting nodes within organization
        MATCH (start:GraphNode)
        WHERE start.node_id IN $node_ids
          AND start.organization_id = $org_id

        // Expand subgraph using APOC
        CALL apoc.path.subgraphAll(start, {apoc_config})
        YIELD nodes, relationships

        // Unwind and filter nodes by organization
        UNWIND nodes AS node
        WITH DISTINCT node, relationships
        WHERE node.organization_id = $org_id

        // Collect unique nodes
        WITH collect(DISTINCT node) AS all_nodes, relationships

        // Filter relationships to only include those between our nodes
        UNWIND relationships AS rel
        WITH all_nodes, rel, startNode(rel) AS from_node, endNode(rel) AS to_node
        WHERE from_node IN all_nodes AND to_node IN all_nodes

        // Return nodes and relationships
        WITH all_nodes, collect(DISTINCT {{
            from_id: from_node.node_id,
            to_id: to_node.node_id,
            rel_type: type(rel),
            properties: properties(rel)
        }}) AS all_rels

        UNWIND all_nodes AS n
        RETURN
            collect(DISTINCT {{
                node_id: n.node_id,
                node_type: n.node_type,
                name: n.ft_name,
                properties: n.properties,
                labels: labels(n)
            }}) AS nodes,
            all_rels AS relationships
        """

        return query

    def _parse_results(
        self,
        records: List[Dict[str, Any]],
        start_node_ids: List[str],
        config: TraversalConfig,
    ) -> TraversalResult:
        """Parse APOC query results into TraversalResult.

        Args:
            records: Raw Neo4j records
            start_node_ids: Original starting node IDs
            config: Traversal configuration

        Returns:
            Parsed TraversalResult
        """
        nodes: List[TraversedNode] = []
        edges: List[TraversedEdge] = []
        seen_node_ids = set()
        start_set = set(start_node_ids)

        for record in records:
            # Parse nodes
            for node_data in record.get("nodes", []):
                node_id = node_data.get("node_id")
                if not node_id or (config.deduplicate and node_id in seen_node_ids):
                    continue

                seen_node_ids.add(node_id)

                # Parse properties from JSON string if needed
                properties = node_data.get("properties", {})
                if isinstance(properties, str):
                    try:
                        properties = json.loads(properties)
                    except json.JSONDecodeError:
                        properties = {}

                # Determine depth (0 for start nodes, 1+ for others)
                depth = 0 if node_id in start_set else 1

                node = TraversedNode(
                    node_id=node_id,
                    node_type=node_data.get("node_type", "Unknown"),
                    name=node_data.get("name") or properties.get("name"),
                    properties=properties if config.include_properties else {},
                    depth=depth,
                    source_node_id=start_node_ids[0] if start_node_ids else None,
                )

                # Skip start nodes if not included
                if not config.include_start_nodes and node_id in start_set:
                    continue

                nodes.append(node)

            # Parse relationships
            for rel_data in record.get("relationships", []):
                edge = TraversedEdge(
                    from_node_id=rel_data.get("from_id", ""),
                    to_node_id=rel_data.get("to_id", ""),
                    relationship_type=rel_data.get("rel_type", "RELATED_TO"),
                    properties=rel_data.get("properties", {}),
                )
                edges.append(edge)

        return TraversalResult(
            nodes=nodes,
            edges=edges,
            start_node_ids=start_node_ids,
            config=config,
            stats={
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "start_nodes_count": len(start_node_ids),
                "strategy": self.name,
            },
        )

    async def _fallback_cypher_traverse(
        self,
        driver: Neo4jDriver,
        node_ids: List[str],
        organization_id: UUID,
        config: TraversalConfig,
    ) -> TraversalResult:
        """Fallback to native Cypher if APOC not available.

        Uses variable-length path patterns for traversal.
        Less efficient than APOC but doesn't require plugins.

        Args:
            driver: Neo4j driver
            node_ids: Starting node IDs
            organization_id: Organization ID
            config: Traversal configuration

        Returns:
            TraversalResult
        """
        logger.info("[APOCStrategy] Using Cypher fallback traversal")

        # Build direction pattern
        if config.direction == TraversalDirection.OUTGOING:
            rel_pattern = f"-[r*1..{config.max_depth}]->"
        elif config.direction == TraversalDirection.INCOMING:
            rel_pattern = f"<-[r*1..{config.max_depth}]-"
        else:
            rel_pattern = f"-[r*1..{config.max_depth}]-"

        # Build relationship type filter
        if config.relationship_types:
            types = "|".join(config.relationship_types)
            rel_pattern = rel_pattern.replace("[r*", f"[r:{types}*")

        query = f"""
        MATCH (start:GraphNode)
        WHERE start.node_id IN $node_ids
          AND start.organization_id = $org_id

        OPTIONAL MATCH path = (start){rel_pattern}(connected:GraphNode)
        WHERE connected.organization_id = $org_id

        WITH start, connected, relationships(path) AS rels
        LIMIT $node_limit

        RETURN
            collect(DISTINCT {{
                node_id: start.node_id,
                node_type: start.node_type,
                name: start.ft_name,
                properties: start.properties,
                is_start: true
            }}) + collect(DISTINCT {{
                node_id: connected.node_id,
                node_type: connected.node_type,
                name: connected.ft_name,
                properties: connected.properties,
                is_start: false
            }}) AS nodes,
            collect(DISTINCT {{
                from_id: startNode(rels[0]).node_id,
                to_id: endNode(rels[0]).node_id,
                rel_type: type(rels[0])
            }}) AS relationships
        """

        params = {
            "node_ids": node_ids,
            "org_id": str(organization_id),
            "node_limit": config.node_limit,
        }

        records = await driver.execute_read(query, params)
        return self._parse_results(records, node_ids, config)

    async def close(self) -> None:
        """Close driver if we own it."""
        if self._owns_driver and self._driver:
            await self._driver.close()
            self._driver = None
