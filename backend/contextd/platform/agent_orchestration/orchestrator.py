"""GLM orchestrator entry points and cohort runners."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from contextd_adk.agent.utils.message_utils import message_to_dict

from contextd.api.context import ApiContext
from contextd.core.logging import LoggerConfigurator
from contextd.platform.agent_orchestration.agents import (
    create_a_agent,
    create_glm_run_context,
    create_p_agent,
    create_r_agent,
)
from contextd.platform.agent_orchestration.cohort.listing import run_cohort_glm
from contextd.platform.agent_orchestration.cohort.scoring import run_cohort_scoring_glm
from contextd.platform.agent_orchestration.p_agent_functions import sanitize_p_agent_stdout_for_llm
from contextd.platform.agent_orchestration.prompts import (
    build_a_agent_user_message,
    build_p_agent_user_message,
    build_r_agent_user_message,
    get_a_agent_system_prompt,
    get_p_agent_system_prompt,
    get_r_agent_system_prompt,
)
from contextd.platform.agent_orchestration.runtime.executor import (
    run_executor,
)
from contextd.platform.agent_orchestration.runtime.p_agent import (
    list_cypher_datasets_for_p_agent,
    run_p_executor,
)
from contextd.platform.agent_orchestration.runtime.settings import (
    MAX_A_AGENT_CORRECTION_RETRIES,
    MAX_P_AGENT_CORRECTION_RETRIES,
)
from contextd.platform.agent_orchestration.types import (
    ChartSpec,
    GLMResult,
    NonDeterministicContext,
    NotebookState,
    PAgentKnowledgeItem,
    RAgentResponse,
    ResearchPlan,
)

logger = LoggerConfigurator.configure_logger(__name__)

# Reduce noise from ContextD ADK (JSON mode, validation, memory config)
for _adk_logger in (
    "contextd_adk.agent.execution.executor",
    "contextd_adk.agent.execution.message_builder",
    "contextd_adk.llm.client",
):
    logging.getLogger(_adk_logger).setLevel(logging.WARNING)


async def run_glm(
    query: str,
    organization_id: UUID,
    collection_id: UUID,
    ctx: ApiContext,
    *,
    readable_id: str = "",
    max_glm_loops: int = 5,
    search_limit: int = 10,
    max_depth: int = 2,
    node_limit: int = 100,
    vector_size: Optional[int] = None,
    business_logic: Optional[Any] = None,
    source_type_filter: Optional[str] = None,
    pruned_schema: Optional[str] = None,
) -> GLMResult:
    """Main entry point: all queries use the non-deterministic path (R-Agent → A-Agent → Executor).

    pruned_schema: When set (from schema RAG), used as vocabulary and property context; Cypher uses anonymous relationships.
    business_logic: Legacy; used only when pruned_schema is not provided.
    source_type_filter: When set, restricts search and Cypher to this connector.
    """
    from contextd_adk.agent import AgentRunner
    from contextd_adk.agent.config import RunnerConfig

    runner = AgentRunner(config=RunnerConfig(persist_state=False))

    # Resolve vector_size once (needed for non-deterministic path)
    if vector_size is None:
        from contextd import crud
        from contextd.db.session import get_db_context

        async with get_db_context() as db:
            coll = await crud.collection.get(db, id=collection_id, ctx=ctx)
            vector_size = getattr(coll, "vector_size", 1536) if coll else 1536

    logger.info("[GLM] Executing non-deterministic path (R-Agent → A-Agent → Executor)")
    if pruned_schema:
        node_types = None
        rel_types = None
        entity_property_shapes = None
        schema_narrative = None
        logger.info("[GLM] Using pruned schema from RAG (anonymous relationships in Cypher)")
    else:
        node_types = business_logic.node_types if business_logic else None
        rel_types = business_logic.rel_types if business_logic else None
        entity_property_shapes = business_logic.entity_property_shapes if business_logic else None
        schema_narrative = business_logic.schema_narrative if business_logic else None
        connector_src = f"@{source_type_filter}" if source_type_filter else "collection sources"
        logger.info(
            "[GLM] Connector filter: %s | vocabulary: %s | node_types: %s",
            connector_src,
            "dynamic" if node_types else "discover from graph",
            node_types if node_types else "(model must run RETURN DISTINCT n.node_type)",
        )
    r_prompt = get_r_agent_system_prompt(
        node_types=node_types,
        rel_types=rel_types,
        entity_property_shapes=entity_property_shapes,
        source_type_filter=source_type_filter,
        schema_narrative=schema_narrative,
        pruned_schema=pruned_schema,
    )
    a_prompt = get_a_agent_system_prompt(
        node_types=node_types,
        rel_types=rel_types,
        entity_property_shapes=entity_property_shapes,
        source_type_filter=source_type_filter,
        schema_narrative=schema_narrative,
        pruned_schema=pruned_schema,
    )

    # Log the schema/vocabulary context passed to the LLM (for debugging and observability)
    if pruned_schema and pruned_schema.strip():
        ps = pruned_schema.strip()
        _log_max = 2000
        if len(ps) > _log_max:
            ps_log = (
                ps[:_log_max]
                + f"\n... [{len(ps) - _log_max} more chars omitted from log; full schema is sent to the LLM]"
            )
        else:
            ps_log = ps
        logger.info(
            "[GLM] Business logic passed to LLM (pruned schema from RAG):\n%s",
            ps_log,
        )
    else:
        logger.info(
            "[GLM] Business logic passed to LLM (legacy): node_types=%s | rel_types=%s | "
            "entity_property_shapes=%s | schema_narrative=%s",
            node_types,
            rel_types,
            entity_property_shapes,
            (schema_narrative[:500] + "...")
            if schema_narrative and len(schema_narrative) > 500
            else schema_narrative,
        )

    r_agent = create_r_agent(instructions=r_prompt)
    a_agent = create_a_agent(instructions=a_prompt)

    # Pull user identity from ApiContext so relative terms ("my", "yesterday") resolve.
    user_email = ctx.user.email if ctx.user else None
    user_name = ctx.user.full_name if ctx.user else None

    notebook = NotebookState(
        current_knowledge=[],
        missing_information=[],
        execution_history=[],
    )
    large_data_store: Dict[str, List[Dict[str, Any]]] = {}
    final_answer: Optional[str] = None

    # GraphSearch (seed) + graph expansion run only when executor runs RetrieveNode(text), not upfront.

    for _ in range(max_glm_loops):
        r_ctx = create_glm_run_context(
            organization_id=organization_id,
            collection_id=collection_id,
            max_turns=2,
        )
        user_msg = build_r_agent_user_message(
            query,
            notebook,
            organization_id=organization_id,
            user_email=user_email,
            user_name=user_name,
        )
        logger.info("[GLM] Agent called: R-Agent (reasoning)")
        try:
            r_response = await runner.run(
                r_agent,
                user_msg,
                context=r_ctx,
                metadata={
                    "organization_id": str(organization_id),
                    "collection_id": str(collection_id),
                },
            )
            r_out = "(none)"
            if getattr(r_response, "structured_output", None):
                r_out = (
                    getattr(r_response.structured_output, "response_type", "")
                    or str(r_response.structured_output)[:150]
                )
            elif getattr(r_response, "content", None):
                r_out = (r_response.content or "")[:150]
            logger.info("[GLM] R-Agent output: %s", r_out)
        except Exception as e:
            logger.warning("R-Agent run failed: %s", e)
            break

        r_struct = getattr(r_response, "structured_output", None)
        if r_struct is None and r_response.content:
            try:
                r_struct = RAgentResponse.model_validate(json.loads(r_response.content))
            except Exception:
                pass

        if r_struct and getattr(r_struct, "response_type", None) == "final_answer":
            final_answer = getattr(r_struct, "answer", None) or (r_response.content or "")
            break

        if r_struct and getattr(r_struct, "response_type", None) == "research_plan":
            rp = getattr(r_struct, "research_plan", None)
            if rp is None:
                break
            if not isinstance(rp, ResearchPlan):
                rp = ResearchPlan.model_validate(
                    rp.model_dump() if hasattr(rp, "model_dump") else rp
                )
            # A-Agent runs with chat history: errors go back to A-Agent in-conversation, not to notebook/R-Agent.
            a_user_msg = build_a_agent_user_message(
                rp,
                node_types=node_types,
                rel_types=rel_types,
                entity_property_shapes=entity_property_shapes,
                schema_narrative=schema_narrative,
                organization_id=organization_id,
                user_email=user_email,
                user_name=user_name,
            )
            a_input: Any = a_user_msg
            a_response = None
            last_cypher_results: List[Tuple[str, List[Dict[str, Any]]]] = []
            for a_attempt in range(MAX_A_AGENT_CORRECTION_RETRIES + 1):
                logger.info(
                    "[GLM] Agent called: A-Agent (action/code) attempt=%s",
                    a_attempt + 1,
                )
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
                    logger.warning("A-Agent run failed: %s", e)
                    break
                a_struct = getattr(a_response, "structured_output", None)
                code = getattr(a_struct, "code", None) if a_struct else None
                if not code and getattr(a_response, "content", None):
                    try:
                        parsed = json.loads(a_response.content or "{}")
                        code = parsed.get("code")
                    except Exception:
                        code = (a_response.content or "").strip()
                if not code:
                    break
                old_knowledge_len = len(notebook.current_knowledge)
                notebook, run_errors, large_data_by_ref = await run_executor(
                    code,
                    notebook,
                    organization_id=organization_id,
                    collection_id=collection_id,
                    vector_size=vector_size,
                    ctx=ctx,
                    readable_collection_id=readable_id,
                    plan_steps=getattr(rp, "steps", None) if rp else None,
                )
                large_data_store.update(large_data_by_ref)
                new_items = notebook.current_knowledge[old_knowledge_len:]
                last_cypher_results = []
                for item in new_items:
                    if not isinstance(item, dict) or item.get("cypher") is None:
                        continue
                    ref_id = item.get("large_data_ref")
                    if ref_id:
                        rows = large_data_store.get(ref_id, [])
                    else:
                        rows = item.get("rows") if isinstance(item.get("rows"), list) else []
                    last_cypher_results.append((item["cypher"], rows))
                if not run_errors:
                    break
                # Send errors back to A-Agent in the same chat (ADK conversation history).
                error_msg = (
                    "\n\n## Tool errors from last run (fix in your code)\n"
                    + "\n".join(f"- {e}" for e in run_errors[-5:])
                    + '\n\nFix the Cypher/tool usage and respond with corrected code (valid JSON with key "code").'
                )
                conv = [message_to_dict(m) for m in (getattr(a_response, "messages", None) or [])]
                conv = [m for m in conv if (m or {}).get("role") != "system"]
                a_input = conv + [{"role": "user", "content": error_msg}]
            if a_response is None:
                break

            # P-Agent: explicit request, large/plottable Cypher tables; may run on multiple queries per round
            use_p = getattr(rp, "use_p_agent", False)
            p_instruction = (
                getattr(rp, "p_agent_instruction", None)
                or "Summarise this data and highlight key patterns."
            )
            p_datasets = list_cypher_datasets_for_p_agent(last_cypher_results, use_p=use_p)
            if p_datasets:
                try:
                    import pandas as pd
                except ImportError:
                    logger.warning("Pandas not available; skipping P-Agent")
                else:
                    merged_summaries: List[str] = []
                    merged_charts: List[ChartSpec] = []
                    last_p_run_errors: List[str] = []
                    for ds_idx, (cypher_ds, rows_ds) in enumerate(p_datasets):
                        p_df = pd.DataFrame(rows_ds)
                        sample_rows = rows_ds[:3]
                        p_user_msg = build_p_agent_user_message(
                            cypher_ds,
                            sample_rows,
                            p_instruction,
                            total_rows=len(rows_ds),
                        )
                        p_agent = create_p_agent(instructions=get_p_agent_system_prompt())
                        p_input: Any = p_user_msg
                        p_artifact_this_ds = False
                        for p_attempt in range(MAX_P_AGENT_CORRECTION_RETRIES + 1):
                            logger.info(
                                "[GLM] Agent called: P-Agent (analysis) dataset=%s/%s attempt=%s",
                                ds_idx + 1,
                                len(p_datasets),
                                p_attempt + 1,
                            )
                            try:
                                p_response = await runner.run(
                                    p_agent,
                                    p_input,
                                    context=create_glm_run_context(
                                        organization_id=organization_id,
                                        collection_id=collection_id,
                                        max_turns=3,
                                    ),
                                )
                            except Exception as e:
                                logger.warning("P-Agent run failed: %s", e)
                                break
                            p_struct = getattr(p_response, "structured_output", None)
                            p_code = getattr(p_struct, "code", None) if p_struct else None
                            if not p_code and getattr(p_response, "content", None):
                                try:
                                    p_parsed = json.loads(p_response.content or "{}")
                                    p_code = p_parsed.get("code")
                                except Exception:
                                    p_code = (p_response.content or "").strip()
                            if not p_code:
                                break
                            (
                                p_stdout,
                                p_stderr,
                                p_chart_entries,
                                p_run_errors,
                            ) = await run_p_executor(p_code, p_df)
                            if not p_run_errors:
                                chart_specs_ds: List[ChartSpec] = []
                                for e in p_chart_entries:
                                    if not isinstance(e, dict) or e.get("type") != "chart":
                                        continue
                                    try:
                                        chart_specs_ds.append(
                                            ChartSpec(
                                                type="chart",
                                                chart_type=e.get("chart_type") or "bar",
                                                title=e.get("title") or "",
                                                data=e.get("data") or [],
                                                config=e.get("config"),
                                            )
                                        )
                                    except Exception:
                                        pass
                                raw_summary = (p_stdout or p_stderr or "").strip() or "No output."
                                summary_text = sanitize_p_agent_stdout_for_llm(raw_summary)
                                if len(p_datasets) > 1:
                                    summary_text = f"### Cypher result {ds_idx + 1}\n{summary_text}"
                                merged_summaries.append(summary_text)
                                merged_charts.extend(chart_specs_ds)
                                p_artifact_this_ds = True
                                logger.info(
                                    "[GLM] P-Agent dataset %s: summary_len=%s charts=%s",
                                    ds_idx + 1,
                                    len(summary_text),
                                    len(chart_specs_ds),
                                )
                                break
                            last_p_run_errors = p_run_errors
                            error_msg = (
                                "\n\n## Python execution errors (fix your code)\n"
                                + "\n".join(f"- {e}" for e in p_run_errors[-5:])
                                + '\n\nOutput valid JSON with key "code" and corrected code.'
                            )
                            conv = [
                                message_to_dict(m)
                                for m in (getattr(p_response, "messages", None) or [])
                            ]
                            conv = [m for m in conv if (m or {}).get("role") != "system"]
                            p_input = conv + [{"role": "user", "content": error_msg}]
                        if not p_artifact_this_ds:
                            logger.warning(
                                "[GLM] P-Agent did not produce a valid artifact for dataset %s; last run_errors=%s",
                                ds_idx + 1,
                                last_p_run_errors[:5]
                                if last_p_run_errors
                                else "(no execution errors captured)",
                            )
                    if merged_summaries or merged_charts:
                        p_item = PAgentKnowledgeItem(
                            source="p_agent",
                            summary="\n\n".join(merged_summaries)
                            if merged_summaries
                            else "No output.",
                            plots=[],
                            charts=merged_charts,
                        )
                        notebook = NotebookState(
                            current_knowledge=notebook.current_knowledge + [p_item.model_dump()],
                            missing_information=notebook.missing_information,
                            execution_history=notebook.execution_history,
                        )
                        logger.info(
                            "[GLM] P-Agent artifact added: datasets_ok=%s summary_len=%s charts=%s",
                            len(merged_summaries),
                            len(p_item.summary),
                            len(p_item.charts),
                        )
        else:
            break

    return GLMResult(
        context_for_synthesis=NonDeterministicContext(
            kind="notebook",
            notebook_state=notebook,
            final_answer=final_answer,
            large_data_by_ref=dict(large_data_store),
        ),
        classification_reason=None,
    )

__all__ = ["run_glm", "run_cohort_glm", "run_cohort_scoring_glm"]
