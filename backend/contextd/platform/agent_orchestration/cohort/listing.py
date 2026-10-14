"""Cohort listing GLM runner."""

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
from contextd.platform.agent_orchestration.cohort.runtime import (
    resolve_vector_size,
    zero_div_retry_hint,
)
from contextd.platform.agent_orchestration.cohort.validation import (
    COHORT_ZERO_ROW_FINAL_WARNING,
    cohort_zero_rows_followup_message,
    conversation_from_agent_response,
    last_cypher_and_rows_from_notebook,
    validate_cohort_member_rows,
)
from contextd.platform.agent_orchestration.prompts import (
    build_a_agent_user_message,
    build_cohort_r_agent_user_message,
    get_a_agent_cohort_system_prompt,
    get_r_agent_cohort_system_prompt,
)
from contextd.platform.agent_orchestration.runtime.executor import run_executor
from contextd.platform.agent_orchestration.runtime.settings import (
    MAX_A_AGENT_CORRECTION_RETRIES,
)
from contextd.platform.agent_orchestration.types import (
    CohortRAgentResponse,
    GLMCohortResult,
    NotebookState,
    ResearchPlan,
)

logger = LoggerConfigurator.configure_logger(__name__)
logging.getLogger("contextd_adk.agent.execution.executor").setLevel(logging.WARNING)


