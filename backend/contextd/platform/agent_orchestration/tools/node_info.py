"""Node hydration tool used by GLM runtime and decision trace enrichment."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List
from uuid import UUID

from contextd.api.context import ApiContext

logger = logging.getLogger(__name__)


def _parse_props(raw: Any) -> Dict[str, Any]:
    """Parse Neo4j node properties stored as dicts or JSON strings."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}


async def node_info(
    node_ids: List[str],
    organization_id: UUID,
    ctx: ApiContext,
    *,
    readable_collection_id: str = "",
) -> List[Dict[str, Any]]:
    """Fetch node properties plus one-hop neighbors for the given node IDs."""
    if not node_ids:
        return []

    from contextd.platform.graph.driver.neo4j_driver import convert_neo4j_types
    from contextd.platform.graph.factory import get_graph_driver

    driver = await get_graph_driver()
    neo4j_database = None
    if readable_collection_id:
        neo4j_database = await driver.ensure_context_database(
            organization_id,
            readable_collection_id,
        )
    query = """
    UNWIND $node_ids AS nid
    MATCH (n:GraphNode {node_id: nid, organization_id: $organization_id})
    OPTIONAL MATCH (n)-[r]-(m:GraphNode)
    WHERE m.organization_id = $organization_id
    WITH n, nid,
         collect(DISTINCT {
             relationship_type: type(r),
             direction: CASE WHEN startNode(r) = n THEN 'outgoing' ELSE 'incoming' END,
             neighbor_node_id: m.node_id,
             neighbor_node_type: m.node_type,
             neighbor_properties: m.properties
         }) AS neighbors
    RETURN nid AS node_id,
           n.node_type AS node_type,
           n.properties AS properties,
           [x IN neighbors WHERE x.neighbor_node_id IS NOT NULL | x] AS neighbors
    """
    params: Dict[str, Any] = {
        "node_ids": node_ids,
        "organization_id": str(organization_id),
    }
    try:
        records = await driver.execute_read(query, params, database=neo4j_database)
    except Exception as e:
        logger.warning("NodeInfo query failed: %s", e)
        return []

    out: List[Dict[str, Any]] = []
    for record in records:
        record = convert_neo4j_types(record)
        props = _parse_props(record.get("properties"))
        neighbors = []
        for neighbor in record.get("neighbors") or []:
            neighbor_props = _parse_props(neighbor.get("neighbor_properties"))
            neighbors.append(
                {
                    "relationship_type": neighbor.get("relationship_type"),
                    "direction": neighbor.get("direction"),
                    "neighbor_node_id": neighbor.get("neighbor_node_id"),
                    "neighbor_node_type": neighbor.get("neighbor_node_type"),
                    "neighbor_name": neighbor_props.get("name"),
                    "neighbor_properties": neighbor_props,
                }
            )
        out.append(
            {
                "node_id": record.get("node_id"),
                "node_type": record.get("node_type") or "Unknown",
                "name": props.get("name"),
                "properties": props,
                "neighbors": neighbors,
            }
        )
    return out
