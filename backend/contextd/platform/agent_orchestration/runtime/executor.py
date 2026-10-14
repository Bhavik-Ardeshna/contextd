"""Sandboxed A-Agent executor for GLM runtime."""

from __future__ import annotations

import asyncio
import builtins as py_builtins
import concurrent.futures
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from contextd.api.context import ApiContext
from contextd.core.logging import LoggerConfigurator
from contextd.platform.agent_orchestration.runtime.sandbox import (
    SANDBOX_BUILTINS,
    sandbox_safe_div,
    sandbox_safe_mean,
)
from contextd.platform.agent_orchestration.runtime.settings import (
    EXECUTOR_TIMEOUT_SECONDS,
    LARGE_DATA_ROW_THRESHOLD,
    MAX_TOOL_CALLS_PER_RUN,
    TOOL_SUBCALL_TIMEOUT_SECONDS,
)
from contextd.platform.agent_orchestration.tools import graph_sql, node_info, retrieve_node
from contextd.platform.agent_orchestration.types import (
    ExecutionRecord,
    NotebookState,
    ToolOutput,
)

logger = LoggerConfigurator.configure_logger(__name__)


def _run_sandbox_in_thread(
    code: str,
    organization_id: UUID,
    collection_id: UUID,
    readable_collection_id: str,
    vector_size: int,
    ctx: ApiContext,
    timeout_seconds: int,
    main_loop: asyncio.AbstractEventLoop,
) -> Tuple[List[ToolOutput], Optional[str], Optional[str], Optional[str]]:
    """Run generated code in a thread, while async tools execute on the main loop."""
    import io
    import json as json_module
    import sys

    tool_outputs: List[ToolOutput] = []

    def _sandbox_import(
        name: str,
        globals: Any = None,
        locals: Any = None,
        fromlist: Any = (),
        level: int = 0,
    ) -> Any:
        """Allow only json imports from generated code."""
        if name == "json":
            return json_module
        raise ImportError(
            f"Sandbox allows only 'import json' or no imports (got {name!r}). "
            "Use run_cypher, RetrieveNode, NodeInfo, print, json, safe_div, and safe_mean only."
        )

    tool_timeout = min(TOOL_SUBCALL_TIMEOUT_SECONDS, max(1, timeout_seconds))

    def sync_retrieve_node(text: str) -> List[Dict[str, Any]]:
        coro = retrieve_node(
            text,
            organization_id,
            collection_id,
            vector_size,
            ctx,
            readable_collection_id=readable_collection_id,
            limit=20,
        )
        future = asyncio.run_coroutine_threadsafe(coro, main_loop)
        try:
            result = future.result(timeout=tool_timeout)
        except Exception as e:
            logger.warning("RetrieveNode failed in sandbox: %s", e)
            return []
        for result_item in result:
            tool_outputs.append(
                ToolOutput(
                    tool_name="RetrieveNode",
                    result=result_item,
                    node_ids=[result_item.get("node_id")] if result_item.get("node_id") else [],
                    raw=result_item,
                )
            )
        return result

    def sync_node_info(node_ids_list: List[str]) -> List[Dict[str, Any]]:
        coro = node_info(
            node_ids_list,
            organization_id,
            ctx,
            readable_collection_id=readable_collection_id,
        )
        future = asyncio.run_coroutine_threadsafe(coro, main_loop)
        try:
            result = future.result(timeout=tool_timeout)
        except Exception as e:
            logger.warning("NodeInfo failed in sandbox: %s", e)
            return []
        for result_item in result:
            tool_outputs.append(
                ToolOutput(
                    tool_name="NodeInfo",
                    result=result_item,
                    node_ids=[result_item.get("node_id")] if result_item.get("node_id") else [],
                    raw=result_item,
                )
            )
        return result

    def sync_run_cypher(
        cypher: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        coro = graph_sql(
            cypher,
            organization_id,
            ctx,
            params=params,
            readable_collection_id=readable_collection_id,
        )
        future = asyncio.run_coroutine_threadsafe(coro, main_loop)
        try:
            result = future.result(timeout=tool_timeout)
        except Exception as e:
            logger.warning(
                "run_cypher failed in sandbox: %s. Full Cypher query:\n%s",
                e,
                cypher,
            )
            tool_outputs.append(
                ToolOutput(
                    tool_name="run_cypher",
                    result=[],
                    node_ids=[],
                    raw={
                        "rows": [],
                        "error": str(e),
                        "cypher": cypher,
                        "params": params or {},
                    },
                )
            )
            return []
        tool_outputs.append(
            ToolOutput(
                tool_name="run_cypher",
                result=result,
                node_ids=[],
                raw={"rows": result, "cypher": cypher, "params": params or {}},
            )
        )
        return result

    builtins: Dict[str, Any] = {
        **SANDBOX_BUILTINS,
        "__import__": _sandbox_import,
        "print": py_builtins.print,
        "safe_div": sandbox_safe_div,
        "safe_mean": sandbox_safe_mean,
        "json": json_module,
        "RetrieveNode": sync_retrieve_node,
        "NodeInfo": sync_node_info,
        "run_cypher": sync_run_cypher,
        "graphSQL": sync_run_cypher,
    }

    stdout_io = io.StringIO()
    stderr_io = io.StringIO()
    exec_error: List[Optional[str]] = [None]

    def run() -> None:
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = stdout_io, stderr_io
        try:
            exec(code, {"__builtins__": builtins})
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            exec_error[0] = err
            logger.warning("A-Agent sandbox exec failed: %s", err)
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run)
        try:
            future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError:
            logger.warning("Sandbox execution timed out after %s s", timeout_seconds)
            exec_error[0] = exec_error[0] or f"Timeout after {timeout_seconds}s"
        except Exception as e:
            logger.warning("Sandbox execution failed: %s", e)
            exec_error[0] = exec_error[0] or f"{type(e).__name__}: {e}"

    return (
        tool_outputs,
        stdout_io.getvalue() or None,
        stderr_io.getvalue() or None,
        exec_error[0],
    )


