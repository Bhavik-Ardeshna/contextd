"""Cohort scoring GLM runner."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from contextd_adk.agent import AgentRunner
from contextd_adk.agent.config import RunnerConfig

from contextd.api.context import ApiContext
from contextd.core.logging import LoggerConfigurator
from contextd.platform.agent_orchestration.agents import create_a_agent, create_glm_run_context
from contextd.platform.agent_orchestration.cohort.agents import (
    CohortAgentStage,
    create_cohort_agent,
)
from contextd.platform.agent_orchestration.cohort.cutoff import (
    run_cohort_cutoff_refinement,
)
from contextd.platform.agent_orchestration.cohort.probe import (
    fetch_distribution_summary,
    score_distribution_from_rows,
)
from contextd.platform.agent_orchestration.cohort.runtime import (
    resolve_vector_size,
    zero_div_retry_hint,
)
from contextd.platform.agent_orchestration.cohort.validation import (
    COHORT_SCORING_RETURN_RETRY_HINT,
    COHORT_SCORING_ZERO_ROW_FINAL_WARNING,
    cohort_scoring_zero_rows_followup_message,
    conversation_from_agent_response,
    pick_scoring_cypher_and_rows,
    validate_cohort_scoring_rows,
)
from contextd.platform.agent_orchestration.prompts import (
    build_a_agent_user_message,
    build_cohort_property_pick_user_message,
    build_cohort_scoring_r_user_message,
    get_a_agent_cohort_scoring_system_prompt,
    get_r_agent_cohort_property_pick_prompt,
    get_r_agent_cohort_scoring_system_prompt,
)
from contextd.platform.agent_orchestration.runtime.executor import run_executor
from contextd.platform.agent_orchestration.runtime.settings import (
    MAX_A_AGENT_CORRECTION_RETRIES,
)
from contextd.platform.agent_orchestration.types import (
    CohortPropertyPickResponse,
    CohortScoringRAgentResponse,
    GLMCohortResult,
    NotebookState,
    ResearchPlan,
)

logger = LoggerConfigurator.configure_logger(__name__)
logging.getLogger("contextd_adk.agent.execution.executor").setLevel(logging.WARNING)


async def run_cohort_scoring_glm(
    query: str,
    organization_id: UUID,
    collection_id: UUID,
    ctx: ApiContext,
    *,
    vector_size: Optional[int] = None,
    pruned_schema: Optional[str] = None,
    source_type_filter: Optional[str] = None,
) -> GLMCohortResult:
    """Cohort scoring: property pick → probe → scoring R → A-Agent scoring → cutoff R loop → filtered rows."""
    runner = AgentRunner(config=RunnerConfig(persist_state=False))

    vector_size = await resolve_vector_size(
        vector_size,
        collection_id=collection_id,
        ctx=ctx,
    )

    node_types = None
    rel_types = None
    entity_property_shapes = None
    schema_narrative = None

    r_ctx_short = create_glm_run_context(
        organization_id=organization_id,
        collection_id=collection_id,
        max_turns=2,
    )
    meta = {"organization_id": str(organization_id), "collection_id": str(collection_id)}

    pick_prompt = get_r_agent_cohort_property_pick_prompt(pruned_schema)
    pick_agent = create_cohort_agent(CohortAgentStage.PROPERTY_PICK, instructions=pick_prompt)
    try:
        pick_response = await runner.run(
            pick_agent,
            build_cohort_property_pick_user_message(query, organization_id=organization_id),
            context=r_ctx_short,
            metadata=meta,
        )
    except Exception as e:
        logger.warning("Cohort property pick R-Agent failed: %s", e)
        return GLMCohortResult(error=str(e))

    pick_struct = getattr(pick_response, "structured_output", None)
    if pick_struct is None and getattr(pick_response, "content", None):
        try:
            pick_struct = CohortPropertyPickResponse.model_validate(
                json.loads(pick_response.content or "{}")
            )
        except Exception:
            pick_struct = None
    if pick_struct is None:
        return GLMCohortResult(error="Property pick R-Agent returned no structured output")
    if not isinstance(pick_struct, CohortPropertyPickResponse):
        try:
            pick_struct = CohortPropertyPickResponse.model_validate(
                pick_struct.model_dump() if hasattr(pick_struct, "model_dump") else pick_struct
            )
        except Exception as e:
            return GLMCohortResult(error=f"Invalid property pick: {e}")

    try:
        dist = await fetch_distribution_summary(
            organization_id=organization_id,
            ctx=ctx,
            node_type=pick_struct.target_node_type,
            property_keys=pick_struct.candidate_property_keys,
        )
    except Exception as e:
        logger.warning("Cohort distribution probe failed: %s", e)
        dist = {
            "target_node_type": pick_struct.target_node_type,
            "keys": {},
            "probe_error": str(e),
        }

    scoring_sys = get_r_agent_cohort_scoring_system_prompt(pruned_schema=pruned_schema)
    scoring_r_agent = create_cohort_agent(CohortAgentStage.SCORING, instructions=scoring_sys)
    try:
        scoring_response = await runner.run(
            scoring_r_agent,
            build_cohort_scoring_r_user_message(query, dist, organization_id=organization_id),
            context=r_ctx_short,
            metadata=meta,
        )
    except Exception as e:
        logger.warning("Cohort scoring R-Agent failed: %s", e)
        return GLMCohortResult(error=str(e), distribution_summary=dist)

    sr_struct = getattr(scoring_response, "structured_output", None)
    if sr_struct is None and getattr(scoring_response, "content", None):
        try:
            sr_struct = CohortScoringRAgentResponse.model_validate(
                json.loads(scoring_response.content or "{}")
            )
        except Exception:
            sr_struct = None
    if sr_struct is None:
        return GLMCohortResult(
            error="Cohort scoring R-Agent returned no structured output",
            distribution_summary=dist,
        )
    if not isinstance(sr_struct, CohortScoringRAgentResponse):
        try:
            scoring_plan = CohortScoringRAgentResponse.model_validate(
                sr_struct.model_dump() if hasattr(sr_struct, "model_dump") else sr_struct
            )
        except Exception as e:
            return GLMCohortResult(
                error=f"Invalid scoring plan: {e}",
                distribution_summary=dist,
            )
    else:
        scoring_plan = sr_struct

    rp = scoring_plan.research_plan
    rp = ResearchPlan.model_validate(rp.model_dump() if hasattr(rp, "model_dump") else rp)
    rp = ResearchPlan(
        goal=rp.goal,
        steps=rp.steps,
        use_p_agent=False,
        p_agent_instruction=rp.p_agent_instruction,
    )

    a_prompt = get_a_agent_cohort_scoring_system_prompt(
        node_types=node_types,
        rel_types=rel_types,
        entity_property_shapes=entity_property_shapes,
        source_type_filter=source_type_filter,
        schema_narrative=schema_narrative,
        pruned_schema=pruned_schema,
    )
    a_agent = create_a_agent(instructions=a_prompt)
    a_user_msg = build_a_agent_user_message(
        rp,
        node_types=node_types,
        rel_types=rel_types,
        entity_property_shapes=entity_property_shapes,
        schema_narrative=schema_narrative,
    )

    notebook = NotebookState(
        current_knowledge=[],
        missing_information=[],
        execution_history=[],
    )
    a_input: Any = a_user_msg
    a_response: Any = None
    last_cypher: Optional[str] = None
    last_rows: List[Dict[str, Any]] = []

    for a_attempt in range(MAX_A_AGENT_CORRECTION_RETRIES + 1):
        logger.info("[Cohort scoring GLM] A-Agent (scoring) attempt=%s", a_attempt + 1)
        try:
            a_response = await runner.run(
                a_agent,
                a_input,
                context=create_glm_run_context(
                    organization_id=organization_id,
                    collection_id=collection_id,
                    max_turns=5,
                ),
                metadata=meta,
            )
        except Exception as e:
            logger.warning("Cohort scoring A-Agent failed: %s", e)
            return GLMCohortResult(
                scoring_plan=scoring_plan,
                distribution_summary=dist,
                error=str(e),
                notebook_state=notebook,
            )

        a_struct = getattr(a_response, "structured_output", None)
        code = getattr(a_struct, "code", None) if a_struct else None
        if not code and getattr(a_response, "content", None):
            try:
                parsed = json.loads(a_response.content or "{}")
                code = parsed.get("code")
            except Exception:
                code = (a_response.content or "").strip()
        if not code:
            return GLMCohortResult(
                scoring_plan=scoring_plan,
                distribution_summary=dist,
                error="A-Agent produced no code",
                notebook_state=notebook,
            )

        notebook, run_errors, large_data_by_ref = await run_executor(
            code,
            notebook,
            organization_id=organization_id,
            collection_id=collection_id,
            vector_size=vector_size,
            ctx=ctx,
            plan_steps=rp.steps,
        )
        last_cypher, last_rows = pick_scoring_cypher_and_rows(notebook, large_data_by_ref)

        if run_errors:
            err_txt = "; ".join(run_errors[-5:])
            conv = conversation_from_agent_response(a_response)
            a_input = conv + [
                {
                    "role": "user",
                    "content": (
                        f"## Tool errors from last run\n{err_txt}\n\n"
                        "Fix run_cypher; each row must include node_id, a combined score, and confidence. "
                        + COHORT_SCORING_RETURN_RETRY_HINT
                        + ' Respond with valid JSON with key "code".'
                        + zero_div_retry_hint(err_txt)
                    ),
                }
            ]
            if a_attempt >= MAX_A_AGENT_CORRECTION_RETRIES:
                return GLMCohortResult(
                    scoring_plan=scoring_plan,
                    distribution_summary=dist,
                    cypher_query=last_cypher,
                    sample_rows=last_rows[:50],
                    notebook_state=notebook,
                    error=f"Cypher/tool errors: {err_txt}",
                )
            continue

        ok, shape_err = validate_cohort_scoring_rows(last_rows)
        if not ok:
            conv = conversation_from_agent_response(a_response)
            a_input = conv + [
                {
                    "role": "user",
                    "content": (
                        f"## Validation error\n{shape_err}\n\n"
                        "Fix the Cypher so every row includes node_id, a combined score column, and confidence. "
                        + COHORT_SCORING_RETURN_RETRY_HINT
                        + ' Respond with valid JSON with key "code".'
                    ),
                }
            ]
            if a_attempt >= MAX_A_AGENT_CORRECTION_RETRIES:
                return GLMCohortResult(
                    scoring_plan=scoring_plan,
                    distribution_summary=dist,
                    cypher_query=last_cypher,
                    sample_rows=last_rows[:50],
                    notebook_state=notebook,
                    error=shape_err or "Invalid scoring cohort rows",
                )
            continue

        if last_rows:
            break

        conv = conversation_from_agent_response(a_response)
        a_input = conv + [
            {"role": "user", "content": cohort_scoring_zero_rows_followup_message(last_cypher)},
        ]
        if a_attempt >= MAX_A_AGENT_CORRECTION_RETRIES:
            return GLMCohortResult(
                scoring_plan=scoring_plan,
                distribution_summary=dist,
                cypher_query=last_cypher,
                sample_rows=[],
                notebook_state=notebook,
                error=None,
                warning=COHORT_SCORING_ZERO_ROW_FINAL_WARNING,
            )
        continue

    if not last_rows:
        return GLMCohortResult(
            scoring_plan=scoring_plan,
            distribution_summary=dist,
            cypher_query=last_cypher,
            sample_rows=[],
            notebook_state=notebook,
            error=None,
            warning=COHORT_SCORING_ZERO_ROW_FINAL_WARNING,
        )

    base_sd = score_distribution_from_rows(last_rows)
    cutoff_result = await run_cohort_cutoff_refinement(
        runner=runner,
        a_agent=a_agent,
        last_a_response=a_response,
        query=query,
        organization_id=organization_id,
        collection_id=collection_id,
        ctx=ctx,
        meta=meta,
        vector_size=vector_size,
        notebook=notebook,
        plan_steps=rp.steps,
        base_score_distribution=base_sd,
        initial_cypher=last_cypher,
        initial_rows=last_rows,
    )

    return GLMCohortResult(
        scoring_plan=scoring_plan,
        distribution_summary=dist,
        score_distribution=base_sd,
        cutoff_value=cutoff_result.cutoff_value,
        cutoff_rationale=cutoff_result.cutoff_rationale,
        cutoff_iterations_used=cutoff_result.iterations_used,
        cypher_query=cutoff_result.cypher_query,
        sample_rows=cutoff_result.rows[:50],
        notebook_state=cutoff_result.notebook_state,
        error=None,
        warning=cutoff_result.warning,
    )
