"""P-Agent dataset selection and sandboxed execution."""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any, Dict, List, Optional, Tuple

from contextd.platform.agent_orchestration.p_agent_functions import (
    get_predefined_functions_registry,
)
from contextd.platform.agent_orchestration.runtime.sandbox import SANDBOX_BUILTINS
from contextd.platform.agent_orchestration.runtime.settings import (
    EXECUTOR_TIMEOUT_SECONDS,
    LARGE_DATA_ROW_THRESHOLD,
    MAX_P_AGENT_DATASETS_PER_ROUND,
    P_AGENT_ROW_THRESHOLD,
)


def cypher_rows_plottable(rows: List[Dict[str, Any]]) -> bool:
    """True when a small row list still looks useful for charts."""
    if not rows:
        return False
    if len(rows) >= P_AGENT_ROW_THRESHOLD:
        return True
    keys = set(rows[0].keys()) if isinstance(rows[0], dict) else set()
    aggregate_hints = (
        "count",
        "cnt",
        "total",
        "sum",
        "avg",
        "mean",
        "min",
        "max",
    )
    return bool(keys & set(aggregate_hints))


def select_cypher_for_p_agent(
    last_cypher_results: List[Tuple[str, List[Dict[str, Any]]]],
    *,
    use_p: bool,
) -> Optional[Tuple[str, List[Dict[str, Any]]]]:
    """Pick one Cypher result for P-Agent when not in explicit use_p_agent mode."""
    if not last_cypher_results:
        return None
    for cypher, rows in last_cypher_results:
        if rows and (use_p or len(rows) > LARGE_DATA_ROW_THRESHOLD):
            return (cypher, rows)
    for cypher, rows in last_cypher_results:
        if rows and cypher_rows_plottable(rows):
            return (cypher, rows)
    return None


def list_cypher_datasets_for_p_agent(
    last_cypher_results: List[Tuple[str, List[Dict[str, Any]]]],
    *,
    use_p: bool,
) -> List[Tuple[str, List[Dict[str, Any]]]]:
    """Return the Cypher datasets that should be analyzed by the P-Agent."""
    if not last_cypher_results:
        return []
    if use_p:
        out: List[Tuple[str, List[Dict[str, Any]]]] = []
        for cypher, rows in last_cypher_results:
            if not rows:
                continue
            out.append((cypher, rows))
            if len(out) >= MAX_P_AGENT_DATASETS_PER_ROUND:
                break
        return out
    selected = select_cypher_for_p_agent(last_cypher_results, use_p=False)
    return [selected] if selected else []


def _run_p_sandbox_in_thread(
    code: str,
    df: Any,
    chart_entries: List[Dict[str, Any]],
    timeout_seconds: int,
) -> Tuple[str, str, List[str]]:
    """Run P-Agent code in a thread with df and predefined chart functions."""
    import io
    import sys

    builtins = {
        **SANDBOX_BUILTINS,
        "print": print,
    }
    namespace: Dict[str, Any] = {
        "__builtins__": builtins,
        "df": df,
        **get_predefined_functions_registry(chart_entries),
    }

    stdout_io = io.StringIO()
    stderr_io = io.StringIO()
    run_errors: List[str] = []

    def run() -> None:
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = stdout_io, stderr_io
        try:
            exec(code, namespace)
        except Exception as e:
            run_errors.append(str(e))
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run)
        try:
            future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError:
            run_errors.append(f"P-Agent execution timed out after {timeout_seconds}s")
        except Exception as e:
            run_errors.append(str(e))

    return (stdout_io.getvalue() or "", stderr_io.getvalue() or "", run_errors)


async def run_p_executor(
    code: str,
    df: Any,
    *,
    timeout_seconds: int = EXECUTOR_TIMEOUT_SECONDS,
) -> Tuple[str, str, List[Dict[str, Any]], List[str]]:
    """Run P-Agent generated code and collect stdout plus chart entries."""
    chart_entries: List[Dict[str, Any]] = []
    stdout_str, stderr_str, run_errors = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: _run_p_sandbox_in_thread(code, df, chart_entries, timeout_seconds),
    )
    return (stdout_str or "", stderr_str or "", chart_entries, run_errors)
