"""PPR-based traversal strategy: PageRank from seeds, elbow filter, induced subgraph, WCC, spanning tree."""
import json
import uuid
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID

from contextd.core.logging import LoggerConfigurator
from contextd.platform.graph.config import get_graph_config
from contextd.platform.graph.driver.neo4j_driver import Neo4jDriver

from ._base import TraversalResult, TraversalStrategy, TraversedEdge, TraversedNode
from .config import TraversalConfig
from .g_retriever_strategy import (
    _compute_depths,
    _fetch_graph_stats,
    _filter_existing_nodes,
)
from .gds_ppr import create_ppr_graph, drop_ppr_graph, run_ppr_stream

logger = LoggerConfigurator.configure_logger(__name__)


def _elbow_cutoff_index(scores_desc: List[float]) -> int:
    """Return index for elbow: point farthest from chord (Kneedle-style) on min-max normalised curve."""
    n = len(scores_desc)
    if n <= 1:
        return 0
    min_s, max_s = min(scores_desc), max(scores_desc)
    span = max_s - min_s
    if span == 0:
        return 0
    # Min-max normalise: x in [0, 1], y in [0, 1] (scores descending so first = 1, last = 0)
    x0, y0 = 0.0, 1.0
    x1, y1 = 1.0, 0.0
    dx = x1 - x0
    dy = y1 - y0
    norm_sq = dx * dx + dy * dy
    if norm_sq == 0:
        return 0
    max_dist = -1.0
    best_i = 0
    for i in range(n):
        x_norm = i / (n - 1) if n > 1 else 0.0
        y_norm = (scores_desc[i] - min_s) / span
        px = x_norm - x0
        py = y_norm - y0
        dist_sq = (dx * py - dy * px) ** 2 / norm_sq
        if dist_sq > max_dist:
            max_dist = dist_sq
            best_i = i
    return best_i


def _select_ppr_nodes(
    ppr_results: List[Tuple[str, float]],
    seed_node_ids: Set[str],
    use_elbow: bool,
    top_k: int,
    score_threshold: Optional[float],
) -> List[str]:
    """Select nodes from PPR scores: elbow, top_k, or score_threshold; always include seeds."""
    if not ppr_results:
        return list(seed_node_ids)
    # Sort by score descending (node_id, score)
    sorted_results = sorted(ppr_results, key=lambda x: (x[1], x[0]), reverse=True)
    scores_only = [s for _, s in sorted_results]
    if score_threshold is not None:
        selected = [node_id for node_id, score in sorted_results if score >= score_threshold]
    elif use_elbow:
        elbow_i = _elbow_cutoff_index(scores_only)
        cap = min(elbow_i + 1, top_k)  # elbow selection capped by top_k
        selected = [node_id for node_id, _ in sorted_results[:cap]]
    else:
        selected = [node_id for node_id, _ in sorted_results[:top_k]]
    selected_set = set(selected) | seed_node_ids
    return list(selected_set)


def _union_find_components(edges: List[Tuple[str, str]]) -> Dict[str, int]:
    """Return node_id -> component_id (0, 1, ...) using Union-Find on edge list."""
    parent: Dict[str, str] = {}

    def find(x: str) -> str:
        if x not in parent:
            parent[x] = x
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(x: str, y: str) -> None:
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    for u, v in edges:
        union(u, v)
    # Assign component ids
    comp_id: Dict[str, int] = {}
    for node in parent:
        root = find(node)
        if root not in comp_id:
            comp_id[root] = len(comp_id)
    return {node: comp_id[find(node)] for node in parent}


def _spanning_tree_edges(
    component_nodes: Set[str],
    edges: List[Tuple[str, str, str]],
) -> List[Tuple[str, str, str]]:
    """BFS from first node in component; return tree edges (from_id, to_id, rel_type)."""
    if not component_nodes or not edges:
        return []
    adj: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for u, v, t in edges:
        if u in component_nodes and v in component_nodes:
            adj[u].append((v, t))
            adj[v].append((u, t))
    start = next(iter(component_nodes))
    seen: Set[str] = {start}
    tree_edges: List[Tuple[str, str, str]] = []
    queue: List[str] = [start]
    while queue:
        cur = queue.pop(0)
        for neighbor, rel_type in adj.get(cur, []):
            if neighbor not in seen:
                seen.add(neighbor)
                tree_edges.append((cur, neighbor, rel_type))
                queue.append(neighbor)
    return tree_edges


