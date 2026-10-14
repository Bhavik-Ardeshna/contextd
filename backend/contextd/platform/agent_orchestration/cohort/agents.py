"""Cohort R-Agent factory definitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from contextd.platform.agent_orchestration.agents import (
    _default_agent_model,
    _get_glm_memory_config,
)
from contextd.platform.agent_orchestration.types import (
    CohortCutoffRAgentResponse,
    CohortPropertyPickResponse,
    CohortRAgentResponse,
    CohortScoringRAgentResponse,
)


class CohortAgentStage(str, Enum):
    """Supported cohort R-Agent stages."""

    PLAN = "plan"
    PROPERTY_PICK = "property_pick"
    SCORING = "scoring"
    CUTOFF = "cutoff"


@dataclass(frozen=True)
class CohortAgentSpec:
    """Runtime metadata needed to create a cohort R-Agent."""

    name: str
    description: str
    output_schema: Any


COHORT_AGENT_SPECS: dict[CohortAgentStage, CohortAgentSpec] = {
    CohortAgentStage.PLAN: CohortAgentSpec(
        name="glm-cohort-r-agent",
        description="Cohort planner: target node type, display/identifier property keys, research plan",
        output_schema=CohortRAgentResponse,
    ),
    CohortAgentStage.PROPERTY_PICK: CohortAgentSpec(
        name="glm-cohort-property-pick-r",
        description="Picks target_node_type and candidate_property_keys from schema",
        output_schema=CohortPropertyPickResponse,
    ),
    CohortAgentStage.SCORING: CohortAgentSpec(
        name="glm-cohort-scoring-r",
        description="Weighted scoring components and normalization using probe data",
        output_schema=CohortScoringRAgentResponse,
    ),
    CohortAgentStage.CUTOFF: CohortAgentSpec(
        name="glm-cohort-cutoff-r",
        description="Sets recommended score threshold from empirical distribution",
        output_schema=CohortCutoffRAgentResponse,
    ),
}


def create_cohort_agent(
    stage: CohortAgentStage | str,
    model: Optional[str] = None,
    temperature: float = 0.0,
    instructions: Optional[str] = None,
    **kwargs: Any,
) -> Any:
    """Create one of the cohort R-Agent variants from a stage enum."""
    from contextd_adk.agent import BaseAgent

    spec = COHORT_AGENT_SPECS[CohortAgentStage(stage)]
    return BaseAgent(
        name=spec.name,
        instructions=instructions or "",
        description=spec.description,
        model=_default_agent_model(model),
        temperature=temperature,
        tools=[],
        output_schema=spec.output_schema,
        enable_json_mode=True,
        memory_config=_get_glm_memory_config(),
        **kwargs,
    )
