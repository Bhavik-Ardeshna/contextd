"""Graph search tool used by the GLM executor."""

from __future__ import annotations

from typing import Any, Dict, List
from uuid import UUID

from contextd.api.context import ApiContext


async def retrieve_node(
    text: str,
    organization_id: UUID,
    collection_id: UUID,
    vector_size: int,
    ctx: ApiContext,
    *,
    readable_collection_id: str = "",
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Lookup seed nodes through the live graph search path."""
    from contextd.search.context import SearchContext
    from contextd.search.emitter import EventEmitter
    from contextd.search.operations.graph_search import GraphSearch

    graph_search = GraphSearch(
        collection_id=collection_id,
        organization_id=organization_id,
        limit=limit,
        graph_depth=0,
    )
    emitter = EventEmitter(request_id=ctx.request_id or "glm-tools", stream=False)
    search_context = SearchContext(
        request_id=ctx.request_id or "glm-tools",
        collection_id=collection_id,
        readable_collection_id=readable_collection_id,
        stream=False,
        vector_size=vector_size,
        offset=0,
        limit=limit,
        query=text,
        emitter=emitter,
        query_expansion=None,
        query_interpretation=None,
        embed_query=None,
        user_filter=None,
        temporal_relevance=None,
        retrieval=None,
        federated_search=None,
        reranking=None,
        generate_answer=None,
    )
    state: Dict[str, Any] = {}
    await graph_search.execute(context=search_context, state=state, ctx=ctx)
    results = state.get("graph_results", [])
    return [
        {
            "node_id": result.get("node_id"),
            "score": result.get("score"),
            "payload": result.get("payload", {}),
            "name": (result.get("payload") or {}).get("name"),
            "node_type": (result.get("payload") or {}).get("node_type"),
        }
        for result in results
        if result.get("node_id")
    ]
