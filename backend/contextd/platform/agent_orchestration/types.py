"""Pydantic models for Multi-Agent GLM state and agent contracts."""

import re
from typing import Any, Dict, List, Literal, Optional, Union, get_args

from pydantic import BaseModel, Field, field_validator, model_validator


class ExecutionRecord(BaseModel):
    """Single entry in execution history to avoid redundant tool calls."""

    tool_or_step: str = Field(..., description="Tool name or 'code_run'")
    input_summary: str = Field(..., description="Short summary of inputs")
    output_summary: str = Field(..., description="Short summary of outputs")
    timestamp_iso: str = Field(..., description="ISO timestamp")


class NotebookState(BaseModel):
    """Notebook state: current knowledge, missing information, execution history."""

    current_knowledge: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Facts / node summaries / query results from tool outputs",
    )
    missing_information: List[str] = Field(
        default_factory=list,
        description="Open questions or gaps the R-Agent has identified",
    )
    execution_history: List[ExecutionRecord] = Field(
        default_factory=list,
        description="History of tool/code runs to avoid redundancy",
    )


class ToolOutput(BaseModel):
    """Generic structure for results of RetrieveNode, NodeInfo, run_cypher."""

    tool_name: str = Field(..., description="Name of the tool that produced this")
    result: Any = Field(default=None, description="Main result payload")
    node_ids: List[str] = Field(
        default_factory=list,
        description="Node IDs involved if applicable",
    )
    raw: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Raw response for merging into current_knowledge",
    )


class ResearchPlan(BaseModel):
    """R-Agent structured output when more research is needed."""

    steps: List[str] = Field(..., description="Next steps to fill gaps")
    goal: str = Field(..., description="Goal of this research plan")
    use_p_agent: bool = Field(
        default=False,
        description="When true, P-Agent will run on Cypher results for plotting/analysis",
    )
    p_agent_instruction: Optional[str] = Field(
        default=None,
        description="Instruction for P-Agent (e.g. what to plot or how to summarise)",
    )


def _string_to_research_plan_dict(text: str) -> Dict[str, Any]:
    """Turn prose / numbered lines from the LLM into a ResearchPlan-compatible dict."""
    t = text.strip()
    if not t:
        return {
            "goal": "Implement the plan in Cypher",
            "steps": ["Use run_cypher with correct organization scope."],
            "use_p_agent": False,
            "p_agent_instruction": None,
        }
    lines = [ln.strip() for ln in re.split(r"\n+", t) if ln.strip()]
    steps: List[str] = []
    for ln in lines:
        m = re.match(r"^\d+[.)]\s*", ln)
        if m:
            steps.append(ln[m.end() :].strip())
        else:
            steps.append(ln)
    if not steps:
        steps = [t[:1200]]
    goal = (steps[0][:500] if steps else t[:500]) or "Implement the plan in Cypher"
    return {
        "goal": goal,
        "steps": steps[:40],
        "use_p_agent": False,
        "p_agent_instruction": None,
    }


def _normalize_research_plan_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """Fill required keys when the model returns a partial dict."""
    out = dict(d)
    steps_raw = out.get("steps")
    if isinstance(steps_raw, str):
        out["steps"] = [s.strip() for s in re.split(r"\n|;", steps_raw) if s.strip()]
    elif isinstance(steps_raw, list):
        out["steps"] = [str(s) for s in steps_raw]
    else:
        out["steps"] = [str(out.get("goal", "Follow the research plan"))]
    if not out["steps"]:
        out["steps"] = ["Use run_cypher per organization scope."]
    if not out.get("goal"):
        out["goal"] = out["steps"][0][:500]
    out.setdefault("use_p_agent", False)
    out.setdefault("p_agent_instruction", None)
    return out


def _coerce_research_plan_field(v: Any) -> Any:
    """LLMs often emit research_plan as a long string; accept dict or str for validation."""
    if isinstance(v, dict):
        return _normalize_research_plan_dict(v)
    if isinstance(v, str):
        return _string_to_research_plan_dict(v)
    return v


