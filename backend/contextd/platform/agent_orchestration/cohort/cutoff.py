"""Cutoff refinement loop for cohort scoring GLM."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from uuid import UUID

from contextd_adk.agent import AgentRunner

from contextd.api.context import ApiContext
from contextd.core.logging import LoggerConfigurator
from contextd.platform.agent_orchestration.agents import create_glm_run_context
from contextd.platform.agent_orchestration.cohort.agents import (
    CohortAgentStage,
    create_cohort_agent,
)
from contextd.platform.agent_orchestration.cohort.runtime import (
    COHORT_CUTOFF_EPS,
    MAX_COHORT_CUTOFF_ITER,
    zero_div_retry_hint,
)
from contextd.platform.agent_orchestration.cohort.validation import (
    COHORT_SCORING_RETURN_RETRY_HINT,
    cohort_scoring_cutoff_apply_message,
    conversation_from_agent_response,
    filter_rows_by_score_cutoff,
    pick_scoring_cypher_and_rows,
    validate_cohort_scoring_rows,
)
from contextd.platform.agent_orchestration.prompts import (
    build_cohort_cutoff_r_user_message,
    get_r_agent_cohort_cutoff_system_prompt,
)
from contextd.platform.agent_orchestration.runtime.executor import run_executor
from contextd.platform.agent_orchestration.runtime.settings import (
    MAX_A_AGENT_CORRECTION_RETRIES,
)
from contextd.platform.agent_orchestration.types import (
    CohortCutoffRAgentResponse,
    NotebookState,
)

logger = LoggerConfigurator.configure_logger(__name__)
logging.getLogger("contextd_adk.agent.execution.executor").setLevel(logging.WARNING)


@dataclass
class CohortCutoffResult:
    """Output from the iterative cutoff refinement loop."""

    cypher_query: Optional[str]
    rows: List[Dict[str, Any]]
    cutoff_value: Optional[float]
    cutoff_rationale: Optional[str]
    iterations_used: int
    notebook_state: NotebookState
    warning: Optional[str]


async def run_cohort_cutoff_refinement(
    *,
    runner: AgentRunner,
    a_agent: Any,
    last_a_response: Any,
    query: str,
    organization_id: UUID,
    collection_id: UUID,
    ctx: ApiContext,
    meta: Dict[str, str],
    vector_size: int,
    notebook: NotebookState,
    plan_steps: List[str],
    base_score_distribution: Dict[str, Any],
    initial_cypher: Optional[str],
    initial_rows: List[Dict[str, Any]],
) -> CohortCutoffResult:
    """Iteratively ask the cutoff agent for a threshold and apply it through A-Agent."""
    base_sd = base_score_distribution
    last_cypher = initial_cypher
    last_rows = initial_rows
    cutoff_r_agent = create_cohort_agent(
        CohortAgentStage.CUTOFF, instructions=get_r_agent_cohort_cutoff_system_prompt()
    )
    filtered_cypher = last_cypher
    filtered_rows: List[Dict[str, Any]] = list(last_rows)
    final_cutoff: Optional[float] = None
    cutoff_rationale = ""
    iterations_used = 0
    last_applied: Optional[float] = None
    warning_parts: List[str] = []

    for it in range(MAX_COHORT_CUTOFF_ITER):
        try:
            co_resp = await runner.run(
                cutoff_r_agent,
                build_cohort_cutoff_r_user_message(
                    query,
                    base_sd,
                    prior_cutoff=last_applied,
                    iteration=it,
                    organization_id=organization_id,
                ),
                context=create_glm_run_context(
                    organization_id=organization_id,
                    collection_id=collection_id,
                    max_turns=3,
                ),
                metadata=meta,
            )
        except Exception as e:
            logger.warning("Cohort cutoff R-Agent failed: %s", e)
            warning_parts.append(f"Cutoff R-Agent failed: {e}")
            break

        co_struct = getattr(co_resp, "structured_output", None)
        if co_struct is None and getattr(co_resp, "content", None):
            try:
                co_struct = CohortCutoffRAgentResponse.model_validate(
                    json.loads(co_resp.content or "{}")
                )
            except Exception:
                co_struct = None
        if co_struct is None:
            warning_parts.append("Cutoff R-Agent returned no structured output")
            break
        if not isinstance(co_struct, CohortCutoffRAgentResponse):
            try:
                co = CohortCutoffRAgentResponse.model_validate(
                    co_struct.model_dump() if hasattr(co_struct, "model_dump") else co_struct
                )
            except Exception as e:
                warning_parts.append(f"Invalid cutoff response: {e}")
                break
        else:
            co = co_struct

        cand = co.recommended_cutoff
        cutoff_rationale = co.rationale
        iterations_used = it + 1
        final_cutoff = cand

        if last_applied is not None and abs(last_applied - cand) < COHORT_CUTOFF_EPS:
            break

        applied_via_a = False
        cutoff_a_input: Any = conversation_from_agent_response(last_a_response) + [
            {
                "role": "user",
                "content": cohort_scoring_cutoff_apply_message(filtered_cypher, cand),
            }
        ]

        for a_attempt in range(MAX_A_AGENT_CORRECTION_RETRIES + 1):
            try:
                a_resp_c = await runner.run(
                    a_agent,
                    cutoff_a_input,
                    context=create_glm_run_context(
                        organization_id=organization_id,
                        collection_id=collection_id,
                        max_turns=5,
                    ),
                    metadata=meta,
                )
            except Exception as e:
                warning_parts.append(f"Cutoff A-Agent failed: {e}")
                a_resp_c = None
                break

            a_st = getattr(a_resp_c, "structured_output", None)
            code_c = getattr(a_st, "code", None) if a_st else None
            if not code_c and getattr(a_resp_c, "content", None):
                try:
                    parsed_c = json.loads(a_resp_c.content or "{}")
                    code_c = parsed_c.get("code")
                except Exception:
                    code_c = (a_resp_c.content or "").strip()
            if not code_c:
                break

            notebook, run_errors, large_data_by_ref = await run_executor(
                code_c,
                notebook,
                organization_id=organization_id,
                collection_id=collection_id,
                vector_size=vector_size,
                ctx=ctx,
                plan_steps=plan_steps,
            )
            cy, rows = pick_scoring_cypher_and_rows(notebook, large_data_by_ref)

            if run_errors:
                err_txt = "; ".join(run_errors[-5:])
                conv_c = conversation_from_agent_response(a_resp_c)
                cutoff_a_input = conv_c + [
                    {
                        "role": "user",
                        "content": (
                            f"## Tool errors from last run\n{err_txt}\n\n"
                            "Fix run_cypher and the cutoff parameter. "
                            'Respond with valid JSON with key "code".'
                            + zero_div_retry_hint(err_txt)
                        ),
                    }
                ]
                if a_attempt >= MAX_A_AGENT_CORRECTION_RETRIES:
                    warning_parts.append(f"Cutoff Cypher errors: {err_txt}")
                else:
                    continue
                break

            ok_c, shape_err_c = validate_cohort_scoring_rows(rows)
            if not ok_c:
                conv_c = conversation_from_agent_response(a_resp_c)
                cutoff_a_input = conv_c + [
                    {
                        "role": "user",
                        "content": (
                            f"## Validation error\n{shape_err_c}\n\n"
                            + COHORT_SCORING_RETURN_RETRY_HINT
                            + ' Respond with valid JSON with key "code".'
                        ),
                    }
                ]
                if a_attempt >= MAX_A_AGENT_CORRECTION_RETRIES:
                    warning_parts.append(shape_err_c or "Invalid cutoff rows")
                else:
                    continue
                break

            applied_via_a = True
            last_a_response = a_resp_c
            filtered_cypher = cy
            filtered_rows = rows
            break

        if not applied_via_a:
            filtered_rows = filter_rows_by_score_cutoff(last_rows, cand)
            filtered_cypher = last_cypher
            warning_parts.append(
                "Score cutoff applied in post-processing; stored Cypher may not include the predicate."
            )

        last_applied = cand

    merged_warn = "; ".join(warning_parts) if warning_parts else None

    merged_warn = "; ".join(warning_parts) if warning_parts else None
    return CohortCutoffResult(
        cypher_query=filtered_cypher,
        rows=filtered_rows,
        cutoff_value=final_cutoff,
        cutoff_rationale=cutoff_rationale or None,
        iterations_used=iterations_used,
        notebook_state=notebook,
        warning=merged_warn,
    )
