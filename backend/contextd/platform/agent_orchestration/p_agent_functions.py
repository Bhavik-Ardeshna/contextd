"""Predefined functions for P-Agent sandbox: analysis and chart output.

P-Agent code runs with a pandas DataFrame `df` and these functions only.
No network, no file I/O, no run_cypher. Visualizations are emitted as chart specs
via emit_chart(spec) for the frontend to render with Recharts (JSON Bridge).
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

# Optional pandas; only used when P-executor runs
# Numpy types (numpy.int64, numpy.float64) are not JSON-serializable; convert to native Python.
try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    np = None  # type: ignore[assignment]
    _HAS_NUMPY = False


def _to_native_value(v: Any) -> Any:
    """Convert numpy/pandas scalars to native Python for JSON serialization."""
    if v is None:
        return None
    if _HAS_NUMPY and hasattr(np, "integer") and isinstance(v, np.integer):
        return int(v)
    if _HAS_NUMPY and hasattr(np, "floating") and isinstance(v, np.floating):
        return float(v)
    if _HAS_NUMPY and hasattr(np, "ndarray") and isinstance(v, np.ndarray):
        return v.tolist()
    if isinstance(v, (int, float, str, bool)):
        return v
    try:
        return int(v)
    except (TypeError, ValueError):
        pass
    try:
        return float(v)
    except (TypeError, ValueError):
        pass
    return str(v)
try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore[assignment]

# Type for a single function spec (callable is optional for doc-only)
PredefinedFunctionSpec = Dict[str, Any]


def sanitize_p_agent_stdout_for_llm(text: str) -> str:
    """Strip pandas ``DataFrame.info()``-style blocks from P-Agent stdout before Analysis / final LLM."""
    if not text:
        return text
    if not text.strip():
        return ""
    text = re.sub(
        r"<class 'pandas\.core\.frame\.DataFrame'>.*?memory usage:[^\n]*\n",
        "",
        text,
        flags=re.DOTALL,
    )
    return text.strip()


def _safe_describe_df(df: "pd.DataFrame") -> str:
    """Return string summary of df.describe()."""
    if pd is None or df is None or df.empty:
        return "No data to describe."
    try:
        return str(df.describe())
    except Exception:
        return "Could not compute describe()."


def _safe_value_counts(df: "pd.DataFrame", column: str) -> Dict[str, Any]:
    """Return value_counts for a column as a dict (value -> count)."""
    if pd is None or df is None or df.empty or column not in df.columns:
        return {}
    try:
        vc = df[column].value_counts()
        return vc.to_dict()
    except Exception:
        return {}


def _safe_chart_from_columns(
    df: "pd.DataFrame",
    label_col: str,
    value_col: str,
) -> List[Dict[str, Any]]:
    """Build chart data from two columns (for pre-aggregated Cypher results: e.g. status + count).
    Use this when df already has one row per category and a numeric count/sum column.
    Returns list of {label, value} dicts with native Python types.
    """
    if pd is None or df is None or df.empty or label_col not in df.columns or value_col not in df.columns:
        return []
    try:
        out = []
        for _, row in df.iterrows():
            label = row[label_col]
            val = row[value_col]
            out.append({
                "label": str(label) if label is not None else "",
                "value": _to_native_value(val) if val is not None else 0,
            })
        return out
    except Exception:
        return []


def _safe_head(df: "pd.DataFrame", n: int = 5) -> str:
    """Return first n rows as string."""
    if pd is None or df is None or df.empty:
        return "No data."
    try:
        return df.head(n).to_string()
    except Exception:
        return "Could not get head()."


def _safe_info(df: "pd.DataFrame") -> str:
    """Return df.info() as string (column dtypes, non-null counts)."""
    if pd is None or df is None:
        return "No data."
    try:
        from io import StringIO

        buf = StringIO()
        df.info(buf=buf)
        return buf.getvalue()
    except Exception:
        return "Could not get info()."


def get_predefined_functions_registry(
    chart_entries: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Callable[..., Any]]:
    """Build the namespace of callables for the P-sandbox.

    chart_entries: mutable list of chart spec dicts (type, chart_type, title, data, config) from emit_chart().
    """
    if chart_entries is None:
        chart_entries = []

    def emit_chart(spec: Dict[str, Any]) -> None:
        """Submit a chart spec for the frontend to render (JSON Bridge). Do not use matplotlib for charts.
        spec must have: type='chart', chart_type (pie|bar|line|histogram), title, data (list of {label, value}).
        Optional: config (e.g. {xAxis, yAxis}). Numeric values are normalized to native Python for JSON.
        """
        if not isinstance(spec, dict):
            return
        raw_data = list(spec.get("data")) if isinstance(spec.get("data"), list) else []
        # Normalize: native types, prefer count/cnt/total/sum as value, ensure label/name for pie/bar
        # Prefer count-like columns over "value" so pre-aggregated data shows real counts
        _value_keys = ("count", "cnt", "total", "sum", "order_count", "num_orders", "total_count", "value", "revenue", "amount")
        _label_keys = ("label", "name", "category", "bucket", "bin", "country", "status", "region", "type", "month", "date", "period", "x")
        data = []
        for row in raw_data:
            if isinstance(row, dict):
                out_row = {str(k): _to_native_value(v) for k, v in row.items()}
                # Value: prefer explicit aggregate column so we never show 1 for pre-aggregated data
                agg = next((out_row.get(k) for k in _value_keys if out_row.get(k) is not None and isinstance(out_row.get(k), (int, float))), None)
                if agg is not None:
                    out_row["value"] = agg
                elif out_row.get("value") is None:
                    # Fallback: first numeric value in row (for custom column names)
                    for k, v in out_row.items():
                        if k in _label_keys:
                            continue
                        if isinstance(v, (int, float)) and v is not None:
                            out_row["value"] = v
                            break
                # Label/name: ensure present for pie/bar so frontend never shows index
                label_val = next((out_row.get(k) for k in _label_keys if out_row.get(k) is not None and out_row.get(k) != ""), None)
                if label_val is not None:
                    raw = str(label_val) if not isinstance(label_val, (int, float)) else str(label_val)
                    out_row["label"] = "(missing)" if raw in ("None", "nan", "NaN", "null") else raw
                    out_row["name"] = out_row["label"]
                else:
                    for k, v in out_row.items():
                        if k in ("value", "count", "cnt", "total", "sum") or (isinstance(v, (int, float)) and k != "value"):
                            continue
                        if v is not None and v != "":
                            raw = str(v)
                            out_row["label"] = "(missing)" if raw in ("None", "nan", "NaN", "null") else raw
                            out_row["name"] = out_row["label"]
                            break
                data.append(out_row)
            else:
                data.append(row)
        out = {
            "type": "chart",
            "chart_type": str(spec.get("chart_type") or "bar"),
            "title": str(spec.get("title") or ""),
            "data": data,
            "config": dict(spec["config"]) if isinstance(spec.get("config"), dict) else None,
        }
        _allowed = ("pie", "bar", "line", "histogram", "area", "scatter", "radar", "radialBar")
        if out["chart_type"] not in _allowed:
            out["chart_type"] = "bar"
        chart_entries.append(out)

    if pd is None:
        return {"emit_chart": emit_chart}

    return {
        "emit_chart": emit_chart,
        "describe_df": lambda d: _safe_describe_df(d),
        "value_counts_column": lambda d, col: _safe_value_counts(d, col),
        "chart_from_columns": lambda d, label_col, value_col: _safe_chart_from_columns(d, label_col, value_col),
        "head_df": lambda d, n=5: _safe_head(d, n),
        "info_df": lambda d: _safe_info(d),
    }


def get_predefined_functions_doc() -> str:
    """Return a string describing each predefined function for prompt injection."""
    lines = [
        "**Predefined functions (you may use only these):**",
        "",
        "- **emit_chart(spec: dict) -> None**",
        "  Submit a chart for the frontend to render in the chat (JSON Bridge).",
        "  spec: {\"type\": \"chart\", \"chart_type\": \"pie\"|\"bar\"|\"line\"|\"histogram\"|\"area\"|\"scatter\"|\"radar\"|\"radialBar\", \"title\": \"...\", \"data\": [{\"label\": \"A\", \"value\": 10}, ...] (for scatter use {\"x\": num, \"y\": num}), \"config\": {\"xAxis\": \"...\", \"yAxis\": \"...\"} (optional)}.",
        "  Use Python to aggregate df into the 'data' array (e.g. chart_from_columns when data is already aggregated, or value_counts_column/groupby when it is not), then call emit_chart(result).",
        "",
        "- **describe_df(df) -> str**",
        "  Numeric summary statistics (count, mean, std, min, max, quartiles).",
        "  Input: DataFrame. Output: string.",
        "",
        "- **value_counts_column(df, column: str) -> dict**",
        "  Count of each value in the given column (number of rows per value). Use ONLY when df has many rows per category and no existing count column. If df already has a column named count, cnt, total, or sum, do NOT use this—use chart_from_columns instead.",
        "  Input: DataFrame, column name. Output: dict mapping value -> count.",
        "",
        "- **chart_from_columns(df, label_col: str, value_col: str) -> list**",
        "  Build chart data from two columns when df is ALREADY AGGREGATED (e.g. Cypher returned status, count). If the data explicitly already includes a count (count, cnt, total, sum), use this—do not use value_counts_column or you will get 1 per row. Before calling, filter out null/None in the label column (e.g. df = df[df[label_col].notna()]) and report in print() how many rows were dropped (e.g. 'N items had no [label_col]').",
        "  Input: DataFrame, name of category column, name of numeric column. Output: list of dicts for emit_chart(spec)[\"data\"].",
        "",
        "- **head_df(df, n=5) -> str**",
        "  First n rows as a string table.",
        "  Input: DataFrame, optional n. Output: string.",
        "",
        "- **info_df(df) -> str**",
        "  Column dtypes and non-null counts (verbose). Use sparingly—do not paste the full output into the summary unless dtypes are essential.",
        "  Input: DataFrame. Output: string.",
        "",
    ]
    return "\n".join(lines)