class FinalAnswer(BaseModel):
    """R-Agent structured output when sufficient evidence exists."""

    answer: str = Field(..., description="Final answer to the user query")
    confidence: Optional[str] = Field(
        default=None,
        description="Optional confidence level or note",
    )


class CohortRAgentResponse(BaseModel):
    """Cohort Reasoning Agent: single node_type cohort + column selection + research plan for A-Agent."""

    target_node_type: str = Field(
        ...,
        description="Exact n.node_type for cohort members (one structured entity type)",
    )
    display_property_keys: List[str] = Field(
        ...,
        description="Keys inside apoc JSON properties, most important first, for shallow list columns",
    )
    identifier_property_keys: List[str] = Field(
        ...,
        description="Subset of keys best for row identity / title (ordered)",
    )
    research_plan: ResearchPlan = Field(
        ...,
        description="Self-contained plan for the Action Agent (Cypher listing of cohort members)",
    )

    @field_validator("research_plan", mode="before")
    @classmethod
    def _coerce_research_plan(cls, v: Any) -> Any:
        return _coerce_research_plan_field(v)


ScoringDirection = Literal["higher_is_better", "lower_is_better", "inverse_linear"]
MissingDataPolicy = Literal["neutral_partial_score", "penalize", "exclude"]
NormalizationType = Literal["min_max", "window", "identity", "categorical_one_hot"]


class ScoringComponent(BaseModel):
    """One weighted signal in a cohort scoring formula (properties are JSON keys on GraphNode)."""

    property_key: str = Field(..., min_length=1, description="Key inside apoc.convert.fromJsonMap(n.properties)")
    weight: float = Field(..., ge=0.0, le=1.0, description="Relative weight; cohort R should make components sum to ~1")
    # Use str (not Literal) so agent JSON-schema validation does not reject outputs before Pydantic;
    # allowed values are enforced in validators below.
    direction: str = Field(
        ...,
        description="higher_is_better | lower_is_better | inverse_linear (not normalization.type)",
    )
    normalization: Dict[str, Any] = Field(
        default_factory=dict,
        description='Must include "type" in NormalizationType; optional "params" from probe stats',
    )

    @model_validator(mode="before")
    @classmethod
    def _direction_not_normalization_type(cls, data: Any) -> Any:
        """LLMs often put normalization.type (e.g. categorical_one_hot) into direction by mistake."""
        if not isinstance(data, dict):
            return data
        d = dict(data)
        norm_types = set(get_args(NormalizationType))
        dr = d.get("direction")
        if isinstance(dr, str) and dr in norm_types:
            norm = d.get("normalization")
            if not isinstance(norm, dict):
                norm = {}
            if not norm.get("type"):
                params = norm.get("params")
                if not isinstance(params, dict):
                    params = {}
                d["normalization"] = {**norm, "type": dr, "params": params}
            else:
                d["normalization"] = norm
            d["direction"] = "higher_is_better"
        return d

    @field_validator("normalization")
    @classmethod
    def _norm_has_type(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if v and "type" in v:
            return v
        if not v:
            return {"type": "identity", "params": {}}
        return v

    @field_validator("direction", mode="after")
    @classmethod
    def _coerce_to_scoring_direction(cls, v: str) -> str:
        """Map unknown strings to a safe default; LLMs often put garbage here."""
        s = (v or "").strip()
        if s in get_args(ScoringDirection):
            return s
        if s in get_args(NormalizationType):
            return "higher_is_better"
        return "higher_is_better"


class CohortPropertyPickResponse(BaseModel):
    """Preflight: choose node_type and which keys to probe (from Schema RAG vocabulary)."""

    target_node_type: str = Field(..., min_length=1)
    candidate_property_keys: List[str] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Keys to run distribution probes on before scoring formula design",
    )


