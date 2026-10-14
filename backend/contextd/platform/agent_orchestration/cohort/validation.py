"""Cohort result validation and retry-message helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from contextd_adk.agent.utils.message_utils import message_to_dict

from contextd.platform.agent_orchestration.cohort.probe import (
    CONFIDENCE_COMPACT_ALIASES,
    FINAL_SCORE_COMPACT_ALIASES,
    cohort_row_compact_keys,
    get_confidence_from_row,
    get_final_score_from_row,
)
from contextd.platform.agent_orchestration.types import NotebookState

COHORT_SCORING_RETURN_RETRY_HINT = (
    " Every RETURN row must include: `node_id`, a combined 0-1 **final_score** (or accepted alias: "
    "weighted_score, total_score, score, finalScore, risk_score, normalized_score, cohort_score, "
    "combined_score, overall_score), and **confidence**; values must be numeric (use toFloat). "
    "**comp_*** = per-component only - the aggregate score must still appear as final_score (or alias). "
    "The final run_cypher for scoring must return this full row shape."
)

COHORT_ZERO_ROW_FINAL_WARNING = (
    "Listing Cypher still returned 0 rows after retries. Likely causes: "
    "(1) Date fields in `n.properties` JSON are strings - comparing `ends_at < date()` may not match; "
    "parse ISO strings or use temporal functions. "
    "(2) Business intent: 'at risk of cancellation' often means expiring soon (future window), "
    "not subscriptions already ended (`ends_at < today`). "
    "(3) Wrong node_type or property key - verify with COUNT and sample rows in Neo4j."
)

COHORT_SCORING_ZERO_ROW_FINAL_WARNING = (
    "Scoring Cypher returned 0 rows after retries. Check target node_type, JSON property keys, "
    "normalization, and NULL handling against missing_data_policy."
)


def validate_cohort_member_rows(rows: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """Cohort listing rows must expose node_id for shallow list and deep-dive."""
    if not rows:
        return True, ""
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            return False, f"Row {idx} is not an object"
        keys_lower = {k.lower() for k in row.keys()}
        if "node_id" not in keys_lower:
            return (
                False,
                "Cohort Cypher must RETURN a column named node_id for each row "
                "(e.g. n.node_id AS node_id).",
            )
    return True, ""


def validate_cohort_scoring_rows(rows: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """Scoring cohort rows must expose node id, final score, and confidence."""
    if not rows:
        return True, ""
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            return False, f"Row {idx} is not an object"
        ck = cohort_row_compact_keys(row)
        if "nodeid" not in ck:
            return (
                False,
                "Cohort scoring Cypher must RETURN a node id column "
                "(e.g. `n.node_id AS node_id` or `AS nodeId`).",
            )
        if not (FINAL_SCORE_COMPACT_ALIASES & ck):
            return (
                False,
                "Cohort scoring Cypher must RETURN a numeric score column for each row "
                "(e.g. **final_score**, **finalScore**, **weighted_score**, **total_score**, **score**).",
            )
        if not (CONFIDENCE_COMPACT_ALIASES & ck):
            return (
                False,
                "Cohort scoring Cypher must RETURN a confidence column (0-1) for each row "
                "(e.g. **confidence**, **model_confidence**).",
            )
        if get_final_score_from_row(row) is None:
            return (
                False,
                "Each row needs a numeric combined score: use `... AS final_score` (preferred), or "
                "weighted_score / total_score / score / risk_score / finalScore / normalized_score / "
                "cohort_score / combined_score / overall_score. Use toFloat() on expressions. "
                "comp_* alone is not enough for the aggregate score.",
            )
        if get_confidence_from_row(row) is None:
            return (
                False,
                "Each row must include a parseable confidence in 0-1 "
                "(**confidence** or common aliases).",
            )
    return True, ""


def filter_rows_by_score_cutoff(
    rows: List[Dict[str, Any]], cutoff: float
) -> List[Dict[str, Any]]:
    """Fallback when A-Agent cannot inject WHERE final_score >= cutoff."""
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        fs = get_final_score_from_row(row)
        if fs is not None and fs >= cutoff:
            out.append(row)
    return out


def cohort_scoring_cutoff_apply_message(last_cypher: Optional[str], cutoff: float) -> str:
    cq = (last_cypher or "").strip()
    preview = cq[:6000] + ("..." if len(cq) > 6000 else "")
    return (
        "## Apply score cutoff\n"
        f"The cutoff planner recommends **final_score >= {cutoff}**.\n"
        "Update the last **run_cypher** scoring query: add or extend `WHERE` so only rows with "
        "`final_score >= $cutoff` remain, and pass `params={{'cutoff': <float>}}` to `run_cypher`.\n"
        "Keep RETURN columns: **node_id**, **final_score**, **confidence**, and **comp_*** breakdown columns.\n\n"
        f"Previous Cypher:\n```\n{preview}\n```\n\n"
        'Respond with valid JSON with key "code" only.'
    )


def cohort_scoring_zero_rows_followup_message(last_cypher: Optional[str]) -> str:
    cq = (last_cypher or "").strip()
    preview = cq[:1200] + ("..." if len(cq) > 1200 else "")
    return (
        "## Zero rows from scoring Cypher\n"
        "The last **run_cypher** returned **0 rows**.\n\n"
        "**Next code should:**\n"
        "1. COUNT `GraphNode` rows for the target `node_type`.\n"
        "2. Sample a few nodes and inspect JSON property keys used in scoring.\n"
        "3. Fix normalization / NULL guards per missing_data_policy.\n\n"
        "Finish with a corrected scoring query that RETURNs **node_id**, **final_score**, **confidence**.\n\n"
        f"Query that returned 0 rows:\n```\n{preview}\n```"
    )


def cohort_zero_rows_followup_message(last_cypher: Optional[str]) -> str:
    """Instructions for A-Agent when the listing query returned no rows."""
    cq = (last_cypher or "").strip()
    preview = cq[:1200] + ("..." if len(cq) > 1200 else "")
    return (
        "## Zero rows from listing Cypher\n"
        "The last **run_cypher** listing returned **0 rows**.\n\n"
        "Do **not** treat this as proof that no data exists.\n\n"
        "**Next code should:**\n"
        "1. Run **COUNT** for the target `node_type` (minimal WHERE).\n"
        "2. **Sample** a few nodes: RETURN `n.node_id` and raw values for any date/status "
        "fields used in filters (`apoc.convert.fromJsonMap(n.properties).fieldName`) to see "
        "whether they are **strings** (e.g. ISO-8601) vs temporal.\n"
        "3. **Fix comparisons:** string dates usually need `datetime()` / parsing / ISO substring "
        "compare - not direct `field < date()` if `field` is a string.\n"
        "4. **Re-check the goal:** e.g. 'at risk' / churn often means **expiring within N days** "
        "while still active, not already past `ends_at`.\n\n"
        "Finish with a **corrected listing** `run_cypher` that RETURNs `node_id` and projected "
        "columns. Output valid JSON with key \"code\" only.\n\n"
        f"Query that returned 0 rows:\n```\n{preview}\n```"
    )


def conversation_from_agent_response(agent_response: Any) -> List[Dict[str, Any]]:
    conv = [
        message_to_dict(message)
        for message in (getattr(agent_response, "messages", None) or [])
    ]
    return [message for message in conv if (message or {}).get("role") != "system"]


def last_cypher_and_rows_from_notebook(
    notebook: NotebookState,
    large_data_by_ref: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    last_cypher: Optional[str] = None
    last_rows: List[Dict[str, Any]] = []
    refs = large_data_by_ref or {}
    for item in notebook.current_knowledge:
        if not isinstance(item, dict):
            continue
        if item.get("error"):
            continue
        cypher = item.get("cypher")
        if not cypher:
            continue
        ref_id = item.get("large_data_ref")
        if ref_id and ref_id in refs:
            last_cypher = str(cypher)
            last_rows = refs[ref_id]
            continue
        rows = item.get("rows")
        if isinstance(rows, list):
            last_cypher = str(cypher)
            last_rows = rows
    return last_cypher, last_rows


def all_cypher_rows_from_notebook(
    notebook: NotebookState,
    large_data_by_ref: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> List[Tuple[str, List[Dict[str, Any]]]]:
    """Every successful run_cypher snapshot in order, including sidecar rows."""
    out: List[Tuple[str, List[Dict[str, Any]]]] = []
    refs = large_data_by_ref or {}
    for item in notebook.current_knowledge:
        if not isinstance(item, dict):
            continue
        if item.get("error"):
            continue
        cypher = item.get("cypher")
        if not cypher:
            continue
        ref_id = item.get("large_data_ref")
        if ref_id and ref_id in refs:
            out.append((str(cypher), refs[ref_id]))
            continue
        rows = item.get("rows")
        if isinstance(rows, list):
            out.append((str(cypher), rows))
    return out


def pick_scoring_cypher_and_rows(
    notebook: NotebookState,
    large_data_by_ref: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """Prefer the latest run_cypher result whose rows pass scoring validation."""
    candidates = all_cypher_rows_from_notebook(notebook, large_data_by_ref)
    for cypher, rows in reversed(candidates):
        if not rows:
            continue
        ok, _ = validate_cohort_scoring_rows(rows)
        if ok:
            return cypher, rows
    if candidates:
        return candidates[-1]
    return None, []