class PPRTraversalStrategy(TraversalStrategy):
    """PPR-based traversal: PageRank from seeds -> filter (elbow/top_k) -> induced subgraph -> WCC -> spanning tree per component."""

    def __init__(self, driver: Optional[Neo4jDriver] = None):
        self._driver = driver
        self._owns_driver = driver is None

    @property
    def name(self) -> str:
        return "ppr"

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
            raise RuntimeError("GDS is disabled. Set GRAPH_GDS_ENABLED=true to use ppr.")

        driver = await self._ensure_driver()
        if neo4j_database:
            driver = driver.for_database(neo4j_database)
        seed_set = set(node_ids)
        existing_seeds = await _filter_existing_nodes(
            driver=driver,
            organization_id=organization_id,
            node_labels=graph_config.ppr_node_labels,
            node_ids=node_ids,
        )
        if not existing_seeds:
            node_stats = await _fetch_graph_stats(
                driver=driver,
                organization_id=organization_id,
                node_labels=graph_config.ppr_node_labels,
                rel_types=graph_config.ppr_rel_types,
                candidate_node_ids=node_ids,
            )
            logger.warning(
                "[PPR] No graph nodes found for seeds. node_labels=%s rel_types=%s",
                graph_config.ppr_node_labels,
                graph_config.ppr_rel_types,
            )
            return TraversalResult(
                start_node_ids=[],
                config=config,
                stats={"strategy": self.name, **node_stats},
            )

        graph_name = f"{graph_config.gds_graph_name}_ppr_{organization_id.hex}_{uuid.uuid4().hex[:8]}"
        try:
            await create_ppr_graph(
                driver=driver,
                graph_name=graph_name,
                organization_id=organization_id,
                node_labels=graph_config.ppr_node_labels,
                rel_types=graph_config.ppr_rel_types,
            )
            ppr_results = await run_ppr_stream(
                driver=driver,
                graph_name=graph_name,
                seed_node_ids=existing_seeds,
                organization_id=organization_id,
                node_labels=graph_config.ppr_node_labels,
                damping_factor=graph_config.ppr_damping_factor,
                max_iterations=graph_config.ppr_max_iterations,
                rel_types=graph_config.ppr_rel_types,
            )
        finally:
            try:
                await drop_ppr_graph(driver, graph_name)
            except Exception as e:
                logger.warning("[PPR] Failed to drop graph %s: %s", graph_name, e)

        selected = _select_ppr_nodes(
            ppr_results,
            seed_node_ids=seed_set,
            use_elbow=graph_config.ppr_use_elbow,
            top_k=graph_config.ppr_top_k,
            score_threshold=graph_config.ppr_score_threshold,
        )
        if not selected:
            return TraversalResult(
                start_node_ids=node_ids,
                config=config,
                stats={"strategy": self.name, "selected_count": 0},
            )

        induced_edges = await self._fetch_induced_edges(
            driver=driver,
            organization_id=organization_id,
            node_labels=graph_config.ppr_node_labels,
            rel_types=graph_config.ppr_rel_types,
            selected_ids=selected,
        )
        edge_tuples = [(e["from_id"], e["to_id"], e["rel_type"]) for e in induced_edges]
        edge_tuples_undirected = [(u, v) for u, v, _ in edge_tuples]
        components = _union_find_components(edge_tuples_undirected)
        comp_to_nodes: Dict[int, Set[str]] = defaultdict(set)
        next_cid = 0
        for nid in selected:
            cid = components.get(nid)
            if cid is None:
                cid = next_cid
                next_cid += 1
            comp_to_nodes[cid].add(nid)

        tree_edges: List[Tuple[str, str, str]] = []
        for _cid, nodes in comp_to_nodes.items():
            tree_edges.extend(_spanning_tree_edges(set(nodes), edge_tuples))

        nodes_result, edges_result = await self._build_result(
            driver=driver,
            organization_id=organization_id,
            node_labels=graph_config.ppr_node_labels,
            node_ids=selected,
            tree_edges=tree_edges,
            start_node_ids=node_ids,
            config=config,
        )
        return TraversalResult(
            nodes=nodes_result,
            edges=edges_result,
            start_node_ids=node_ids,
            config=config,
            stats={
                "strategy": self.name,
                "total_nodes": len(nodes_result),
                "total_edges": len(edges_result),
                "ppr_candidates": len(ppr_results),
                "selected_count": len(selected),
                "component_count": len(comp_to_nodes),
            },
        )

    async def _fetch_induced_edges(
        self,
        driver: Neo4jDriver,
        organization_id: UUID,
        node_labels: List[str],
        rel_types: List[str],
        selected_ids: List[str],
    ) -> List[Dict[str, Any]]:
        """Return edges (from_id, to_id, rel_type) in induced subgraph on selected_ids."""
        query = """
        MATCH (n)-[r]->(m)
        WHERE n.organization_id = $org_id
          AND m.organization_id = $org_id
          AND (size($node_labels) = 0 OR any(l IN labels(n) WHERE l IN $node_labels))
          AND (size($node_labels) = 0 OR any(l IN labels(m) WHERE l IN $node_labels))
          AND (size($rel_types) = 0 OR type(r) IN $rel_types)
          AND n.node_id IN $selected_ids
          AND m.node_id IN $selected_ids
        RETURN n.node_id AS from_id, m.node_id AS to_id, type(r) AS rel_type
        """
        records = await driver.execute_read(
            query,
            {
                "org_id": str(organization_id),
                "node_labels": node_labels,
                "rel_types": rel_types,  # empty list = all relationship types (size($rel_types)=0)
                "selected_ids": selected_ids,
            },
        )
        return [dict(r) for r in records]

    async def _build_result(
        self,
        driver: Neo4jDriver,
        organization_id: UUID,
        node_labels: List[str],
        node_ids: List[str],
        tree_edges: List[Tuple[str, str, str]],
        start_node_ids: List[str],
        config: TraversalConfig,
    ) -> Tuple[List[TraversedNode], List[TraversedEdge]]:
        """Fetch node properties from Neo4j and build TraversedNode/TraversedEdge lists."""
        if not node_ids:
            return [], []
        query = """
        MATCH (n)
        WHERE n.organization_id = $org_id
          AND (size($node_labels) = 0 OR any(l IN labels(n) WHERE l IN $node_labels))
          AND n.node_id IN $node_ids
        RETURN n.node_id AS node_id, n.node_type AS node_type,
               n.ft_name AS name, n.properties AS properties
        """
        records = await driver.execute_read(
            query,
            {"org_id": str(organization_id), "node_labels": node_labels, "node_ids": node_ids},
        )
        node_type_by_id: Dict[str, str] = {}
        name_by_id: Dict[str, Optional[str]] = {}
        props_by_id: Dict[str, Dict[str, Any]] = {}
        for r in records:
            nid = r.get("node_id")
            if not nid:
                continue
            node_type_by_id[nid] = r.get("node_type") or (r.get("labels") or ["Unknown"])[0]
            name_by_id[nid] = r.get("name")
            raw = r.get("properties") or {}
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except json.JSONDecodeError:
                    raw = {}
            props_by_id[nid] = raw if config.include_properties else {}

        start_set = set(start_node_ids) if start_node_ids else set(node_ids[:1])
        nodes_list: List[TraversedNode] = []
        seen_nodes: Set[str] = set()
        for nid in node_ids:
            if config.deduplicate and nid in seen_nodes:
                continue
            seen_nodes.add(nid)
            if not config.include_start_nodes and nid in start_set:
                continue
            nodes_list.append(
                TraversedNode(
                    node_id=nid,
                    node_type=node_type_by_id.get(nid, "Unknown"),
                    name=name_by_id.get(nid),
                    properties=props_by_id.get(nid, {}),
                    depth=0,
                    source_node_id=node_ids[0] if node_ids else None,
                )
            )
        edges_list: List[TraversedEdge] = []
        seen_edges: Set[Tuple[str, str, str]] = set()
        for from_id, to_id, rel_type in tree_edges:
            key = (from_id, to_id, rel_type)
            if config.deduplicate and key in seen_edges:
                continue
            seen_edges.add(key)
            edges_list.append(
                TraversedEdge(
                    from_node_id=from_id,
                    to_node_id=to_id,
                    relationship_type=rel_type,
                    properties={},
                    direction="outgoing",
                )
            )
        depths = _compute_depths(start_node_ids, edges_list)
        for node in nodes_list:
            node.depth = depths.get(node.node_id, 0)
        if config.node_limit and len(nodes_list) > config.node_limit:
            nodes_list = sorted(nodes_list, key=lambda n: (n.depth, n.node_id))[: config.node_limit]
            allowed = {n.node_id for n in nodes_list}
            edges_list = [
                e for e in edges_list
                if e.from_node_id in allowed and e.to_node_id in allowed
            ]
        return nodes_list, edges_list

    async def close(self) -> None:
        if self._driver and self._owns_driver:
            await self._driver.close()
            self._driver = None