class CohortScoringRAgentResponse(BaseModel):
    """Cohort scoring: weighted formula + policy; A-Agent implements Cypher vector score."""

    target_node_type: str = Field(..., description="Exact n.node_type for scored entities")
    display_property_keys: List[str] = Field(
        default_factory=list,
        description="Shallow table columns (may include score, confidence)",
    )
    identifier_property_keys: List[str] = Field(default_factory=list)
    missing_data_policy: MissingDataPolicy = Field(
        default="neutral_partial_score",
        description="How NULL/missing JSON keys affect score and confidence",
    )
    cutoff_method: Literal["llm_iterated"] = Field(
        default="llm_iterated",
        description="Threshold chosen via sample distribution + R-Agent iteration",
    )
    components: List[ScoringComponent] = Field(
        ...,
        min_length=1,
        description="Weighted scoring components grounded in Schema RAG + probe",
    )
    research_plan: ResearchPlan = Field(
        ...,
        description="Instructions for A-Agent to implement scoring Cypher",
    )

    @field_validator("research_plan", mode="before")
    @classmethod
    def _coerce_research_plan_scoring(cls, v: Any) -> Any:
        return _coerce_research_plan_field(v)

    @model_validator(mode="after")
    def _weights_sum(self) -> "CohortScoringRAgentResponse":
        s = sum(c.weight for c in self.components)
        if s <= 0:
            raise ValueError("Sum of component weights must be positive")
        if abs(s - 1.0) > 0.15:
            # Soft warn: normalize in Cypher instructions, not fatal
            pass
        return self


class CohortCutoffRAgentResponse(BaseModel):
    """Second-pass R-Agent: chooses cutoff from score distribution + user intent."""

    recommended_cutoff: float = Field(..., ge=0.0, le=1.0)
    rationale: str = Field(default="", description="Short justification for the threshold")


class RAgentResponse(BaseModel):
    """R-Agent output: either FINAL_ANSWER or RESEARCH_PLAN (tagged union)."""

    response_type: Literal["final_answer", "research_plan"] = Field(
        ...,
        description="Discriminator for union",
    )
    answer: Optional[str] = Field(
        default=None,
        description="Present when response_type is final_answer",
    )
    confidence: Optional[str] = Field(default=None)
    research_plan: Optional[ResearchPlan] = Field(
        default=None,
        description="Present when response_type is research_plan",
    )


class AAgentCodeOutput(BaseModel):
    """A-Agent structured output: Python code string."""

    code: str = Field(..., description="Python code using RetrieveNode, NodeInfo, run_cypher (Cypher only)")


class PAgentCodeOutput(BaseModel):
    """P-Agent structured output: Python code string (runs in dataframe + predefined-functions sandbox)."""

    code: str = Field(
        ...,
        description="Python code using df and predefined analysis/plotting functions",
    )


class PAgentPlotDescription(BaseModel):
    """Description of a plot produced by P-Agent; may include image for display in chat."""

    description: str = Field(..., description="Short text description of the plot")
    image_base64: Optional[str] = Field(
        default=None,
        description="Optional PNG image as base64 for display in chat window",
    )


