"""Graph context extraction service for graph chat endpoints."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import HTTPException

from contextd import crud
from contextd.api.context import ApiContext
from contextd.api.v1.endpoints.graph_chat_schemas import ContextRequest, ContextResponse
from contextd.core.logging import LoggerConfigurator
from contextd.db.session import get_db_context
from contextd.platform.graph.config import get_graph_config
from contextd.platform.graph.traversal import (
    GraphContextFormatter,
    TraversalConfig,
    TraversalService,
)
from contextd.search.operations.graph_search import GraphSearch

logger = LoggerConfigurator.configure_logger(__name__)


async def get_graph_context_for_request(
    readable_id: str,
    request: ContextRequest,
    ctx: ApiContext,
) -> ContextResponse:
    """Build pre-formatted graph context for LLM consumption."""
    async with get_db_context() as db:
        collection = await crud.collection.get_by_readable_id(db, readable_id=readable_id, ctx=ctx)
        if not collection:
            raise HTTPException(status_code=404, detail="Collection not found")

    search_results: List[Dict[str, Any]] = []
    node_ids = request.node_ids or []

    if request.include_search and not node_ids:
        try:
            from contextd.platform.agent_orchestration.business_logic import (
                parse_connector_filter_from_message,
            )
            from contextd.search.context import SearchContext
            from contextd.search.emitter import EventEmitter

            source_type_filter = parse_connector_filter_from_message(request.query)
            graph_search = GraphSearch(
                collection_id=collection.id,
                organization_id=ctx.organization.id,
                limit=request.search_limit,
                graph_depth=0,
                source_type_filter=source_type_filter,
            )

            emitter = EventEmitter(request_id=ctx.request_id, stream=False)
            search_context = SearchContext(
                request_id=ctx.request_id,
                collection_id=collection.id,
                readable_collection_id=readable_id,
                stream=False,
                vector_size=collection.vector_size,
                offset=0,
                limit=request.search_limit,
                query=request.query,
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
            await graph_search.execute(
                context=search_context,
                state=state,
                ctx=ctx,
            )

            search_results = state.get("graph_results", [])
            node_ids = _node_ids_from_search_results(search_results)

        except Exception as exc:
            logger.warning("Search for context failed: %s", exc)

    if not node_ids:
        return _empty_context_response()

    try:
        service = await TraversalService.create()

        try:
            config = TraversalConfig(
                max_depth=request.max_depth,
                node_limit=100,
                include_properties=True,
            )

            traversal_result = await service.traverse(
                node_ids=node_ids,
                organization_id=ctx.organization.id,
                config=config,
                readable_collection_id=readable_id,
            )

            formatter = GraphContextFormatter(
                max_tokens=request.max_tokens,
                include_properties=True,
                subgraph_text_mode=get_graph_config().subgraph_text_mode,
            )
            try:
                from contextd.core.config import settings as app_settings

                if getattr(app_settings, "USE_TOON", True):
                    formatted = formatter.format_for_chat_hybrid_toon(
                        traversal_result=traversal_result,
                        query=request.query,
                        search_results=search_results,
                    )
                else:
                    formatted = formatter.format_for_chat(
                        traversal_result=traversal_result,
                        query=request.query,
                        search_results=search_results,
                    )
            except Exception as exc:
                logger.warning("Hybrid TOON format failed for context endpoint: %s", exc)
                formatted = formatter.format_for_chat(
                    traversal_result=traversal_result,
                    query=request.query,
                    search_results=search_results,
                )

            token_estimate = int(len(formatted) * 0.3)
            return ContextResponse(
                context=formatted,
                token_estimate=token_estimate,
                node_count=len(traversal_result.nodes),
                edge_count=len(traversal_result.edges),
                truncated=token_estimate > request.max_tokens,
                search_results=search_results[:5],
            )

        finally:
            await service.close()

    except Exception as exc:
        logger.error("Context extraction failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Context extraction failed: {str(exc)}")


def _node_ids_from_search_results(search_results: List[Dict[str, Any]]) -> List[str]:
    return [result["node_id"] for result in search_results if result.get("node_id")]


def _empty_context_response() -> ContextResponse:
    return ContextResponse(
        context="No relevant information found in the knowledge graph.",
        token_estimate=10,
        node_count=0,
        edge_count=0,
        truncated=False,
        search_results=[],
    )
