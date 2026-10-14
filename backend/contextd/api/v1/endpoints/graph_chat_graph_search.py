"""Graph search endpoint service."""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List

from fastapi import HTTPException

from contextd import crud
from contextd.api.context import ApiContext
from contextd.api.v1.endpoints.graph_chat_retrieval import (
    _parse_connector_ignoring_search,
    _run_graph_search_retrieval,
)
from contextd.api.v1.endpoints.graph_chat_schemas import (
    GraphSearchRequest,
    GraphSearchResponse,
    request_context_tools,
)
from contextd.core.context_intelligence_service import context_intelligence_service
from contextd.db.session import get_db_context


async def search_graph_for_request(
    readable_id: str,
    request: GraphSearchRequest,
    ctx: ApiContext,
) -> GraphSearchResponse:
    """Execute graph search and return nodes, optionally with edges."""
    started_at = time.perf_counter()
    async with get_db_context() as db:
        collection = await crud.collection.get_by_readable_id(db, readable_id=readable_id, ctx=ctx)
        if not collection:
            raise HTTPException(status_code=404, detail="Collection not found")

    phase_timings_ms: Dict[str, int] = {}
    context_tools = request_context_tools(
        explicit=request.context_tools,
        text=request.query,
    )
    max_depth = _effective_depth(request.query, request.max_depth)
    source_type_filter = _parse_connector_ignoring_search(request.query)
    phase_started = time.perf_counter()
    traversal_result, search_results = await _run_graph_search_retrieval(
        readable_id=readable_id,
        query=request.query,
        ctx=ctx,
        search_limit=request.search_limit,
        max_depth=max_depth,
        source_type_filter=source_type_filter,
        collection=collection,
    )
    phase_timings_ms["retrieval"] = max(1, round((time.perf_counter() - phase_started) * 1000))

    to_dict = traversal_result.to_dict() if traversal_result is not None else {"nodes": [], "edges": []}
    nodes = to_dict.get("nodes", [])
    edges = to_dict.get("edges", []) if request.include_edges else []
    raw_edges = to_dict.get("edges", [])
    token_estimate = max(128, (len(nodes) * 36) + (len(raw_edges) * 12))
    token_limit = 4000
    context_metadata = {
        "node_count": len(nodes),
        "edge_count": len(raw_edges),
        "search_result_count": len(search_results or []),
        "token_estimate": token_estimate,
        "token_limit": token_limit,
        "token_remaining": max(0, token_limit - token_estimate),
        "token_used_percent": min(100, round((token_estimate / token_limit) * 100)),
        "max_depth": max_depth,
        "path_used": "graph_search",
        "context_tools": {"requested": context_tools},
        "phase_timings_ms": phase_timings_ms,
    }
    intelligence: Dict[str, Any] = {}
    async with get_db_context() as intelligence_db:
        phase_started = time.perf_counter()
        intelligence = await context_intelligence_service.assemble_query_intelligence(
            intelligence_db,
            collection=collection,
            request_message=request.query,
            recipe="rrf",
            path_used="graph_search",
            traversal_result=traversal_result,
            search_results=search_results or [],
            context_metadata=context_metadata,
            ctx=ctx,
            latency_ms=max(1, round((time.perf_counter() - started_at) * 1000)),
            context_tools=context_tools,
        )
        await intelligence_db.commit()
        phase_timings_ms["intelligence"] = max(1, round((time.perf_counter() - phase_started) * 1000))
    context_metadata = {
        **context_metadata,
        "query_id": intelligence.get("query_id"),
        "latency_ms": max(1, round((time.perf_counter() - started_at) * 1000)),
        "temporal_mode": "current",
        "lineage_edge_count": (intelligence.get("lineage_context") or {}).get("edge_count", 0),
        "decision_count": intelligence.get("decision_audit_count", len(intelligence.get("decision_history") or []) + 1),
        "native_decision_count": intelligence.get("native_decision_count", len(intelligence.get("decision_history") or [])),
        "query_trace_count": intelligence.get("query_trace_count", 1),
        "drift_severity": (intelligence.get("drift_context") or {}).get("severity", "clean"),
        "context_tools": intelligence.get("tool_context") or {"requested": context_tools},
        "phase_timings_ms": phase_timings_ms,
    }

    return build_graph_search_response(
        nodes=nodes,
        edges=edges,
        traversal_result=traversal_result,
        search_results=search_results,
        include_edges=request.include_edges,
        context_metadata=context_metadata,
        intelligence=intelligence,
    )


def _effective_depth(query: str, requested_depth: int) -> int:
    """Honor explicit natural-language hop depth while respecting API bounds."""
    depth = requested_depth
    match = re.search(r"\b([1-5])\s*(?:hop|hops)\b", query or "", re.IGNORECASE)
    if match:
        depth = max(depth, int(match.group(1)))
    return max(1, min(depth, 5))


def build_graph_search_response(
    *,
    nodes: List[Dict[str, Any]] | None = None,
    edges: List[Dict[str, Any]] | None = None,
    traversal_result: Any,
    search_results: List[Dict[str, Any]],
    include_edges: bool,
    context_metadata: Dict[str, Any] | None = None,
    intelligence: Dict[str, Any] | None = None,
) -> GraphSearchResponse:
    if traversal_result is None:
        return GraphSearchResponse(
            nodes=nodes or [],
            edges=edges or [],
            search_results=search_results,
            start_node_ids=[],
            stats={},
            context_metadata=context_metadata or {},
            temporal_context=(intelligence or {}).get("temporal_context") or {},
            lineage_context=(intelligence or {}).get("lineage_context") or {},
            decision_history=(intelligence or {}).get("decision_history") or [],
            drift_context=(intelligence or {}).get("drift_context") or {},
            tool_context=(intelligence or {}).get("tool_context") or {},
            decision_tree=(intelligence or {}).get("decision_tree") or {},
        )

    return GraphSearchResponse(
        nodes=nodes or [],
        edges=edges or [],
        search_results=search_results,
        start_node_ids=traversal_result.start_node_ids or [],
        stats=traversal_result.stats or {},
        context_metadata=context_metadata or {},
        temporal_context=(intelligence or {}).get("temporal_context") or {},
        lineage_context=(intelligence or {}).get("lineage_context") or {},
        decision_history=(intelligence or {}).get("decision_history") or [],
        drift_context=(intelligence or {}).get("drift_context") or {},
        tool_context=(intelligence or {}).get("tool_context") or {},
        decision_tree=(intelligence or {}).get("decision_tree") or {},
    )