async def run_cohort_glm(
    query: str,
    organization_id: UUID,
    collection_id: UUID,
    ctx: ApiContext,
    *,
    vector_size: Optional[int] = None,
    pruned_schema: Optional[str] = None,
    source_type_filter: Optional[str] = None,
) -> GLMCohortResult:
    """Cohort pipeline: Cohort R-Agent → A-Agent → executor; validates node_id in rows."""
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
    if pruned_schema and pruned_schema.strip():
        logger.info("[Cohort GLM] Using pruned schema from RAG")
    else:
        logger.info("[Cohort GLM] No pruned schema; vocabulary may be empty")

    r_prompt = get_r_agent_cohort_system_prompt(
        node_types=node_types,
        rel_types=rel_types,
        entity_property_shapes=entity_property_shapes,
        source_type_filter=source_type_filter,
        schema_narrative=schema_narrative,
        pruned_schema=pruned_schema,
    )
    a_prompt = get_a_agent_cohort_system_prompt(
        node_types=node_types,
        rel_types=rel_types,
        entity_property_shapes=entity_property_shapes,
        source_type_filter=source_type_filter,
        schema_narrative=schema_narrative,
        pruned_schema=pruned_schema,
    )

    r_agent = create_cohort_agent(CohortAgentStage.PLAN, instructions=r_prompt)
    a_agent = create_a_agent(instructions=a_prompt)

    notebook = NotebookState(
        current_knowledge=[],
        missing_information=[],
        execution_history=[],
    )

    r_ctx = create_glm_run_context(
        organization_id=organization_id,
        collection_id=collection_id,
        max_turns=2,
    )
    user_msg = build_cohort_r_agent_user_message(query, organization_id=organization_id)
    cohort_plan: Optional[CohortRAgentResponse] = None
    try:
        r_response = await runner.run(
            r_agent,
            user_msg,
            context=r_ctx,
            metadata={"organization_id": str(organization_id), "collection_id": str(collection_id)},
        )
    except Exception as e:
        logger.warning("Cohort R-Agent failed: %s", e)
        return GLMCohortResult(error=str(e))

    r_struct = getattr(r_response, "structured_output", None)
    if r_struct is None and getattr(r_response, "content", None):
        try:
            r_struct = CohortRAgentResponse.model_validate(json.loads(r_response.content or "{}"))
        except Exception:
            pass
    if r_struct is None:
        return GLMCohortResult(error="Cohort R-Agent returned no structured output")

    if not isinstance(r_struct, CohortRAgentResponse):
        try:
            cohort_plan = CohortRAgentResponse.model_validate(
                r_struct.model_dump() if hasattr(r_struct, "model_dump") else r_struct
            )
        except Exception as e:
            return GLMCohortResult(error=f"Invalid cohort plan: {e}")
    else:
        cohort_plan = r_struct

    rp = cohort_plan.research_plan
    rp = ResearchPlan.model_validate(rp.model_dump() if hasattr(rp, "model_dump") else rp)
    rp = ResearchPlan(
        goal=rp.goal,
        steps=rp.steps,
        use_p_agent=False,
        p_agent_instruction=rp.p_agent_instruction,
    )

    a_user_msg = build_a_agent_user_message(
        rp,
        node_types=node_types,
        rel_types=rel_types,
        entity_property_shapes=entity_property_shapes,
        schema_narrative=schema_narrative,
    )
    a_input: Any = a_user_msg
    a_response = None
    last_cypher: Optional[str] = None
    last_rows: List[Dict[str, Any]] = []

    for a_attempt in range(MAX_A_AGENT_CORRECTION_RETRIES + 1):
        logger.info("[Cohort GLM] A-Agent attempt=%s", a_attempt + 1)
        try:
            a_response = await runner.run(
                a_agent,
                a_input,
                context=create_glm_run_context(
                    organization_id=organization_id,
                    collection_id=collection_id,
                    max_turns=5,
                ),
            )
        except Exception as e:
            logger.warning("Cohort A-Agent failed: %s", e)
            return GLMCohortResult(
                cohort_plan=cohort_plan,
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
                cohort_plan=cohort_plan,
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
        last_cypher, last_rows = last_cypher_and_rows_from_notebook(notebook, large_data_by_ref)

        if run_errors:
            err_txt = "; ".join(run_errors[-5:])
            conv = conversation_from_agent_response(a_response)
            a_input = conv + [
                {
                    "role": "user",
                    "content": (
                        f"## Tool errors from last run\n{err_txt}\n\n"
                        "Fix run_cypher and ensure each row has node_id. "
                        'Respond with valid JSON with key "code".' + zero_div_retry_hint(err_txt)
                    ),
                }
            ]
            if a_attempt >= MAX_A_AGENT_CORRECTION_RETRIES:
                return GLMCohortResult(
                    cohort_plan=cohort_plan,
                    cypher_query=last_cypher,
                    sample_rows=last_rows[:50],
                    notebook_state=notebook,
                    error=f"Cypher/tool errors: {err_txt}",
                )
            continue

        ok, shape_err = validate_cohort_member_rows(last_rows)
        if not ok:
            conv = conversation_from_agent_response(a_response)
            a_input = conv + [
                {
                    "role": "user",
                    "content": (
                        f"## Validation error\n{shape_err}\n\n"
                        "Fix the Cypher so every RETURN row includes node_id. "
                        'Respond with valid JSON with key "code".'
                    ),
                }
            ]
            if a_attempt >= MAX_A_AGENT_CORRECTION_RETRIES:
                return GLMCohortResult(
                    cohort_plan=cohort_plan,
                    cypher_query=last_cypher,
                    sample_rows=last_rows[:50],
                    notebook_state=notebook,
                    error=shape_err or "Invalid cohort rows",
                )
            continue

        # Shape OK: either we have members, or empty result (suspicious)
        if last_rows:
            return GLMCohortResult(
                cohort_plan=cohort_plan,
                cypher_query=last_cypher,
                sample_rows=last_rows[:50],
                notebook_state=notebook,
                error=None,
                warning=None,
            )

        # Zero rows: retry with diagnostic instructions (same retry budget)
        conv = conversation_from_agent_response(a_response)
        a_input = conv + [
            {"role": "user", "content": cohort_zero_rows_followup_message(last_cypher)},
        ]
        if a_attempt >= MAX_A_AGENT_CORRECTION_RETRIES:
            return GLMCohortResult(
                cohort_plan=cohort_plan,
                cypher_query=last_cypher,
                sample_rows=[],
                notebook_state=notebook,
                error=None,
                warning=COHORT_ZERO_ROW_FINAL_WARNING,
            )
        continue

    return GLMCohortResult(
        cohort_plan=cohort_plan,
        error="A-Agent produced no valid cohort listing",
        notebook_state=notebook,
    )
