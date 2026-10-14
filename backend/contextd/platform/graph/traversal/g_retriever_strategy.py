"""G-Retriever traversal strategy using PCST via Neo4j GDS."""
import json
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from contextd.core.logging import LoggerConfigurator
from contextd.platform.graph.config import get_graph_config
from contextd.platform.graph.driver.neo4j_driver import Neo4jDriver

from ._base import TraversalResult, TraversalStrategy, TraversedEdge, TraversedNode
from .config import TraversalConfig
from .gds_pcst import create_pcst_graph, drop_graph, run_pcst

logger = LoggerConfigurator.configure_logger(__name__)


class PCSTTraversalStrategy(TraversalStrategy):
    """PCST-based subgraph retrieval using Neo4j GDS."""

    def __init__(self, driver: Optional[Neo4jDriver] = None):
        self._driver = driver
        self._owns_driver = driver is None

    @property
    def name(self) -> str:
        return "pcst"

    async def _ensure_driver(self) -> Neo4jDriver:
        if self._driver is None:
            graph_config = get_graph_config()
            self._driver = Neo4jDriver(
                uri=graph_config.neo4j_uri,
                user=graph_config.neo4j_user,
                password=graph_config.neo4j_password,
                database=graph_config.neo4j_database,
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
        if not node_ids:
            return TraversalResult(start_node_ids=[], config=config)

        graph_config = get_graph_config()
        if not graph_config.gds_enabled:
            raise RuntimeError("GDS is disabled. Set GRAPH_GDS_ENABLED=true to use pcst.")

        driver = await self._ensure_driver()
        if neo4j_database:
            driver = driver.for_database(neo4j_database)

        prize_scale = graph_config.pcst_prize_scale
        logger.info(
            "[PCST] Config: prize_scale=%s node_labels=%s rel_types=%s",
            prize_scale,
            graph_config.pcst_node_labels,
            graph_config.pcst_rel_types,
        )
        candidate_node_ids = list(dict.fromkeys(node_ids))
        prize_map: Dict[str, float] = {
            node_id: 1.0 * prize_scale for node_id in candidate_node_ids
        }

        existing_node_ids = await _filter_existing_nodes(
            driver=driver,
            organization_id=organization_id,
            node_labels=graph_config.pcst_node_labels,
            node_ids=candidate_node_ids,
        )
        node_stats = await _fetch_graph_stats(
            driver=driver,
            organization_id=organization_id,
            node_labels=graph_config.pcst_node_labels,
            rel_types=graph_config.pcst_rel_types,
            candidate_node_ids=candidate_node_ids,
        )
        logger.info(
            "[PCST] Graph stats: node_count=%s rel_count=%s candidate_matches=%s "
            "candidate_total=%s",
            node_stats.get("node_count"),
            node_stats.get("rel_count"),
            node_stats.get("candidate_matches"),
            len(candidate_node_ids),
        )
        if not existing_node_ids:
            logger.warning(
                "[PCST] No matching graph nodes for prizes. "
                "label_count=%s rel_count=%s candidate_matches=%s "
                "Check labels/relationship types or ensure node_ids exist in Neo4j.",
                node_stats.get("node_count"),
                node_stats.get("rel_count"),
                node_stats.get("candidate_matches"),
            )
            return TraversalResult(
                start_node_ids=[],
                config=config,
                stats={
                    "strategy": self.name,
                    **node_stats,
                },
            )

        prize_map = {node_id: prize for node_id, prize in prize_map.items() if node_id in existing_node_ids}
        candidate_node_ids = [node_id for node_id in candidate_node_ids if node_id in existing_node_ids]
        positive_prizes = sum(1 for prize in prize_map.values() if prize > 0.0)
        logger.info(
            "[PCST] Prize stats: total=%s positive=%s labels=%s rel_types=%s",
            len(prize_map),
            positive_prizes,
            graph_config.pcst_node_labels,
            graph_config.pcst_rel_types,
        )

        graph_name = f"{graph_config.gds_graph_name}_{organization_id.hex}_{uuid4().hex[:8]}"
        prize_property = graph_config.pcst_prize_property
        weight_property = "weight"

        try:
            await create_pcst_graph(
                driver=driver,
                graph_name=graph_name,
                organization_id=organization_id,
                node_labels=graph_config.pcst_node_labels,
                rel_types=graph_config.pcst_rel_types,
                prize_map=prize_map,
                prize_property=prize_property,
                edge_weight_property=graph_config.pcst_edge_weight_property,
            )

            results = await run_pcst(
                driver=driver,
                graph_name=graph_name,
                prize_property=prize_property,
                weight_property=weight_property,
                relationship_types=graph_config.pcst_rel_types,
                organization_id=organization_id,
            )
            logger.info(
                "[PCST] Results: nodes=%s edges=%s",
                len(results.get("nodes", [])),
                len(results.get("relationships", [])),
            )
            if results.get("nodes"):
                logger.info(
                    "[PCST] Sample node: %s",
                    results["nodes"][0],
                )
        finally:
            try:
                await drop_graph(driver, graph_name)
            except Exception as e:
                logger.warning("[PCST] Failed to drop graph %s: %s", graph_name, e)

        nodes, edges = self._parse_results(
            results.get("nodes", []),
            results.get("relationships", []),
            candidate_node_ids,
            config,
        )

        return TraversalResult(
            nodes=nodes,
            edges=edges,
            start_node_ids=candidate_node_ids,
            config=config,
            stats={
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "start_nodes_count": len(candidate_node_ids),
                "strategy": self.name,
                "candidate_count": len(prize_map),
                "graph_name": graph_name,
                "query_embedding_used": False,
                **node_stats,
            },
        )

    def _parse_results(
        self,
        node_records: List[Dict[str, Any]],
        rel_records: List[Dict[str, Any]],
        start_node_ids: List[str],
        config: TraversalConfig,
    ) -> tuple[List[TraversedNode], List[TraversedEdge]]:
        nodes: List[TraversedNode] = []
        edges: List[TraversedEdge] = []
        seen_node_ids = set()
        seen_edges = set()
        start_set = set(start_node_ids)

        for node_data in node_records:
            node_id = node_data.get("node_id")
            if not node_id or (config.deduplicate and node_id in seen_node_ids):
                continue

            seen_node_ids.add(node_id)
            properties = node_data.get("properties", {})
            if isinstance(properties, str):
                try:
                    properties = json.loads(properties)
                except json.JSONDecodeError:
                    properties = {}

            node = TraversedNode(
                node_id=node_id,
                node_type=node_data.get("node_type", "Unknown"),
                name=node_data.get("name") or properties.get("name"),
                properties=properties if config.include_properties else {},
                depth=0,
                source_node_id=start_node_ids[0] if start_node_ids else None,
            )

            if not config.include_start_nodes and node_id in start_set:
                continue
            nodes.append(node)

        for rel_data in rel_records:
            from_id = rel_data.get("from_id")
            to_id = rel_data.get("to_id")
            rel_type = rel_data.get("rel_type")
            if not from_id or not to_id or not rel_type:
                continue

            edge_key = (from_id, to_id, rel_type)
            if config.deduplicate and edge_key in seen_edges:
                continue

            seen_edges.add(edge_key)
            edges.append(
                TraversedEdge(
                    from_node_id=from_id,
                    to_node_id=to_id,
                    relationship_type=rel_type,
                    properties=rel_data.get("properties", {}),
                    direction="outgoing",
                )
            )

        depths = _compute_depths(start_node_ids, edges)
        for node in nodes:
            node.depth = depths.get(node.node_id, 0)

        if config.node_limit and len(nodes) > config.node_limit:
            nodes = sorted(nodes, key=lambda n: (n.depth, n.node_id))[: config.node_limit]
            allowed_ids = {node.node_id for node in nodes}
            edges = [
                edge
                for edge in edges
                if edge.from_node_id in allowed_ids and edge.to_node_id in allowed_ids
            ]

        return nodes, edges

    async def close(self) -> None:
        if self._driver and self._owns_driver:
            await self._driver.close()
            self._driver = None


def _compute_depths(
    start_node_ids: List[str], edges: List[TraversedEdge]
) -> Dict[str, int]:
    if not start_node_ids:
        return {}

    adjacency: Dict[str, List[str]] = {}
    for edge in edges:
        adjacency.setdefault(edge.from_node_id, []).append(edge.to_node_id)
        adjacency.setdefault(edge.to_node_id, []).append(edge.from_node_id)

    depths: Dict[str, int] = {}
    queue: List[str] = []
    for node_id in start_node_ids:
        depths[node_id] = 0
        queue.append(node_id)

    while queue:
        current = queue.pop(0)
        for neighbor in adjacency.get(current, []):
            if neighbor not in depths:
                depths[neighbor] = depths[current] + 1
                queue.append(neighbor)

    return depths


async def _filter_existing_nodes(
    driver: Neo4jDriver,
    organization_id: UUID,
    node_labels: List[str],
    node_ids: List[str],
) -> List[str]:
    if not node_ids:
        return []
    query = """
    MATCH (n)
    WHERE n.organization_id = $org_id
      AND (size($node_labels) = 0 OR any(l IN labels(n) WHERE l IN $node_labels))
      AND n.node_id IN $node_ids
    RETURN collect(n.node_id) AS node_ids
    """
    records = await driver.execute_read(
        query,
        {"org_id": str(organization_id), "node_labels": node_labels, "node_ids": node_ids},
    )
    if not records:
        return []
    return records[0].get("node_ids", [])


async def _fetch_graph_stats(
    driver: Neo4jDriver,
    organization_id: UUID,
    node_labels: List[str],
    rel_types: List[str],
    candidate_node_ids: List[str],
) -> Dict[str, int]:
    query = """
    MATCH (n)
    WHERE n.organization_id = $org_id
      AND (size($node_labels) = 0 OR any(l IN labels(n) WHERE l IN $node_labels))
    OPTIONAL MATCH (n)-[r]-(m)
    WHERE m.organization_id = $org_id
      AND (size($node_labels) = 0 OR any(l IN labels(m) WHERE l IN $node_labels))
      AND (size($rel_types) = 0 OR type(r) IN $rel_types)
    WITH count(DISTINCT n) AS node_count, count(DISTINCT r) AS rel_count
    OPTIONAL MATCH (c)
    WHERE c.organization_id = $org_id
      AND (size($node_labels) = 0 OR any(l IN labels(c) WHERE l IN $node_labels))
      AND c.node_id IN $candidate_node_ids
    RETURN node_count, rel_count, count(DISTINCT c) AS candidate_matches
    """
    records = await driver.execute_read(
        query,
        {
            "org_id": str(organization_id),
            "node_labels": node_labels,
            "rel_types": rel_types,
            "candidate_node_ids": candidate_node_ids,
        },
    )
    if not records:
        return {"node_count": 0, "rel_count": 0, "candidate_matches": 0}
    return {
        "node_count": records[0].get("node_count", 0),
        "rel_count": records[0].get("rel_count", 0),
        "candidate_matches": records[0].get("candidate_matches", 0),
    }
