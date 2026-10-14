"""Deterministic distribution probes for cohort scoring (per-property aggregates)."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, FrozenSet, List, Optional, Set
from uuid import UUID

from contextd.api.context import ApiContext
from contextd.platform.agent_orchestration.tools import graph_sql

logger = logging.getLogger(__name__)

MAX_PROBE_KEYS = 12
_CAT_TOP_N = 21

_SAFE_KEY = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def cohort_column_key_compact(name: str) -> str:
    """Normalize Cypher RETURN aliases so final_score, finalScore, FINAL_SCORE match."""
    return "".join(c.lower() for c in str(name) if c.isalnum())


# Aliases LLMs / Cypher often use instead of exactly `final_score` / `confidence`
FINAL_SCORE_COMPACT_ALIASES: FrozenSet[str] = frozenset(
    {
        "finalscore",
        "totalscore",
        "weightedscore",
        "normalizedscore",
        "aggregatedscore",
        "riskscore",
        "cohortscore",
        "combinedscore",
        "overallscore",
        "score",  # generic aggregate (avoid comp_* columns — those use comp prefix)
    }
)
CONFIDENCE_COMPACT_ALIASES: FrozenSet[str] = frozenset(
    {
        "confidence",
        "confidencescore",
        "scoreconfidence",
        "modelconfidence",
    }
)


def cohort_row_compact_keys(row: Dict[str, Any]) -> Set[str]:
    """Compact column names for a result row (matches cohort_column_key_compact per key)."""
    return {cohort_column_key_compact(str(k)) for k in row.keys()}


def get_final_score_from_row(row: Dict[str, Any]) -> Optional[float]:
    """First matching final-score column (priority order)."""
    ck_to_k = {cohort_column_key_compact(str(k)): k for k in row.keys()}
    priority = (
        "finalscore",
        "totalscore",
        "weightedscore",
        "riskscore",
        "cohortscore",
        "normalizedscore",
        "aggregatedscore",
        "combinedscore",
        "overallscore",
        "score",
    )
    for alias in priority:
        k = ck_to_k.get(alias)
        if k is None:
            continue
        try:
            return float(row[k])  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    return None


def get_confidence_from_row(row: Dict[str, Any]) -> Optional[float]:
    """Parse confidence (0–1) from the first matching column alias."""
    ck_to_k = {cohort_column_key_compact(str(k)): k for k in row.keys()}
    for alias in ("confidence", "confidencescore", "scoreconfidence", "modelconfidence"):
        k = ck_to_k.get(alias)
        if k is None:
            continue
        try:
            return float(row[k])  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    return None


def _prop_accessor(key: str) -> str:
    """Safe property subscript for apoc map (Cypher)."""
    k = key.strip()
    if _SAFE_KEY.match(k):
        return f"p.{k}"
    # Escape backticks inside key
    esc = k.replace("`", "``")
    return f"p.`{esc}`"


async def fetch_distribution_summary(
    *,
    organization_id: UUID,
    ctx: ApiContext,
    node_type: str,
    property_keys: List[str],
) -> Dict[str, Any]:
    """Run bounded Cypher probes per key: numeric stats or categorical frequency."""
    keys = list(dict.fromkeys(k.strip() for k in property_keys if k and k.strip()))[
        :MAX_PROBE_KEYS
    ]
    base_params = {"node_type": node_type}

    out: Dict[str, Any] = {
        "target_node_type": node_type,
        "keys": {},
    }

    total_q = """
    MATCH (n:GraphNode)
    WHERE n.organization_id = $organization_id AND n.node_type = $node_type
    RETURN count(n) AS total
    """
    try:
        tr = await graph_sql(
            total_q,
            organization_id,
            ctx,
            params=base_params,
            max_results=5,
        )
        out["total_nodes"] = int(tr[0].get("total", 0)) if tr else 0
    except Exception as e:
        logger.warning("cohort probe total count failed: %s", e)
        out["total_nodes"] = None

    for key in keys:
        pa = _prop_accessor(key)
        num_q = f"""
        MATCH (n:GraphNode)
        WHERE n.organization_id = $organization_id AND n.node_type = $node_type
        WITH apoc.convert.fromJsonMap(n.properties) AS p
        WHERE p IS NOT NULL AND {pa} IS NOT NULL
        WITH toFloat(trim(toString({pa}))) AS v
        WHERE v IS NOT NULL
        RETURN count(v) AS n,
               min(v) AS min_v,
               max(v) AS max_v,
               avg(v) AS avg_v
        """
        rows: List[Dict[str, Any]] = []
        try:
            rows = await graph_sql(
                num_q,
                organization_id,
                ctx,
                params=base_params,
                max_results=5,
            )
        except Exception as e:
            logger.debug("numeric probe failed for %s: %s", key, e)
            rows = []

        if rows and int(rows[0].get("n") or 0) > 0:
            r = rows[0]
            entry: Dict[str, Any] = {
                "kind": "numeric",
                "count_non_null": int(r.get("n") or 0),
                "min": _num(r.get("min_v")),
                "max": _num(r.get("max_v")),
                "mean": _num(r.get("avg_v")),
            }
            # Optional percentiles (second query if first lacked)
            pq = f"""
            MATCH (n:GraphNode)
            WHERE n.organization_id = $organization_id AND n.node_type = $node_type
            WITH apoc.convert.fromJsonMap(n.properties) AS p
            WHERE p IS NOT NULL AND {pa} IS NOT NULL
            WITH toFloat(trim(toString({pa}))) AS v
            WHERE v IS NOT NULL
            RETURN percentileCont(v, 0.25) AS p25,
                   percentileCont(v, 0.5) AS p50,
                   percentileCont(v, 0.75) AS p75
            """
            try:
                pr = await graph_sql(
                    pq, organization_id, ctx, params=base_params, max_results=5
                )
                if pr:
                    entry["p25"] = _num(pr[0].get("p25"))
                    entry["p50"] = _num(pr[0].get("p50"))
                    entry["p75"] = _num(pr[0].get("p75"))
            except Exception:
                pass
            out["keys"][key] = entry
            continue

        cat_q = f"""
        MATCH (n:GraphNode)
        WHERE n.organization_id = $organization_id AND n.node_type = $node_type
        WITH apoc.convert.fromJsonMap(n.properties) AS p
        WHERE p IS NOT NULL AND {pa} IS NOT NULL
        WITH substring(toString({pa}), 0, 200) AS bucket, count(*) AS cnt
        RETURN bucket, cnt
        ORDER BY cnt DESC
        LIMIT {_CAT_TOP_N}
        """
        try:
            crows = await graph_sql(
                cat_q,
                organization_id,
                ctx,
                params=base_params,
                max_results=_CAT_TOP_N + 5,
            )
        except Exception as e:
            logger.warning("categorical probe failed for %s: %s", key, e)
            out["keys"][key] = {"kind": "unknown", "error": str(e)[:200]}
            continue

        total_cat = sum(int(c.get("cnt") or 0) for c in crows)
        dist = []
        for c in crows:
            cnt = int(c.get("cnt") or 0)
            b = c.get("bucket")
            dist.append(
                {
                    "value": b,
                    "count": cnt,
                    "pct": round(100.0 * cnt / total_cat, 2) if total_cat else 0.0,
                }
            )
        out["keys"][key] = {
            "kind": "categorical",
            "distinct_capped": len(dist),
            "distribution": dist,
        }

    return out


def _num(v: Any) -> Any:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _final_score_from_row_or_key(
    row: Dict[str, Any], score_key: str
) -> Optional[float]:
    fs = get_final_score_from_row(row)
    if fs is not None:
        return fs
    if not score_key:
        return None
    target = cohort_column_key_compact(score_key)
    for k, v in row.items():
        if cohort_column_key_compact(str(k)) != target:
            continue
        try:
            return float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
    return None


def score_distribution_from_rows(
    rows: List[Dict[str, Any]],
    score_key: str = "final_score",
) -> Dict[str, Any]:
    """Compute min/max/mean/quantiles from sample rows (Python)."""
    vals: List[float] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        fs = _final_score_from_row_or_key(row, score_key)
        if fs is not None:
            vals.append(fs)
    if not vals:
        return {"n": 0, "note": "no_final_score_in_rows"}
    vals.sort()
    n = len(vals)

    def pct(p: float) -> float:
        if n == 1:
            return vals[0]
        idx = int(p * (n - 1))
        return vals[idx]

    return {
        "n": n,
        "min": vals[0],
        "max": vals[-1],
        "mean": sum(vals) / n,
        "p25": pct(0.25),
        "p50": pct(0.5),
        "p75": pct(0.75),
    }
