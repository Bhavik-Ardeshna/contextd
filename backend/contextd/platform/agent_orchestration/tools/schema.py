"""Graph schema sampling tools for business-logic prompt construction."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from contextd.api.context import ApiContext
from contextd.platform.agent_orchestration.tools.cypher import _validate_read_only_cypher

logger = logging.getLogger(__name__)


def _graph_scope_filter(
    use_collection: bool,
    collection_id: Optional[str],
    source_type: Optional[str],
) -> Tuple[str, Dict[str, Any]]:
    """Return Cypher WHERE fragment and params for collection or connector scoping."""
    if use_collection and collection_id:
        fragment = (
            " AND n.properties IS NOT NULL"
            " AND apoc.convert.fromJsonMap(n.properties).collection_id = $collection_id"
        )
        return fragment, {"collection_id": collection_id}
    if source_type:
        fragment = (
            " AND n.properties IS NOT NULL"
            " AND apoc.convert.fromJsonMap(n.properties).source_type = $source_type"
        )
        return fragment, {"source_type": source_type}
    return "", {}


def _properties_from_raw(raw: Any) -> Dict[str, Any]:
    """Normalize Neo4j property payloads stored as dicts or JSON strings."""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    if isinstance(raw, dict):
        return dict(raw)
    return {}


async def get_graph_node_types_and_samples(
    organization_id: UUID,
    source_type: Optional[str] = None,
    ctx: Optional[ApiContext] = None,
    *,
    collection_id: Optional[str] = None,
    samples_per_type: int = 3,
    max_node_types: int = 500,
    use_all_org_node_types: bool = True,
) -> Tuple[List[str], Dict[str, List[Dict[str, Any]]]]:
    """Fetch distinct node_type values and sample rows per type."""
    from contextd.platform.graph.driver.neo4j_driver import convert_neo4j_types
    from contextd.platform.graph.factory import get_graph_driver

    _validate_read_only_cypher("MATCH (n:GraphNode) RETURN n.node_type")
    driver = await get_graph_driver()
    neo4j_database = None
    if collection_id:
        neo4j_database = await driver.ensure_context_database(
            organization_id,
            collection_id,
        )
    org_str = str(organization_id)
    use_collection = bool(collection_id)

    scope_frag, scope_params = _graph_scope_filter(use_collection, collection_id, source_type)
    if use_all_org_node_types and not scope_frag:
        node_types_query = """
        MATCH (n:GraphNode)
        WHERE n.organization_id = $organization_id
          AND n.node_type IS NOT NULL
        RETURN DISTINCT n.node_type AS type
        """
        params: Dict[str, Any] = {"organization_id": org_str}
    else:
        node_types_query = (
            """
        MATCH (n:GraphNode)
        WHERE n.organization_id = $organization_id
          AND n.node_type IS NOT NULL
        """
            + scope_frag
            + """
        RETURN DISTINCT n.node_type AS type
        """
        )
        params = {"organization_id": org_str, **scope_params}

    try:
        node_records = await driver.execute_read(
            node_types_query,
            params,
            database=neo4j_database,
        )
    except Exception as e:
        logger.warning("get_graph_node_types_and_samples (node types) failed: %s", e)
        return ([], {})

    node_types = [
        str(record["type"]).strip()
        for record in convert_neo4j_types(node_records)
        if record.get("type") is not None
    ][:max_node_types]
    if not node_types:
        return ([], {})

    samples_by_node_type: Dict[str, List[Dict[str, Any]]] = {}
    sample_scope_frag, sample_scope_params = _graph_scope_filter(
        use_collection,
        collection_id,
        source_type,
    )
    sample_query = (
        """
    MATCH (n:GraphNode)
    WHERE n.organization_id = $organization_id
      AND n.node_type = $node_type
      AND n.properties IS NOT NULL
    """
        + sample_scope_frag
        + """
    RETURN n.node_id AS node_id, n.node_type AS node_type, n.properties AS properties
    LIMIT $limit
    """
    )
    for node_type in node_types:
        try:
            records = await driver.execute_read(
                sample_query,
                {
                    "organization_id": org_str,
                    "node_type": node_type,
                    "limit": samples_per_type,
                    **sample_scope_params,
                },
                database=neo4j_database,
            )
        except Exception as e:
            logger.warning(
                "get_graph_node_types_and_samples (samples for %s) failed: %s",
                node_type,
                e,
            )
            continue
        rows: List[Dict[str, Any]] = []
        for record in convert_neo4j_types(records):
            row: Dict[str, Any] = {
                "node_id": record.get("node_id"),
                "node_type": record.get("node_type"),
            }
            row.update(_properties_from_raw(record.get("properties")))
            rows.append(row)
        if rows:
            samples_by_node_type[node_type] = rows
    return (node_types, samples_by_node_type)


def _rows_from_property_records(records: List[Any]) -> List[Dict[str, Any]]:
    """Turn Neo4j records with node_id, node_type, properties into flat rows."""
    from contextd.platform.graph.driver.neo4j_driver import convert_neo4j_types

    rows: List[Dict[str, Any]] = []
    for record in convert_neo4j_types(records):
        row: Dict[str, Any] = {
            "node_id": record.get("node_id"),
            "node_type": record.get("node_type"),
        }
        row.update(_properties_from_raw(record.get("properties")))
        rows.append(row)
    return rows


async def fetch_samples_for_node_type_with_fallback(
    organization_id: UUID,
    node_type: str,
    *,
    collection_id: Optional[str] = None,
    source_type: Optional[str] = None,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """Sample rows for one node_type, trying collection, source, then org-wide."""
    from contextd.platform.graph.factory import get_graph_driver

    driver = await get_graph_driver()
    neo4j_database = None
    if collection_id:
        neo4j_database = await driver.ensure_context_database(
            organization_id,
            collection_id,
        )
    org_str = str(organization_id)
    base = """
    MATCH (n:GraphNode)
    WHERE n.organization_id = $organization_id
      AND n.node_type = $node_type
      AND n.properties IS NOT NULL
    """
    tail = """
    RETURN n.node_id AS node_id, n.node_type AS node_type, n.properties AS properties
    LIMIT $limit
    """
    params_base = {"organization_id": org_str, "node_type": node_type, "limit": limit}

    if collection_id:
        fragment, extra = _graph_scope_filter(True, collection_id, None)
        try:
            records = await driver.execute_read(
                base + fragment + tail,
                {**params_base, **extra},
                database=neo4j_database,
            )
            rows = _rows_from_property_records(records)
            if rows:
                return rows
        except Exception as e:
            logger.warning("fetch_samples collection scope %s: %s", node_type, e)

    if source_type:
        fragment, extra = _graph_scope_filter(False, None, source_type)
        try:
            records = await driver.execute_read(base + fragment + tail, {**params_base, **extra})
            rows = _rows_from_property_records(records)
            if rows:
                return rows
        except Exception as e:
            logger.warning("fetch_samples source_type scope %s: %s", node_type, e)

    try:
        records = await driver.execute_read(base + tail, params_base, database=neo4j_database)
        return _rows_from_property_records(records)
    except Exception as e:
        logger.warning("fetch_samples org-wide %s: %s", node_type, e)
        return []


async def get_graph_relationships_by_node_type(
    organization_id: UUID,
    source_type: Optional[str] = None,
    ctx: Optional[ApiContext] = None,
    *,
    collection_id: Optional[str] = None,
    node_types: Optional[List[str]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Fetch per-node-type relationship summaries from the graph."""
    from contextd.platform.graph.driver.neo4j_driver import convert_neo4j_types
    from contextd.platform.graph.factory import get_graph_driver

    _validate_read_only_cypher(
        "MATCH (a:GraphNode)-[r:RELATES_TO]->(b:GraphNode) RETURN r.relationship_type"
    )
    driver = await get_graph_driver()
    neo4j_database = None
    if collection_id:
        neo4j_database = await driver.ensure_context_database(
            organization_id,
            collection_id,
        )
    org_str = str(organization_id)
    scope_frag, scope_params = _graph_scope_filter(bool(collection_id), collection_id, source_type)
    if not scope_frag:
        return {}

    params = {"organization_id": org_str, **scope_params}
    scope_frag_a = scope_frag.replace("n.", "a.")
    query_out = (
        """
    MATCH (a:GraphNode)-[r:RELATES_TO]->(b:GraphNode)
    WHERE a.organization_id = $organization_id
      AND a.properties IS NOT NULL
    """
        + scope_frag_a
        + """
      AND a.node_type IS NOT NULL
      AND b.node_type IS NOT NULL
    WITH a.node_type AS node_type,
         r.relationship_type AS relationship_type,
         'outgoing' AS direction,
         b.node_type AS neighbor_node_type
    RETURN DISTINCT node_type, relationship_type, direction, neighbor_node_type
    """
    )
    try:
        records_out = await driver.execute_read(query_out, params, database=neo4j_database)
    except Exception as e:
        logger.warning("get_graph_relationships_by_node_type (outgoing) failed: %s", e)
        records_out = []

    query_in = (
        """
    MATCH (a:GraphNode)<-[r:RELATES_TO]-(b:GraphNode)
    WHERE a.organization_id = $organization_id
      AND a.properties IS NOT NULL
    """
        + scope_frag_a
        + """
      AND a.node_type IS NOT NULL
      AND b.node_type IS NOT NULL
    WITH a.node_type AS node_type,
         r.relationship_type AS relationship_type,
         'incoming' AS direction,
         b.node_type AS neighbor_node_type
    RETURN DISTINCT node_type, relationship_type, direction, neighbor_node_type
    """
    )
    try:
        records_in = await driver.execute_read(query_in, params, database=neo4j_database)
    except Exception as e:
        logger.warning("get_graph_relationships_by_node_type (incoming) failed: %s", e)
        records_in = []

    result: Dict[str, List[Dict[str, Any]]] = {}
    seen: Dict[str, set] = {}
    for record in convert_neo4j_types(records_out) + convert_neo4j_types(records_in):
        node_type = record.get("node_type")
        if node_type is None:
            continue
        node_type = str(node_type).strip()
        if node_types is not None and node_type not in node_types:
            continue
        rel_type = record.get("relationship_type") or "RELATES_TO"
        direction = record.get("direction") or "outgoing"
        neighbor = record.get("neighbor_node_type")
        if neighbor is None:
            continue
        neighbor = str(neighbor).strip()
        key = (node_type, str(rel_type).strip(), str(direction).strip(), neighbor)
        if node_type not in seen:
            seen[node_type] = set()
        if key in seen[node_type]:
            continue
        seen[node_type].add(key)
        if node_type not in result:
            result[node_type] = []
        result[node_type].append(
            {
                "relationship_type": str(rel_type).strip(),
                "direction": str(direction).strip(),
                "neighbor_node_type": neighbor,
            }
        )
    return result
