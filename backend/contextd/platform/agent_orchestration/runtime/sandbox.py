"""Shared sandbox primitives for agent-generated Python."""

from __future__ import annotations

from typing import Any, Dict

SANDBOX_BUILTINS: Dict[str, Any] = {
    "list": list,
    "dict": dict,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "len": len,
    "range": range,
    "enumerate": enumerate,
    "zip": zip,
    "map": map,
    "filter": filter,
    "sorted": sorted,
    "sum": sum,
    "min": min,
    "max": max,
    "abs": abs,
    "isinstance": isinstance,
    "round": round,
    "None": None,
    "True": True,
    "False": False,
}


def sandbox_safe_div(a: Any, b: Any, default: float = 0.0) -> float:
    """Guard agent-emitted ratio calculations against invalid denominators."""
    try:
        denominator = float(b)
        if denominator == 0.0:
            return float(default)
        return float(a) / denominator
    except (TypeError, ValueError, ZeroDivisionError):
        return float(default)


def sandbox_safe_mean(values: Any, default: float = 0.0) -> float:
    """Return the mean of a sequence, using default for invalid or empty input."""
    if not isinstance(values, (list, tuple)) or len(values) == 0:
        return float(default)
    try:
        nums = [float(value) for value in values]
        return sandbox_safe_div(sum(nums), len(nums), default=default)
    except (TypeError, ValueError):
        return float(default)
