"""Schemas for ContextD temporal, lineage, decision, and drift inspection."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ContextQueryFeedbackRequest(BaseModel):
    query_id: Optional[str] = None
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = None
    retrieved_node_ids: List[str] = Field(default_factory=list)
    retrieved_edge_ids: List[str] = Field(default_factory=list)


class ContextQueryFeedbackResponse(BaseModel):
    query_id: Optional[str] = None
    rating: int
    target_weight: float
    alpha: float
    updated_facts: int
    previous_average_weight: Optional[float] = None
    new_average_weight: Optional[float] = None
    trace_updated: bool = False


class ContextIntelligenceSource(BaseModel):
    source_connection_id: str
    source_name: str
    provider: str
    sync_id: Optional[str] = None
    cursor_field: Optional[str] = None
    drift: Dict[str, Any] = Field(default_factory=dict)


class ContextIntelligenceSummary(BaseModel):
    collection_id: str
    readable_id: str
    name: str
    generated_at: datetime | str
    totals: Dict[str, Any] = Field(default_factory=dict)
    temporal: Dict[str, Any] = Field(default_factory=dict)
    lineage: Dict[str, Any] = Field(default_factory=dict)
    decisions: Dict[str, Any] = Field(default_factory=dict)
    drift: Dict[str, Any] = Field(default_factory=dict)
    query_traces: List[Dict[str, Any]] = Field(default_factory=list)
    sources: List[ContextIntelligenceSource] = Field(default_factory=list)
