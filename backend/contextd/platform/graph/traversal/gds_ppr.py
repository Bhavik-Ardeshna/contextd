"""Helpers for Personalized PageRank (PPR) in Neo4j GDS."""
import logging
from typing import List, Tuple
from uuid import UUID

from contextd.platform.graph.driver.neo4j_driver import Neo4jDriver

logger = logging.getLogger(__name__)


def _build_label_filter(label_param: str = "$node_labels") -> str:
    return f"(size({label_param}) = 0 OR any(l IN labels(n) WHERE l IN {label_param}))"


def _build_label_filter_for_node(var: str, label_param: str = "$node_labels") -> str:
    return f"(size({label_param}) = 0 OR any(l IN labels({var}) WHERE l IN {label_param}))"


def _build_rel_filter(rel_param: str = "$rel_types") -> str:
    return f"(size({rel_param}) = 0 OR type(r) IN {rel_param})"


async def create_ppr_graph(
    driver: Neo4jDriver,
    graph_name: str,
    organization_id: UUID,
    node_labels: List[str],
    rel_types: List[str],
) -> None:
    """Create an in-memory structure-only graph for PPR (no node properties; GDS does not support String)."""
    query = f"""
    WITH $parameters AS parameters
    MATCH (n)
    WHERE n.organization_id = parameters.org_id
      AND {_build_label_filter("parameters.node_labels")}
    OPTIONAL MATCH (n)-[r]-(m)
    WITH n, r, m, parameters
    WHERE m IS NULL OR (
        m.organization_id = parameters.org_id
        AND {_build_label_filter_for_node("m", "parameters.node_labels")}
        AND {_build_rel_filter("parameters.rel_types")}
    )
    WITH gds.graph.project(
        $graph_name,
        n,
        m,
        {{
            relationshipType: type(r)
        }},
        {{
            undirectedRelationshipTypes: ['*']
        }}
    ) AS g
    RETURN g.graphName AS graphName
    """
    params = {
        "graph_name": graph_name,
        "parameters": {
            "org_id": str(organization_id),
            "node_labels": node_labels,
            "rel_types": rel_types,
        },
    }
    await driver.execute_write(query, params)
    logger.debug("[PPR] Created GDS graph %s", graph_name)


async def run_ppr_stream(
    driver: Neo4jDriver,
    graph_name: str,
    seed_node_ids: List[str],
    organization_id: UUID,
    node_labels: List[str],
    damping_factor: float,
    max_iterations: int,
    rel_types: List[str],
) -> List[Tuple[str, float]]:
    """Run Personalized PageRank from seed nodes; return list of (node_id, score)."""
    if not seed_node_ids:
        return []
    resolved_rel_types = rel_types or ["*"]
    # Match seed nodes in Neo4j and pass as sourceNodes; stream (node_id, score)
    query = """
    MATCH (n)
    WHERE n.organization_id = $org_id
      AND (size($node_labels) = 0 OR any(l IN labels(n) WHERE l IN $node_labels))
      AND n.node_id IN $seed_node_ids
    WITH collect(n) AS seeds
    CALL gds.pageRank.stream(
        $graph_name,
        {
            sourceNodes: seeds,
            dampingFactor: $damping_factor,
            maxIterations: $max_iterations,
            relationshipTypes: $rel_types
        }
    )
    YIELD nodeId, score
    WITH gds.util.asNode(nodeId) AS node, score
    WHERE node.organization_id = $org_id
    RETURN node.node_id AS node_id, score
    """
    records = await driver.execute_read(
        query,
        {
            "graph_name": graph_name,
            "org_id": str(organization_id),
            "node_labels": node_labels,
            "seed_node_ids": seed_node_ids,
            "damping_factor": damping_factor,
            "max_iterations": max_iterations,
            "rel_types": resolved_rel_types,
        },
    )
    return [(r.get("node_id"), float(r.get("score", 0.0))) for r in records if r.get("node_id")]


async def drop_ppr_graph(driver: Neo4jDriver, graph_name: str) -> None:
    """Drop a GDS graph from the catalog."""
    query = "CALL gds.graph.drop($graph_name, false) YIELD graphName"
    await driver.execute_write(query, {"graph_name": graph_name})
    logger.debug("[PPR] Dropped GDS graph %s", graph_name)