async def run_executor(
    code: str,
    notebook: NotebookState,
    organization_id: UUID,
    collection_id: UUID,
    vector_size: int,
    ctx: ApiContext,
    *,
    readable_collection_id: str = "",
    timeout_seconds: int = EXECUTOR_TIMEOUT_SECONDS,
    plan_steps: Optional[List[str]] = None,
) -> Tuple[NotebookState, List[str], Dict[str, List[Dict[str, Any]]]]:
    """Run A-Agent generated code and merge tool results into the notebook."""
    if not readable_collection_id:
        try:
            from sqlalchemy import select

            from contextd.db.session import get_db_context
            from contextd.models.collection import Collection

            async with get_db_context() as db:
                result = await db.execute(
                    select(Collection.readable_id).where(Collection.id == collection_id)
                )
                readable_collection_id = str(result.scalar_one_or_none() or "")
        except Exception as exc:
            logger.debug("Could not resolve readable collection id for executor: %s", exc)

    main_loop = asyncio.get_running_loop()
    (
        tool_outputs,
        stdout_str,
        stderr_str,
        exec_err,
    ) = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: _run_sandbox_in_thread(
            code,
            organization_id,
            collection_id,
            readable_collection_id,
            vector_size,
            ctx,
            timeout_seconds,
            main_loop,
        ),
    )

    run_errors: List[str] = []
    if exec_err:
        run_errors.append(exec_err)
    suspicious_empty_results: List[str] = []
    new_knowledge = list(notebook.current_knowledge)
    large_data_by_ref: Dict[str, List[Dict[str, Any]]] = {}
    cypher_result_index = 0

    for output in tool_outputs[:MAX_TOOL_CALLS_PER_RUN]:
        if output.raw is not None:
            raw = output.raw
            if isinstance(raw, dict) and raw.get("error"):
                run_errors.append(raw["error"])
                continue
            if isinstance(raw, dict) and "cypher" in raw and "rows" in raw:
                intent = "General Query"
                if plan_steps and cypher_result_index < len(plan_steps):
                    intent = (plan_steps[cypher_result_index] or "General Query")[:200]
                cypher_result_index += 1
                rows = raw.get("rows") or []
                cypher = raw.get("cypher") or ""
                cols = list(rows[0].keys()) if rows else []
                is_empty_result = len(rows) == 0
                if len(rows) > LARGE_DATA_ROW_THRESHOLD:
                    ref_id = f"cypher_{len(new_knowledge)}_{len(large_data_by_ref)}"
                    large_data_by_ref[ref_id] = rows
                    new_knowledge.append(
                        {
                            "type": "cypher_result",
                            "cypher": cypher,
                            "row_count": len(rows),
                            "columns": cols,
                            "large_data_ref": ref_id,
                            "intent": intent,
                            "empty_result": is_empty_result,
                        }
                    )
                else:
                    new_knowledge.append(
                        {
                            **raw,
                            "intent": intent,
                            "row_count": len(rows),
                            "columns": cols,
                            "empty_result": is_empty_result,
                        }
                    )
                if is_empty_result:
                    suspicious_empty_results.append(
                        f"Cypher query for intent '{intent}' returned 0 rows and may need "
                        "validation (wrong node_type/property/filter)."
                    )
            else:
                new_knowledge.append(raw)
        elif output.result is not None:
            new_knowledge.append(
                {
                    "tool": output.tool_name,
                    "result": output.result,
                    "node_ids": output.node_ids,
                }
            )

    if run_errors:
        new_knowledge.append(
            {
                "type": "execution_note",
                "note": "Python sandbox or Cypher execution failed.",
                "errors": list(run_errors),
            }
        )
    if suspicious_empty_results:
        new_knowledge.append(
            {
                "type": "execution_note",
                "note": (
                    "One or more Cypher executions returned 0 rows and may be logically "
                    "incorrect."
                ),
                "errors": list(suspicious_empty_results),
            }
        )

    output_summary = f"tools_called={len(tool_outputs)}"
    if suspicious_empty_results:
        output_summary += f" suspicious_empty_results={len(suspicious_empty_results)}"
    if stdout_str:
        output_summary += f" stdout_len={len(stdout_str)}"
    if stderr_str:
        output_summary += f" stderr_len={len(stderr_str)}"

    new_history = list(notebook.execution_history) + [
        ExecutionRecord(
            tool_or_step="code_run",
            input_summary=code[:300] + ("..." if len(code) > 300 else ""),
            output_summary=output_summary,
            timestamp_iso=datetime.now(timezone.utc).isoformat(),
        )
    ]

    logger.info(
        "[GLM] Notebook updated: knowledge_count=%s (added %s) "
        "history_len=%s run_errors=%s large_refs=%s",
        len(new_knowledge),
        len(new_knowledge) - len(notebook.current_knowledge),
        len(new_history),
        len(run_errors),
        len(large_data_by_ref),
    )
    return (
        NotebookState(
            current_knowledge=new_knowledge,
            missing_information=notebook.missing_information,
            execution_history=new_history,
        ),
        run_errors,
        large_data_by_ref,
    )
