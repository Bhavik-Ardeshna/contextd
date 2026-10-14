"""Pydantic schemas for cohort API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CohortDraftRequest(BaseModel):
    """Natural language cohort definition (draft pipeline)."""

    message: str = Field(..., min_length=1, description="User description of the cohort")
    mode: Literal["list", "scoring"] = Field(
        default="list",
        description='Use "scoring" for weighted score + LLM-iterated cutoff pipeline.',
    )


class ResearchPlanSchema(BaseModel):
    """Mirror of ResearchPlan for API responses."""

    goal: str
    steps: List[str]
    use_p_agent: bool = False
    p_agent_instruction: Optional[str] = None


class CohortPlanSchema(BaseModel):
    """Cohort R-Agent output for clients."""

    target_node_type: str
    display_property_keys: List[str]
    identifier_property_keys: List[str]
    research_plan: ResearchPlanSchema


class ScoringComponentSchema(BaseModel):
    """One weighted component in a scoring cohort."""

    property_key: str
    weight: float
    direction: str
    normalization: Dict[str, Any] = Field(default_factory=dict)


class CohortScoringPlanSchema(BaseModel):
    """Scoring cohort R-Agent output."""

    target_node_type: str
    display_property_keys: List[str] = Field(default_factory=list)
    identifier_property_keys: List[str] = Field(default_factory=list)
    missing_data_policy: str = "neutral_partial_score"
    cutoff_method: str = "llm_iterated"
    components: List[ScoringComponentSchema]
    research_plan: ResearchPlanSchema


class CohortDraftResponse(BaseModel):
    """Draft: proposed plan + Cypher + sample rows (not persisted)."""

    mode: Literal["list", "scoring"] = "list"
    cohort_plan: Optional[CohortPlanSchema] = None
    scoring_plan: Optional[CohortScoringPlanSchema] = None
    distribution_summary: Optional[Dict[str, Any]] = None
    score_distribution: Optional[Dict[str, Any]] = None
    cutoff_value: Optional[float] = None
    cutoff_rationale: Optional[str] = None
    cutoff_iterations_used: int = 0
    cypher_query: Optional[str] = None
    sample_rows: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None
    warning: Optional[str] = Field(
        default=None,
        description="Hints when Cypher returned 0 rows after retries (date strings, filter semantics, etc.)",
    )


class CohortCreate(BaseModel):
    """Persist a cohort after reviewing a draft."""

    name: str = Field(..., min_length=1, max_length=256)
    target_node_type: str
    cypher_text: str = Field(..., min_length=1)
    display_property_keys: List[str] = Field(default_factory=list)
    identifier_property_keys: List[str] = Field(default_factory=list)
    cohort_mode: Literal["list", "scoring"] = "list"
    scoring_spec: Optional[Dict[str, Any]] = None
    distribution_probe_snapshot: Optional[Dict[str, Any]] = None
    cutoff_value: Optional[float] = None
    cutoff_iterations_used: Optional[int] = None
    score_breakdown_keys: Optional[List[str]] = None
    cypher_params: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Extra Neo4j $-parameters for stored Cypher (optional; server infers many).",
    )


class CohortUpdate(BaseModel):
    """Partial update for saved cohort (optional fields)."""

    name: Optional[str] = Field(None, max_length=256)
    cypher_text: Optional[str] = None
    display_property_keys: Optional[List[str]] = None
    identifier_property_keys: Optional[List[str]] = None


class CohortOut(BaseModel):
    """Saved cohort row."""

    id: UUID
    organization_id: UUID
    collection_id: UUID
    name: str
    target_node_type: str
    cypher_text: str
    display_property_keys: List[str]
    identifier_property_keys: List[str]
    cohort_mode: str = "list"
    scoring_spec: Optional[Dict[str, Any]] = None
    distribution_probe_snapshot: Optional[Dict[str, Any]] = None
    cutoff_value: Optional[float] = None
    cutoff_iterations_used: Optional[int] = None
    score_breakdown_keys: Optional[List[str]] = None
    cypher_params: Optional[Dict[str, Any]] = None
    created_at: datetime
    modified_at: datetime
    created_by_email: Optional[str] = None

    model_config = ConfigDict(
        from_attributes=True,
    )


class CohortMemberRow(BaseModel):
    """Shallow member projection."""

    node_id: str
    fields: Dict[str, Any] = Field(default_factory=dict)
    final_score: Optional[float] = None
    confidence: Optional[float] = None


class CohortRunResponse(BaseModel):
    """Paginated shallow members."""

    rows: List[CohortMemberRow]
    total_fetched: int
    offset: int
    limit: int


class CohortMemberDetailResponse(BaseModel):
    """Deep-dive: NodeInfo-style payload."""

    node_id: str
    node_type: Optional[str] = None
    name: Optional[str] = None
    properties: Dict[str, Any] = Field(default_factory=dict)
    neighbors: List[Dict[str, Any]] = Field(default_factory=list)
    final_score: Optional[float] = None
    confidence: Optional[float] = None
    score_breakdown: Dict[str, Any] = Field(
        default_factory=dict,
        description="Per-component scores when cohort_mode is scoring",
    )
