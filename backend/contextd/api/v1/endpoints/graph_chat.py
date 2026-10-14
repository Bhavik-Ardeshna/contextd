"""Graph traversal and chat endpoints.

Provides API endpoints for:
- Graph traversal from node IDs
- Graph context extraction for LLM
- Chat with graph-augmented context

These endpoints are mounted under /collections prefix.
"""

from fastapi import Depends, Path

from contextd.api.context import ApiContext
from contextd.api.deps import get_context
from contextd.api.router import TrailingSlashRouter
from contextd.api.v1.endpoints.graph_chat_chat import chat_with_graph_for_request
from contextd.api.v1.endpoints.graph_chat_context import get_graph_context_for_request
from contextd.api.v1.endpoints.graph_chat_graph_search import search_graph_for_request
from contextd.api.v1.endpoints.graph_chat_schemas import (
    ChatRequest,
    ChatResponse,
    ContextRequest,
    ContextResponse,
    GraphSearchRequest,
    GraphSearchResponse,
    NeighborhoodRequest,
    NeighborhoodResponse,
    TraverseRequest,
    TraverseResponse,
)
from contextd.api.v1.endpoints.graph_chat_search import chat_with_graph_search_for_request
from contextd.api.v1.endpoints.graph_chat_trace import (
    expand_trace_neighborhood_for_request,
)
from contextd.api.v1.endpoints.graph_chat_traversal import traverse_graph_for_request

router = TrailingSlashRouter()


# ============================================================================
# Endpoints
# ============================================================================


@router.post(
    "/{readable_id}/graph/traverse",
    response_model=TraverseResponse,
    summary="Traverse graph from nodes",
    description="Extract subgraph starting from specified nodes with configurable depth",
)
async def traverse_graph(
    readable_id: str = Path(..., description="Collection readable ID"),
    request: TraverseRequest = ...,
    ctx: ApiContext = Depends(get_context),
):
    return await traverse_graph_for_request(readable_id, request, ctx)


@router.post(
    "/{readable_id}/graph-search",
    response_model=GraphSearchResponse,
    summary="Graph search: nodes or subgraph",
    description="Run seed search + traversal. Returns nodes only or nodes+edges (subgraph) based on include_edges.",
)
async def graph_search(
    readable_id: str = Path(..., description="Collection readable ID"),
    request: GraphSearchRequest = ...,
    ctx: ApiContext = Depends(get_context),
):
    return await search_graph_for_request(readable_id, request, ctx)


@router.post(
    "/{readable_id}/graph/context",
    response_model=ContextResponse,
    summary="Get graph context for LLM",
    description="Extract and format graph context optimized for LLM consumption",
)
async def get_graph_context(
    readable_id: str = Path(..., description="Collection readable ID"),
    request: ContextRequest = ...,
    ctx: ApiContext = Depends(get_context),
):
    return await get_graph_context_for_request(readable_id, request, ctx)


@router.post(
    "/{readable_id}/trace/neighborhood",
    response_model=NeighborhoodResponse,
    summary="Expand a trace row into its 2-3 hop graph neighborhood",
    description=(
        "For a Decision-Trace aggregate row, sample the underlying GraphNodes matching a filter "
        "(e.g. specialty='Running'), then expand their 2-3 hop neighborhood and return the "
        "distinct nodes + edges. Used by the chat sidebar to turn an aggregate bucket into a "
        "real graph slice."
    ),
)
async def expand_trace_neighborhood(
    readable_id: str = Path(..., description="Collection readable ID"),
    request: NeighborhoodRequest = ...,
    ctx: ApiContext = Depends(get_context),
) -> NeighborhoodResponse:
    return await expand_trace_neighborhood_for_request(readable_id, request, ctx)


@router.post(
    "/{readable_id}/chat",
    response_model=ChatResponse,
    summary="Chat with graph-augmented context",
    description="Send a message and get a response informed by knowledge graph",
)
async def chat_with_graph(
    readable_id: str = Path(..., description="Collection readable ID"),
    request: ChatRequest = ...,
    ctx: ApiContext = Depends(get_context),
):
    return await chat_with_graph_for_request(readable_id, request, ctx)


@router.post(
    "/{readable_id}/chat/search",
    response_model=ChatResponse,
    summary="Chat via deterministic path (Seed Search → PPR/MST)",
    description="Same as main chat but always uses the deterministic path (no C-Agent, no R-Agent). Accessible via @search.",
)
async def chat_with_graph_search(
    readable_id: str = Path(..., description="Collection readable ID"),
    request: ChatRequest = ...,
    ctx: ApiContext = Depends(get_context),
):
    return await chat_with_graph_search_for_request(readable_id, request, ctx)
