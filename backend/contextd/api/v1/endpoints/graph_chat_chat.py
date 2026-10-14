"""Main graph chat service."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

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
    strip_context_tool_mentions,
)
from contextd.api.v1.endpoints.graph_chat_synthesis import (
    append_count_hint,
    append_notebook_context_sections,
    build_chart_specs_from_notebook,
    build_graph_chat_system_prompt,
    build_queries_trace,
    build_tool_errors_section,
)
from contextd.core.logging import LoggerConfigurator
from contextd.core.context_intelligence_service import context_intelligence_service
from contextd.db.session import get_db_context
from contextd.platform.graph.config import get_graph_config
from contextd.platform.graph.traversal import GraphContextFormatter

logger = LoggerConfigurator.configure_logger(__name__)


async def chat_with_graph_for_request(
    readable_id: str,
    request: ChatRequest,
    ctx: ApiContext,
) -> ChatResponse:
    """Run graph-augmented chat orchestration and synthesize an answer."""
    started_at = time.perf_counter()
    async with get_db_context() as db:
        collection = await crud.collection.get_by_readable_id(db, readable_id=readable_id, ctx=ctx)
        if not collection:
            raise HTTPException(status_code=404, detail="Collection not found")

    glm_notebook_state = None
    context_tools = request_context_tools(
        explicit=request.context_tools,
        text=request.message,
    )

    from contextd.platform.agent_orchestration.business_logic import (
        expand_query_for_schema,
        format_pruned_schema,
        parse_collection_mention_from_message,
        retrieve_node_types_for_query,
    )

    collection_mention = parse_collection_mention_from_message(strip_context_tool_mentions(request.message))
    collection_ids_for_schema: List[str] = []
    source_types: List[str] = []
    mention_diagnostic: Optional[str] = None
    async with get_db_context() as db:
        if collection_mention:
            mentioned = await crud.collection.get_by_display_name_or_readable_id(
                db, mention=collection_mention, ctx=ctx
            )
            if mentioned:
                collection_ids_for_schema = [mentioned.readable_id]
                conns = await crud.source_connection.get_multi_with_stats(
                    db, ctx=ctx, collection_id=mentioned.readable_id, limit=50
                )
                source_types = [c["short_name"] for c in conns if c.get("short_name")]
                logger.info(
                    "[Graph Chat] @%s -> collection %s | collection_ids=%s",
                    collection_mention,
                    mentioned.readable_id,
                    collection_ids_for_schema,
                )
            else:
                available = await crud.collection.get_multi(db, ctx=ctx, limit=50)
                listed = []
                for collection_item in available:
                    c_conns = await crud.source_connection.get_multi_with_stats(
                        db, ctx=ctx, collection_id=collection_item.readable_id, limit=10
                    )
                    names = sorted({sc["short_name"] for sc in c_conns if sc.get("short_name")})
                    listed.append(
                        f"- '{collection_item.name}' (id: {collection_item.readable_id}) "
                        f"-- connectors: {', '.join(names) if names else 'none'}"
                    )
                mention_diagnostic = (
                    f"The user referenced `@{collection_mention}` but no collection with that "
                    "name or readable_id exists in this organization. Available collections "
                    "in this organization:\n"
                    + "\n".join(listed)
                    + "\nAsk the user to re-send the question with a matching @mention "
                    "(or without @ to use the currently-open collection)."
                )
                logger.info(
                    "[Graph Chat] @%s could not be resolved to a collection; using current",
                    collection_mention,
                )
        if not collection_ids_for_schema:
            collection_ids_for_schema = [readable_id]
            conns = await crud.source_connection.get_multi_with_stats(
                db, ctx=ctx, collection_id=readable_id, limit=50
            )
            source_types = [c["short_name"] for c in conns if c.get("short_name")]
            logger.info(
                "[Graph Chat] No @collection; current collection %s | collection_ids=%s",
                readable_id,
                collection_ids_for_schema,
            )

    from contextd.core.config import settings as _graph_chat_settings
    from contextd.core.semantic_merge_gating import use_glm_agents_for_graph_chat

    use_glm_agents = use_glm_agents_for_graph_chat(
        source_types,
        _graph_chat_settings.SEMANTIC_MERGE_STRUCTURED_CONNECTORS,
    )

    pruned_schema = ""
    if use_glm_agents:
        try:
            expanded_query = await expand_query_for_schema(request.message, ctx)
            payloads = await retrieve_node_types_for_query(
                ctx.organization.id,
                expanded_query,
                ctx,
                collection_ids=collection_ids_for_schema,
                source_types=None,
                top_k=15,
            )
            if not payloads and source_types:
                payloads = await retrieve_node_types_for_query(
                    ctx.organization.id,
                    expanded_query,
                    ctx,
                    collection_ids=None,
                    source_types=source_types,
                    top_k=15,
                )
            pruned_schema = format_pruned_schema(payloads)
            if pruned_schema:
                logger.info(
                    "[Graph Chat] Schema RAG: %s node types retrieved for vocabulary",
                    len(payloads),
                )
        except Exception as exc:
            logger.warning("[Graph Chat] Schema RAG failed: %s; continuing with empty schema", exc)

    traversal_result = None
    search_results: List[Dict[str, Any]] = []
    phase_timings_ms: Dict[str, int] = {}

    phase_started = time.perf_counter()
    if not use_glm_agents:
        logger.info(
            "[Graph Chat] Unstructured connector(s) in collection; graph search only "
            "(GLM agents disabled)",
        )
        source_type_filter = _parse_connector_ignoring_search(request.message)
        traversal_result, search_results = await _run_graph_search_retrieval(
            readable_id=readable_id,
            query=request.message,
            ctx=ctx,
            search_limit=request.search_limit,
            max_depth=request.max_depth,
            source_type_filter=source_type_filter,
            collection=collection,
        )
    else:
        try:
            from contextd.platform.agent_orchestration import run_glm
            from contextd.platform.agent_orchestration.runtime.traversal import (
                enrich_traversal_result_with_referenced_nodes,
                notebook_to_traversal_result,
            )
            from contextd.platform.agent_orchestration.types import (
                DeterministicContext,
                NonDeterministicContext,
            )

            glm_result = await run_glm(
                request.message,
                organization_id=ctx.organization.id,
                collection_id=collection.id,
                ctx=ctx,
                readable_id=readable_id,
                search_limit=request.search_limit,
                max_depth=request.max_depth,
                node_limit=100,
                vector_size=collection.vector_size,
                pruned_schema=pruned_schema,
                source_type_filter=None,
            )
            ctx_synth = glm_result.context_for_synthesis
            if isinstance(ctx_synth, DeterministicContext):
                logger.info("[Graph Chat] GLM path used: deterministic (Seed Search -> PPR/MST)")
                traversal_result = ctx_synth.traversal_result
                search_results = ctx_synth.search_results or []
            else:
                assert isinstance(ctx_synth, NonDeterministicContext)
                logger.info(
                    "[Graph Chat] GLM path used: non-deterministic (R-Agent / A-Agent / Executor)"
                )
                glm_notebook_state = ctx_synth.notebook_state
                traversal_result = notebook_to_traversal_result(
                    glm_notebook_state,
                    large_data_by_ref=getattr(ctx_synth, "large_data_by_ref", None),
                )
                traversal_result = await enrich_traversal_result_with_referenced_nodes(
                    traversal_result,
                    ctx.organization.id,
                    ctx,
                    readable_collection_id=readable_id,
                )
                search_results = []
        except Exception as exc:
            logger.warning("GLM run failed, falling back to no context: %s", exc)
            traversal_result = None
            search_results = []
    phase_timings_ms["retrieval"] = max(1, round((time.perf_counter() - phase_started) * 1000))

    phase_started = time.perf_counter()
    subgraph = None
    if request.include_subgraph and traversal_result and traversal_result.nodes:
        subgraph = _build_subgraph(traversal_result, search_results)

    context_for_prompt = _format_graph_context_for_prompt(
        traversal_result=traversal_result,
        search_results=search_results,
        query=request.message,
        max_context_tokens=request.max_context_tokens,
    )

    if mention_diagnostic:
        context_for_prompt = (
            "## @MENTION DIAGNOSTIC\n" + mention_diagnostic + "\n\n" + context_for_prompt
        )

    context_for_prompt, has_p_agent_charts = append_notebook_context_sections(
        context_for_prompt,
        glm_notebook_state,
    )

    entity_count_for_hint = (
        len(getattr(traversal_result, "nodes", None) or []) if traversal_result else 0
    )
    context_for_prompt = append_count_hint(
        context_for_prompt,
        entity_count_for_hint,
        has_p_agent_charts=has_p_agent_charts,
    )

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

        system_prompt = build_graph_chat_system_prompt(
            context_for_prompt=context_for_prompt,
            entity_count=entity_count,
            relationship_count=relationship_count,
            tool_errors_section=build_tool_errors_section(glm_notebook_state),
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": request.message},
        ]

        if getattr(settings, "SHOW_LLM_PROMPT", False):
            logger.info(
                "[Graph Chat] Final LLM prompt: system_prompt_length=%s messages_count=%s",
                len(system_prompt),
                len(messages),
            )
            for idx, message in enumerate(redact_llm_messages(messages)):
                role = message.get("role", "")
                content = message.get("content") or ""
                logger.info(
                    "[Graph Chat] Final LLM Message[%s] role=%s content=%s",
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

        chart_specs, p_agent_count = build_chart_specs_from_notebook(glm_notebook_state)
        if p_agent_count:
            logger.info(
                "[Graph Chat] chart_specs from notebook: p_agent_items=%s charts_collected=%s",
                p_agent_count,
                len(chart_specs),
            )

        queries_trace = build_queries_trace(glm_notebook_state)

        resolved_collection_name = await _resolve_collection_name(
            collection_ids_for_schema=collection_ids_for_schema,
            ctx=ctx,
        )

        context_metadata = build_graph_chat_context_metadata(
            traversal_result=traversal_result,
            search_results=search_results,
            context_for_prompt=context_for_prompt,
            max_depth=request.max_depth,
            use_glm_agents=use_glm_agents,
            glm_notebook_state=glm_notebook_state,
            queries_trace=queries_trace,
            collection_ids_for_schema=collection_ids_for_schema,
            resolved_collection_name=resolved_collection_name,
            source_types=source_types,
            collection_mention=collection_mention,
            mention_diagnostic=mention_diagnostic,
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
                    recipe="graph-chat",
                    path_used=context_metadata.get("path_used", "graph_chat"),
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
            chart_specs=chart_specs,
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
        logger.error("Chat generation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Chat failed: {str(exc)}") from exc


def _format_graph_context_for_prompt(
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
        logger.warning("TOON format failed, using plain context: %s", exc)
        return context_text


async def _resolve_collection_name(
    *,
    collection_ids_for_schema: List[str],
    ctx: ApiContext,
) -> Optional[str]:
    if not collection_ids_for_schema:
        return None

    async with get_db_context() as db:
        resolved = await crud.collection.get_by_readable_id(
            db, readable_id=collection_ids_for_schema[0], ctx=ctx
        )
        if resolved:
            return resolved.name
    return None


def determine_graph_chat_path_used(
    *,
    use_glm_agents: bool,
    glm_notebook_state: Any,
) -> str:
    if not use_glm_agents:
        return "graph_search"
    if glm_notebook_state is not None:
        return "glm_non_deterministic"
    return "glm_deterministic"


def build_graph_chat_context_metadata(
    *,
    traversal_result: Any,
    search_results: List[Dict[str, Any]],
    context_for_prompt: str,
    max_depth: int,
    use_glm_agents: bool,
    glm_notebook_state: Any,
    queries_trace: List[Dict[str, Any]],
    collection_ids_for_schema: List[str],
    resolved_collection_name: Optional[str],
    source_types: List[str],
    collection_mention: Optional[str],
    mention_diagnostic: Optional[str],
    max_context_tokens: int,
    phase_timings_ms: Dict[str, int] | None = None,
    context_tools: List[str] | None = None,
) -> Dict[str, Any]:
    """Build UI metadata for the main graph chat response."""
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
        "path_used": determine_graph_chat_path_used(
            use_glm_agents=use_glm_agents,
            glm_notebook_state=glm_notebook_state,
        ),
        "queries": queries_trace,
        "total_rows": sum(query["row_count"] for query in queries_trace),
        "collection_id": collection_ids_for_schema[0] if collection_ids_for_schema else None,
        "collection_name": resolved_collection_name,
        "source_types": source_types,
        "mention_unresolved": collection_mention if mention_diagnostic else None,
        "context_tools": {"requested": context_tools or []},
        "phase_timings_ms": phase_timings_ms or {},
    }
