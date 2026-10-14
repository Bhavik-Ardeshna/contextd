"""Trace neighborhood expansion service for graph chat."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

from fastapi import HTTPException

from contextd import crud
from contextd.api.context import ApiContext
from contextd.api.v1.endpoints.graph_chat_schemas import (
    NeighborhoodRequest,
    NeighborhoodResponse,
)
from contextd.db.session import get_db_context


async def expand_trace_neighborhood_for_request(
    readable_id: str,
    request: NeighborhoodRequest,
    ctx: ApiContext,
) -> NeighborhoodResponse:
    """Expand a Decision Trace aggregate row into a real graph neighborhood."""
    async with get_db_context() as db:
        collection = await crud.collection.get_by_readable_id(db, readable_id=readable_id, ctx=ctx)
        if not collection:
            raise HTTPException(status_code=404, detail="Collection not found")

    from contextd.platform.graph.driver.neo4j_driver import convert_neo4j_types
    from contextd.platform.graph.factory import get_graph_driver

    driver = await get_graph_driver()
    neo4j_database = await driver.ensure_context_database(ctx.organization.id, readable_id)
    org_id = str(ctx.organization.id)
    sample_query, sample_params, depth, neighbor_cap = _build_sample_query_plan(
        request,
        organization_id=org_id,
    )

    try:
        sample_records = await driver.execute_read(
            sample_query,
            sample_params,
            database=neo4j_database,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Sample query failed: {exc}") from exc

    samples, sample_ids = _build_samples(sample_records, convert_neo4j_types)
    if not sample_ids:
        return NeighborhoodResponse(samples=[], nodes=[], edges=[], stats={"sample_count": 0})

    expand_query, expand_params = _build_expand_query_plan(
        organization_id=org_id,
        sample_ids=sample_ids,
        depth=depth,
        neighbor_cap=neighbor_cap,
    )
    try:
        expand_records = await driver.execute_read(
            expand_query,
            expand_params,
            database=neo4j_database,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Expand query failed: {exc}") from exc

    if not expand_records:
        return NeighborhoodResponse(
            samples=samples,
            nodes=[],
            edges=[],
            stats={"sample_count": len(samples), "depth": depth},
        )

    row = convert_neo4j_types(expand_records[0])
    return _build_neighborhood_response(
        samples=samples,
        sample_ids=sample_ids,
        row=row,
        depth=depth,
    )


def _build_sample_query_plan(
    request: NeighborhoodRequest,
    *,
    organization_id: str,
) -> Tuple[str, Dict[str, Any], int, int]:
    """Build the safe sample query and bounded expansion settings."""
    depth = max(1, min(request.depth, 3))
    sample_limit = max(1, min(request.sample_limit, 25))
    neighbor_cap = max(1, min(request.neighbor_cap, 500))

    sample_params: Dict[str, Any] = {
        "organization_id": organization_id,
        "node_type": request.node_type,
        "sample_limit": sample_limit,
    }
    where_clauses = [
        "t.organization_id = $organization_id",
        "t.node_type = $node_type",
    ]
    if request.filter_key:
        safe_key = re.sub(r"[^A-Za-z0-9_]", "", request.filter_key)
        if safe_key:
            where_clauses.append(
                f"apoc.convert.fromJsonMap(t.properties).`{safe_key}` = $filter_value"
            )
            sample_params["filter_value"] = request.filter_value

    sample_query = f"""
    MATCH (t:GraphNode)
    WHERE {" AND ".join(where_clauses)}
    RETURN t.node_id AS node_id,
           t.node_type AS node_type,
           t.properties AS properties
    LIMIT $sample_limit
    """
    return sample_query, sample_params, depth, neighbor_cap


def _build_expand_query_plan(
    *,
    organization_id: str,
    sample_ids: List[str],
    depth: int,
    neighbor_cap: int,
) -> Tuple[str, Dict[str, Any]]:
    """Build the bounded neighborhood expansion query."""
    expand_query = f"""
    MATCH (seed:GraphNode)
    WHERE seed.organization_id = $organization_id
      AND seed.node_id IN $seed_ids
    OPTIONAL MATCH path = (seed)-[*1..{depth}]-(m:GraphNode)
    WHERE m.organization_id = $organization_id
    WITH seed, path, m
    WHERE m IS NOT NULL OR path IS NULL
    WITH collect(DISTINCT seed) AS seeds,
         collect(DISTINCT m) AS neighbors,
         collect(DISTINCT path) AS paths
    WITH seeds + neighbors AS all_nodes, paths
    UNWIND all_nodes AS n
    WITH collect(DISTINCT n) AS node_list, paths
    UNWIND paths AS p
    UNWIND relationships(p) AS r
    WITH node_list,
         collect(DISTINCT {{
             source_id: startNode(r).node_id,
             target_id: endNode(r).node_id,
             relationship_type: type(r)
         }}) AS edge_list
    RETURN
      [n IN node_list WHERE n IS NOT NULL | {{
        node_id: n.node_id,
        node_type: n.node_type,
        properties: n.properties
      }}][..$cap] AS nodes,
      edge_list AS edges
    """
    return (
        expand_query,
        {
            "organization_id": organization_id,
            "seed_ids": sample_ids,
            "cap": neighbor_cap,
        },
    )


def _parse_props(raw: Any) -> Dict[str, Any]:
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


def _build_samples(
    sample_records: List[Any],
    convert_neo4j_types: Any,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    samples: List[Dict[str, Any]] = []
    sample_ids: List[str] = []
    for record in sample_records:
        converted = convert_neo4j_types(record)
        props = _parse_props(converted.get("properties"))
        node_id = converted.get("node_id")
        if not node_id:
            continue
        sample_ids.append(node_id)
        samples.append(
            {
                "node_id": node_id,
                "node_type": converted.get("node_type"),
                "name": props.get("name") or props.get("title") or node_id,
                "properties": props,
            }
        )
    return samples, sample_ids


def _clean_trace_properties(props: Dict[str, Any]) -> Dict[str, Any]:
    clean: Dict[str, Any] = {}
    for key, value in (props or {}).items():
        if value is None or value == "" or (isinstance(key, str) and key.startswith("_")):
            continue
        try:
            if isinstance(value, str) and len(value) > 2000:
                continue
            if isinstance(value, (list, dict)) and len(json.dumps(value, default=str)) > 2000:
                continue
        except Exception:
            pass
        clean[key] = value
    return clean


def _build_neighborhood_response(
    *,
    samples: List[Dict[str, Any]],
    sample_ids: List[str],
    row: Dict[str, Any],
    depth: int,
) -> NeighborhoodResponse:
    raw_nodes = row.get("nodes") or []
    raw_edges = row.get("edges") or []

    out_nodes: List[Dict[str, Any]] = []
    allowed_ids: set[str] = set()
    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            continue
        node_id = raw_node.get("node_id")
        if not node_id:
            continue
        allowed_ids.add(node_id)
        clean = _clean_trace_properties(_parse_props(raw_node.get("properties")))
        out_nodes.append(
            {
                "node_id": node_id,
                "node_type": raw_node.get("node_type") or "Unknown",
                "name": clean.get("name") or clean.get("title") or node_id,
                "properties": clean,
                "is_seed": node_id in sample_ids,
            }
        )

    out_edges: List[Dict[str, Any]] = []
    seen_edges: set[tuple[Any, Any, Any]] = set()
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, dict):
            continue
        source_id = raw_edge.get("source_id")
        target_id = raw_edge.get("target_id")
        relationship_type = raw_edge.get("relationship_type")
        if (
            not source_id
            or not target_id
            or source_id not in allowed_ids
            or target_id not in allowed_ids
        ):
            continue
        key = (source_id, target_id, relationship_type)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        out_edges.append(
            {
                "source_id": source_id,
                "target_id": target_id,
                "relationship_type": relationship_type or "RELATES_TO",
            }
        )

    return NeighborhoodResponse(
        samples=samples,
        nodes=out_nodes,
        edges=out_edges,
        stats={
            "sample_count": len(samples),
            "depth": depth,
            "node_count": len(out_nodes),
            "edge_count": len(out_edges),
        },
    )