class ChartSpec(BaseModel):
    """JSON Bridge: chart specification for frontend to render with Recharts/Chart.js.
    P-Agent emits this via emit_chart() instead of generating images.
    """

    type: Literal["chart"] = "chart"
    chart_type: str = Field(
        ...,
        description="One of: pie, bar, line, histogram, area, scatter, radar, radialBar",
    )
    title: str = Field(default="", description="Chart title")
    data: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Data points, e.g. [{\"label\": \"A\", \"value\": 10}, ...]",
    )
    config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional axis labels etc., e.g. {\"xAxis\": \"Category\", \"yAxis\": \"Count\"}",
    )


class PAgentKnowledgeItem(BaseModel):
    """Artifact appended to current_knowledge when P-Agent runs. Summary, plots, and optional chart specs."""

    source: Literal["p_agent"] = "p_agent"
    summary: str = Field(..., description="Text summary or analysis from P-Agent stdout")
    plots: List[PAgentPlotDescription] = Field(
        default_factory=list,
        description="Short descriptions of any plots produced (no image data)",
    )
    charts: List[ChartSpec] = Field(
        default_factory=list,
        description="Chart specs from emit_chart() for frontend to render interactively",
    )


class ForgeEntityProposal(BaseModel):
    """Context Forge agent proposal for one graph entity type."""

    source_object: str = Field(..., min_length=1)
    label: str = Field(..., min_length=1)
    primary_key: Optional[List[str]] = None
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    rationale: str = Field(default="")


class ForgeRelationshipProposal(BaseModel):
    """Context Forge agent proposal for a semantic graph relationship."""

    source_object: str = Field(..., min_length=1)
    target_object: str = Field(..., min_length=1)
    source_column: Optional[str] = None
    target_column: Optional[str] = None
    label: str = Field(..., min_length=1)
    kind: str = Field(default="ai_inferred")
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    rationale: str = Field(default="")


class ForgeFactPredicateProposal(BaseModel):
    """Context Forge agent proposal for a predicate/fact column."""

    source_object: str = Field(..., min_length=1)
    source_column: str = Field(..., min_length=1)
    predicate: str = Field(..., min_length=1)
    label: str = Field(..., min_length=1)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    rationale: str = Field(default="")


class ForgeAgentResponse(BaseModel):
    """Structured Context Forge agent output."""

    entity_types: List[ForgeEntityProposal] = Field(default_factory=list)
    relationships: List[ForgeRelationshipProposal] = Field(default_factory=list)
    fact_predicates: List[ForgeFactPredicateProposal] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


# Context for synthesis: either (TraversalResult, search_results) or (NotebookState,).
# Implemented as a tagged union for type-safe handling in graph_chat.
class DeterministicContext(BaseModel):
    """Context from deterministic path (subgraph + search results)."""

    kind: Literal["deterministic"] = "deterministic"
    traversal_result: Any = Field(..., description="TraversalResult from PPR/MST")
    search_results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Graph search results",
    )


class NonDeterministicContext(BaseModel):
    """Context from non-deterministic path (notebook)."""

    kind: Literal["notebook"] = "notebook"
    notebook_state: NotebookState = Field(...)
    final_answer: Optional[str] = Field(default=None)
    # Side-car: notebook items with more than LARGE_DATA_ROW_THRESHOLD rows carry only a
    # `large_data_ref` manifest. The actual rows live here so downstream consumers (Decision
    # Trace sidebar, subgraph build, P-Agent) can rehydrate without bloating the LLM prompt.
    large_data_by_ref: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)


ContextForSynthesis = Union[DeterministicContext, NonDeterministicContext]


class GLMResult(BaseModel):
    """Result of run_glm(); carries path-agnostic context_for_synthesis."""

    context_for_synthesis: ContextForSynthesis = Field(
        ...,
        description="Unified context for GraphContextFormatter",
    )
    classification_reason: Optional[str] = Field(
        default=None,
        description="C-Agent reason when available",
    )


class GLMCohortResult(BaseModel):
    """Result of run_cohort_glm() or run_cohort_scoring_glm(): listing and/or scoring artifacts."""

    cohort_plan: Optional[CohortRAgentResponse] = Field(
        default=None,
        description="Structured output from the cohort R-Agent (list mode)",
    )
    scoring_plan: Optional[CohortScoringRAgentResponse] = Field(
        default=None,
        description="Weighted scoring plan (scoring mode)",
    )
    distribution_summary: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Probe aggregates: per-key categorical % and numeric summaries",
    )
    score_distribution: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Aggregates over computed final_score (histogram / quantiles)",
    )
    cutoff_value: Optional[float] = Field(
        default=None,
        description="Last LLM-iterated score threshold",
    )
    cutoff_rationale: Optional[str] = Field(default=None)
    cutoff_iterations_used: int = Field(
        default=0,
        description="How many cutoff refinement rounds ran",
    )
    cypher_query: Optional[str] = Field(
        default=None,
        description="Last successful listing or scoring query from the executor",
    )
    sample_rows: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Rows returned by that query (capped)",
    )
    notebook_state: Optional[NotebookState] = Field(
        default=None,
        description="Notebook after A-Agent + executor (for debugging)",
    )
    error: Optional[str] = Field(
        default=None,
        description="Fatal error message if the pipeline could not complete",
    )
    warning: Optional[str] = Field(
        default=None,
        description="Non-fatal note (e.g. 0 rows after validation retries — likely filter/date/business-logic issue)",
    )
