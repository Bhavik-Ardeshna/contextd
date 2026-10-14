"""Helpers for Prize-Collecting Steiner Tree (PCST) in Neo4j GDS."""
import logging
from typing import Dict, List, Optional
from uuid import UUID

from contextd.platform.graph.driver.neo4j_driver import Neo4jDriver

logger = logging.getLogger(__name__)


def _build_label_filter(label_param: str = "$node_labels") -> str:
    return f"(size({label_param}) = 0 OR any(l IN labels(n) WHERE l IN {label_param}))"


def _build_label_filter_for_node(var: str, label_param: str = "$node_labels") -> str:
    return f"(size({label_param}) = 0 OR any(l IN labels({var}) WHERE l IN {label_param}))"


def _build_rel_filter(rel_param: str = "$rel_types") -> str:
    return f"(size({rel_param}) = 0 OR type(r) IN {rel_param})"


async def graph_exists(driver: Neo4jDriver, graph_name: str) -> bool:
    """Check if a GDS graph exists in the catalog."""
    query = "CALL gds.graph.exists($graph_name) YIELD exists RETURN exists"
    records = await driver.execute_read(query, {"graph_name": graph_name})
    if not records:
        return False
    return bool(records[0].get("exists"))


async def create_pcst_graph(
    driver: Neo4jDriver,
    graph_name: str,
    organization_id: UUID,
    node_labels: List[str],
    rel_types: List[str],
    prize_map: Dict[str, float],
    prize_property: str,
    edge_weight_property: Optional[str],
) -> None:
    """Create an in-memory graph with computed prize values."""
    weight_expr = "1.0"
    if edge_weight_property:
        weight_expr = "coalesce(r[parameters.edge_weight_property], 1.0)"

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
            sourceNodeProperties: {{
                {prize_property}: coalesce(parameters.prize_map[n.node_id], 0.0)
            }},
            targetNodeProperties: CASE
                WHEN m IS NULL THEN {{}}
                ELSE {{
                    {prize_property}: coalesce(parameters.prize_map[m.node_id], 0.0)
                }}
            END,
            relationshipType: type(r),
            relationshipProperties: CASE
                WHEN r IS NULL THEN {{}}
                ELSE {{ weight: {weight_expr} }}
            END
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
            "prize_map": prize_map,
            "edge_weight_property": edge_weight_property,
        },
    }

    await driver.execute_write(query, params)
    logger.debug("[PCST] Created GDS graph %s", graph_name)


async def drop_graph(driver: Neo4jDriver, graph_name: str) -> None:
    """Drop a GDS graph from the catalog."""
    query = "CALL gds.graph.drop($graph_name, false) YIELD graphName"
    await driver.execute_write(query, {"graph_name": graph_name})
    logger.debug("[PCST] Dropped GDS graph %s", graph_name)


async def run_pcst(
    driver: Neo4jDriver,
    graph_name: str,
    prize_property: str,
    weight_property: str,
    relationship_types: List[str],
    organization_id: UUID,
) -> Dict[str, List[Dict]]:
    """Run PCST and return nodes/relationships as dictionaries."""
    resolved_relationship_types = relationship_types or ["*"]
    query = """
    CALL gds.prizeSteinerTree.stream(
        $graph_name,
        {
            prizeProperty: $prize_property,
            relationshipWeightProperty: $weight_property,
            relationshipTypes: $relationship_types
        }
    )
    YIELD nodeId, parentId, weight
    WITH nodeId, parentId
    WITH gds.util.asNode(nodeId) AS node,
         CASE
            WHEN parentId IS NULL OR parentId = nodeId THEN NULL
            ELSE gds.util.asNode(parentId)
         END AS parent
    OPTIONAL MATCH (parent)-[r]-(node)
    WITH node, parent, r
    WHERE node.organization_id = $org_id
      AND (parent IS NULL OR parent.organization_id = $org_id)
    RETURN
        collect(DISTINCT {
            node_id: node.node_id,
            node_type: node.node_type,
            name: node.ft_name,
            properties: node.properties
        }) AS nodes,
        collect(DISTINCT {
            from_id: CASE WHEN parent IS NULL THEN NULL ELSE parent.node_id END,
            to_id: node.node_id,
            rel_type: CASE WHEN r IS NULL THEN NULL ELSE type(r) END,
            properties: CASE WHEN r IS NULL THEN {} ELSE properties(r) END
        }) AS relationships
    """

    records = await driver.execute_read(
        query,
        {
            "graph_name": graph_name,
            "prize_property": prize_property,
            "weight_property": weight_property,
            "relationship_types": resolved_relationship_types,
            "org_id": str(organization_id),
        },
    )
    if not records:
        return {"nodes": [], "relationships": []}
    return {
        "nodes": records[0].get("nodes", []),
        "relationships": records[0].get("relationships", []),
    }
