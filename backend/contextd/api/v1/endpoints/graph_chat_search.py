"""Deterministic graph chat search service."""

from __future__ import annotations

import time
from typing import Any, Dict, List

from fastapi import HTTPException

from contextd import crud
from contextd.api.context import ApiContext
from contextd.api.v1.endpoints.graph_chat_presenters import (
    _build_entity_references,
    _build_subgraph,
)
from contextd.api.v1.endpoints.graph_chat_retrieval import (
    _parse_connector_ignoring_search,
    _run_graph_search_retrieval,
)
from contextd.api.v1.endpoints.graph_chat_schemas import (
    ChatRequest,
    ChatResponse,
    request_context_tools,
)
from contextd.api.v1.endpoints.graph_chat_synthesis import (
    append_count_hint,
    build_graph_chat_search_system_prompt,
)
from contextd.core.logging import LoggerConfigurator
from contextd.core.context_intelligence_service import context_intelligence_service
from contextd.db.session import get_db_context
from contextd.platform.graph.config import get_graph_config
from contextd.platform.graph.traversal import GraphContextFormatter

logger = LoggerConfigurator.configure_logger(__name__)


async def chat_with_graph_search_for_request(
    readable_id: str,
    request: ChatRequest,
    ctx: ApiContext,
) -> ChatResponse:
    """Run deterministic graph-search retrieval and synthesize a chat response."""
    started_at = time.perf_counter()
    async with get_db_context() as db:
        collection = await crud.collection.get_by_readable_id(db, readable_id=readable_id, ctx=ctx)
        if not collection:
            raise HTTPException(status_code=404, detail="Collection not found")

    phase_timings_ms: Dict[str, int] = {}
    context_tools = request_context_tools(
        explicit=request.context_tools,
        text=request.message,
    )

    source_type_filter = _parse_connector_ignoring_search(request.message)
    phase_started = time.perf_counter()
    traversal_result, search_results = await _run_graph_search_retrieval(
        readable_id=readable_id,
        query=request.message,
        ctx=ctx,
        search_limit=request.search_limit,
        max_depth=request.max_depth,
        source_type_filter=source_type_filter,
        collection=collection,
    )
    phase_timings_ms["retrieval"] = max(1, round((time.perf_counter() - phase_started) * 1000))

    phase_started = time.perf_counter()
    subgraph = None
    if request.include_subgraph and traversal_result and traversal_result.nodes:
        subgraph = _build_subgraph(traversal_result, search_results)

    context_for_prompt = _format_search_context_for_prompt(
        traversal_result=traversal_result,
        search_results=search_results,
        query=request.message,
        max_context_tokens=request.max_context_tokens,
    )
    entity_count_for_hint = (
        len(getattr(traversal_result, "nodes", None) or []) if traversal_result else 0
    )
    context_for_prompt = append_count_hint(context_for_prompt, entity_count_for_hint)

    entity_references = _build_entity_references(
        search_results,
        traversal_result.nodes if traversal_result else [],
        organization_id=ctx.organization.id,
    )
    phase_timings_ms["context"] = max(1, round((time.perf_counter() - phase_started) * 1000))

    try:
        from contextd.core.config import settings
        from contextd.platform.llm.gateway import (
            LLMConfigurationError,
            get_llm_gateway,
            redact_llm_messages,
        )

        entity_count = len(traversal_result.nodes) if traversal_result else 0
        relationship_count = len(traversal_result.edges) if traversal_result else 0

        system_prompt = build_graph_chat_search_system_prompt(
            context_for_prompt=context_for_prompt,
            entity_count=entity_count,
            relationship_count=relationship_count,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": request.message},
        ]

        if getattr(settings, "SHOW_LLM_PROMPT", False):
            logger.info(
                "[Graph Chat Search] Final LLM prompt: system_prompt_length=%s messages_count=%s",
                len(system_prompt),
                len(messages),
            )
            for idx, message in enumerate(redact_llm_messages(messages)):
                role = message.get("role", "")
                content = message.get("content") or ""
                logger.info(
                    "[Graph Chat Search] Message[%s] role=%s content=%s",
                    idx,
                    role,
                    content,
                )

        try:
            phase_started = time.perf_counter()
            response_text = await get_llm_gateway().complete(
                messages,
                role="answer_synthesis",
                ctx=ctx,
            )
            phase_timings_ms["synthesis"] = max(1, round((time.perf_counter() - phase_started) * 1000))
        except LLMConfigurationError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        context_metadata = build_search_context_metadata(
            traversal_result=traversal_result,
            search_results=search_results,
            context_for_prompt=context_for_prompt,
            max_depth=request.max_depth,
            max_context_tokens=request.max_context_tokens,
            phase_timings_ms=phase_timings_ms,
            context_tools=context_tools,
        )
        intelligence = {}
        if request.include_lineage:
            async with get_db_context() as intelligence_db:
                phase_started = time.perf_counter()
                intelligence = await context_intelligence_service.assemble_query_intelligence(
                    intelligence_db,
                    collection=collection,
                    request_message=request.message,
                    recipe="rrf",
                    path_used="graph_search",
                    traversal_result=traversal_result,
                    search_results=search_results,
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
                "temporal_mode": request.temporal_mode,
                "lineage_edge_count": (intelligence.get("lineage_context") or {}).get("edge_count", 0),
                "decision_count": intelligence.get("decision_audit_count", len(intelligence.get("decision_history") or []) + 1),
                "native_decision_count": intelligence.get("native_decision_count", len(intelligence.get("decision_history") or [])),
                "query_trace_count": intelligence.get("query_trace_count", 1),
                "drift_severity": (intelligence.get("drift_context") or {}).get("severity", "clean"),
                "context_tools": intelligence.get("tool_context") or {"requested": context_tools},
                "phase_timings_ms": phase_timings_ms,
            }

        return ChatResponse(
            message=response_text,
            entity_references=entity_references,
            subgraph=subgraph,
            plot_images=[],
            chart_specs=[],
            context_metadata=context_metadata,
            temporal_context=intelligence.get("temporal_context") or {},
            lineage_context=intelligence.get("lineage_context") or {},
            decision_history=intelligence.get("decision_history") or [],
            drift_context=intelligence.get("drift_context") or {},
            tool_context=intelligence.get("tool_context") or {},
            decision_tree=intelligence.get("decision_tree") or {},
            search_results=search_results[:5],
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Chat/search generation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Chat failed: {str(exc)}") from exc


def _format_search_context_for_prompt(
    *,
    traversal_result: Any,
    search_results: List[Dict[str, Any]],
    query: str,
    max_context_tokens: int,
) -> str:
    if not traversal_result or not (traversal_result.nodes or traversal_result.edges):
        return "No relevant information found in the knowledge graph."

    formatter = GraphContextFormatter(
        max_tokens=max_context_tokens,
        include_properties=True,
        subgraph_text_mode=get_graph_config().subgraph_text_mode,
    )
    context_text = formatter.format_for_chat(
        traversal_result=traversal_result,
        query=query,
        search_results=search_results,
    )
    try:
        return formatter.format_for_chat_hybrid_toon(
            traversal_result=traversal_result,
            query=query,
            search_results=search_results,
        )
    except Exception as exc:
        logger.warning("TOON format failed in chat/search: %s", exc)
        return context_text


def build_search_context_metadata(
    *,
    traversal_result: Any,
    search_results: List[Dict[str, Any]],
    context_for_prompt: str,
    max_depth: int,
    max_context_tokens: int,
    phase_timings_ms: Dict[str, int] | None = None,
    context_tools: List[str] | None = None,
) -> Dict[str, Any]:
    token_estimate = int(len(context_for_prompt) * 0.3)
    return {
        "node_count": len(traversal_result.nodes) if traversal_result else 0,
        "edge_count": len(traversal_result.edges) if traversal_result else 0,
        "search_result_count": len(search_results),
        "token_estimate": token_estimate,
        "token_limit": max_context_tokens,
        "token_remaining": max(0, max_context_tokens - token_estimate),
        "token_used_percent": min(100, round((token_estimate / max_context_tokens) * 100)) if max_context_tokens else 0,
        "max_depth": max_depth,
        "path_used": "graph_search",
        "context_tools": {"requested": context_tools or []},
        "phase_timings_ms": phase_timings_ms or {},
    }
