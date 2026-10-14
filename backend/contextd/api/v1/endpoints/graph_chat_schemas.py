"""Request and response schemas for graph chat endpoints."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from pydantic import BaseModel, Field


CONTEXT_TOOL_KEYS = ("search", "graph", "temporal", "core", "cohort", "decision")
CONTEXT_TOOL_PURPOSES = {
    "search": "Seed the packet with deterministic hybrid search and RRF.",
    "graph": "Expand seed matches into a linked ContextD neighborhood.",
    "temporal": "Attach current bitemporal facts and cursor-aware state.",
    "core": "Attach the selected database core summary and source shape.",
    "cohort": "Attach cohort scope; defaults to all entities when no cohort is selected.",
    "decision": "Attach query audit and first-class Decision lineage.",
}
_CONTEXT_TOOL_RE = re.compile(r"@(" + "|".join(CONTEXT_TOOL_KEYS) + r")\b", re.IGNORECASE)


def normalize_context_tools(values: Sequence[str] | None) -> List[str]:
    """Normalize UI/request context-tool names while preserving declaration order."""
    normalized: List[str] = []
    for raw in values or []:
        tool = str(raw or "").strip().lower().removeprefix("@")
        if tool in CONTEXT_TOOL_KEYS and tool not in normalized:
            normalized.append(tool)
    return normalized


def parse_context_tools_from_text(text: str | None) -> List[str]:
    """Parse @search/@graph/etc. mentions from free-text clients."""
    return normalize_context_tools(match.group(1) for match in _CONTEXT_TOOL_RE.finditer(text or ""))


def strip_context_tool_mentions(text: str | None) -> str:
    """Remove reserved ContextD tool mentions before connector/collection mention parsing."""
    return re.sub(r"\s+", " ", _CONTEXT_TOOL_RE.sub(" ", text or "")).strip()


def request_context_tools(*, explicit: Sequence[str] | None, text: str | None) -> List[str]:
    """Return explicit context tools, falling back to mentions embedded in the message."""
    return normalize_context_tools(explicit) or parse_context_tools_from_text(text)


class TraverseRequest(BaseModel):
    """Request for graph traversal."""

    node_ids: List[str] = Field(..., description="Starting node IDs for traversal")
    max_depth: int = Field(default=2, ge=1, le=10, description="Maximum hops from start nodes")
    direction: str = Field(
        default="both",
        description="Traversal direction: outgoing, incoming, or both",
    )
    relationship_types: Optional[List[str]] = Field(
        default=None,
        description="Filter for specific relationship types (null = all)",
    )
    node_limit: int = Field(default=100, ge=1, le=1000, description="Maximum nodes to return")
    include_properties: bool = Field(default=True, description="Include full node properties")


class TraverseResponse(BaseModel):
    """Response from graph traversal."""

    nodes: List[Dict[str, Any]] = Field(..., description="Discovered nodes")
    edges: List[Dict[str, Any]] = Field(..., description="Discovered edges")
    start_node_ids: List[str] = Field(..., description="Original starting node IDs")
    stats: Dict[str, Any] = Field(default_factory=dict, description="Traversal statistics")


class ContextRequest(BaseModel):
    """Request for graph context extraction."""

    query: str = Field(..., description="User query for context")
    node_ids: Optional[List[str]] = Field(
        default=None,
        description="Specific node IDs to get context for (if not provided, uses search)",
    )
    max_depth: int = Field(default=2, ge=1, le=5, description="Traversal depth")
    max_tokens: int = Field(
        default=4000, ge=100, le=16000, description="Maximum tokens for context"
    )
    include_search: bool = Field(default=True, description="Include search results in context")
    search_limit: int = Field(default=10, ge=1, le=50, description="Number of search results")


class ContextResponse(BaseModel):
    """Response with formatted graph context."""

    context: str = Field(..., description="Pre-formatted context text for LLM")
    token_estimate: int = Field(..., description="Estimated token count")
    node_count: int = Field(..., description="Number of nodes in context")
    edge_count: int = Field(..., description="Number of edges in context")
    truncated: bool = Field(default=False, description="Whether context was truncated")
    search_results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Search results used (if include_search=True)",
    )


class ChatRequest(BaseModel):
    """Request for chat with graph context."""

    message: str = Field(..., description="User message")
    conversation_history: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Previous messages [{role, content}]",
    )
    max_depth: int = Field(default=2, ge=1, le=5, description="Graph traversal depth")
    search_limit: int = Field(default=10, ge=1, le=50, description="Search results for context")
    max_context_tokens: int = Field(
        default=4000, ge=100, le=16000, description="Max context tokens"
    )
    temperature: float = Field(default=0.7, ge=0, le=2, description="LLM temperature")
    stream: bool = Field(default=False, description="Stream response (not yet implemented)")
    include_subgraph: bool = Field(
        default=True, description="Include subgraph in response for UI display"
    )
    include_lineage: bool = Field(
        default=True,
        description="Include native temporal, lineage, decision, and drift context",
    )
    context_tools: List[str] = Field(
        default_factory=list,
        description="Requested ContextD context tools: search, graph, temporal, core, cohort, decision",
    )
    temporal_mode: str = Field(
        default="current",
        description="Temporal query mode: current, historical, knowledge, or audit",
    )


class EntityReference(BaseModel):
    """Standardized entity reference metadata."""

    entity_id: str = Field(..., description="Unique entity identifier")
    node_id: str = Field(..., description="Graph node ID (use with organization_id to fetch node)")
    organization_id: Optional[str] = Field(
        default=None, description="Organization ID for graph lookup"
    )
    name: str = Field(..., description="Display name")
    entity_type: str = Field(..., description="Entity type (e.g., AsanaTaskEntity)")
    source: str = Field(default="", description="Source system (e.g., asana, jira)")
    url: Optional[str] = Field(default=None, description="External URL if available")
    score: Optional[float] = Field(default=None, description="Relevance score if from search")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Key properties")


class SubgraphNode(BaseModel):
    """Node in the subgraph for UI visualization."""

    node_id: str = Field(..., description="Node ID")
    node_type: str = Field(..., description="Node type")
    name: str = Field(..., description="Display name")
    source: str = Field(default="", description="Source system")
    depth: int = Field(default=0, description="Distance from search result (0 = direct match)")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Node properties")
    is_primary: bool = Field(default=False, description="Whether this was a direct search match")


class SubgraphEdge(BaseModel):
    """Edge in the subgraph for UI visualization."""

    from_node_id: str = Field(..., description="Source node ID")
    to_node_id: str = Field(..., description="Target node ID")
    relationship_type: str = Field(..., description="Relationship type")
    label: str = Field(default="", description="Human-readable relationship label")


class Subgraph(BaseModel):
    """Complete subgraph for UI visualization."""

    nodes: List[SubgraphNode] = Field(default_factory=list, description="Nodes in subgraph")
    edges: List[SubgraphEdge] = Field(default_factory=list, description="Edges in subgraph")
    center_node_ids: List[str] = Field(
        default_factory=list, description="Primary/search result node IDs"
    )


class PlotImage(BaseModel):
    """A plot from P-Agent for display in the chat window."""

    description: str = Field(..., description="Short text description of the plot")
    image_base64: str = Field(
        ..., description="PNG image as base64 for display (data URL: data:image/png;base64,...)"
    )


class ChartSpecResponse(BaseModel):
    """JSON Bridge chart spec for frontend rendering."""

    type: str = Field(default="chart", description="Always 'chart'")
    chart_type: str = Field(
        ..., description="pie | bar | line | histogram | area | scatter | radar | radialBar"
    )
    title: str = Field(default="", description="Chart title")
    data: List[Dict[str, Any]] = Field(
        default_factory=list, description="Data points: [{label, value}, ...]"
    )
    config: Optional[Dict[str, Any]] = Field(
        default=None, description="Optional xAxis, yAxis, etc."
    )


class ChatResponse(BaseModel):
    """Response from chat endpoint."""

    message: str = Field(..., description="Assistant response")
    entity_references: List[EntityReference] = Field(
        default_factory=list,
        description="Entities referenced in the response with standardized metadata",
    )
    subgraph: Optional[Subgraph] = Field(
        default=None,
        description="Subgraph used to generate response (for UI display)",
    )
    plot_images: List[PlotImage] = Field(
        default_factory=list,
        description="Plots generated by P-Agent for display in chat (description + base64 PNG)",
    )
    chart_specs: List[ChartSpecResponse] = Field(
        default_factory=list,
        description="Chart specifications (type, chart_type, title, data) for interactive rendering",
    )
    context_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Metadata about context used",
    )
    temporal_context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Bitemporal facts used or available for this response",
    )
    lineage_context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Provenance and derivation edges attached to this response",
    )
    decision_history: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="First-class Decision primitives relevant to this response",
    )
    drift_context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Config, schema, cursor, and Forge drift guard result",
    )
    tool_context: Dict[str, Any] = Field(
        default_factory=dict,
        description="ContextD tool lane status and evidence for this response",
    )
    decision_tree: Dict[str, Any] = Field(
        default_factory=dict,
        description="Context assembly decision tree for answer auditability",
    )
    search_results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Search results that informed the response",
    )


class GraphSearchRequest(BaseModel):
    """Request for graph search: query + whether to return edges."""

    query: str = Field(..., description="Search query")
    include_edges: bool = Field(
        default=True,
        description="If True, return subgraph (nodes + edges); if False, return nodes only",
    )
    search_limit: int = Field(
        default=10, ge=1, le=50, description="Max seed results from vector search"
    )
    max_depth: int = Field(default=2, ge=1, le=5, description="Traversal depth")
    context_tools: List[str] = Field(
        default_factory=list,
        description="Requested ContextD context tools for this graph-search packet",
    )


class GraphSearchResponse(BaseModel):
    """Response: nodes always; edges only when include_edges was True."""

    nodes: List[Dict[str, Any]] = Field(..., description="Discovered nodes")
    edges: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Edges (only when include_edges=True)",
    )
    search_results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Seed search results (primary matches)",
    )
    start_node_ids: List[str] = Field(default_factory=list, description="Seed node IDs")
    stats: Dict[str, Any] = Field(default_factory=dict, description="Traversal stats")
    context_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Native ContextD response metadata, including query_id and path",
    )
    temporal_context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Bitemporal facts attached to this graph-search response",
    )
    lineage_context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Lineage/provenance edges attached to this graph-search response",
    )
    decision_history: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Relevant first-class decisions attached to this response",
    )
    drift_context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Drift guard state at response assembly time",
    )
    tool_context: Dict[str, Any] = Field(
        default_factory=dict,
        description="ContextD tool lane status and evidence for this graph-search response",
    )
    decision_tree: Dict[str, Any] = Field(
        default_factory=dict,
        description="Persisted ContextD query decision trace",
    )


class NeighborhoodRequest(BaseModel):
    """Request to expand an aggregate row's 2-hop neighborhood from real underlying nodes."""

    node_type: str = Field(
        ...,
        description="Target node_type of underlying rows (e.g. 'DatabaseTableNode_public_trainers')",
    )
    filter_key: Optional[str] = Field(
        default=None,
        description="Property key to filter underlying rows on (e.g. 'specialty'). Looked up inside n.properties JSON.",
    )
    filter_value: Optional[Any] = Field(
        default=None,
        description="Value to match against filter_key. Compared with equality; strings case-sensitive.",
    )
    sample_limit: int = Field(
        default=3, ge=1, le=25, description="How many underlying rows to sample"
    )
    depth: int = Field(default=2, ge=1, le=3, description="Max hops to expand from each sample")
    neighbor_cap: int = Field(
        default=60, ge=1, le=500, description="Cap on distinct neighbor nodes returned"
    )


class NeighborhoodResponse(BaseModel):
    """Expanded neighborhood centered on a handful of underlying rows matching the filter."""

    samples: List[Dict[str, Any]] = Field(
        ..., description="Representative underlying rows (sampled)"
    )
    nodes: List[Dict[str, Any]] = Field(
        ..., description="Distinct nodes within `depth` hops of any sample"
    )
    edges: List[Dict[str, Any]] = Field(..., description="Edges between nodes in this neighborhood")
    stats: Dict[str, Any] = Field(default_factory=dict)
