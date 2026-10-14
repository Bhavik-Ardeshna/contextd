"""Deterministic-first property merge with optional LLM synthesis on conflict."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Optional, Tuple


def _hash_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:32]


def merge_dicts_deterministic(
    base: Optional[Dict[str, Any]],
    incoming: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], bool]:
    """Deep-merge dicts; return (merged, had_conflict_on_leaf_string)."""
    had_conflict = False
    out: Dict[str, Any] = dict(base or {})
    for k, v in (incoming or {}).items():
        if k not in out or out[k] is None:
            out[k] = v
            continue
        if isinstance(out[k], dict) and isinstance(v, dict):
            sub, c = merge_dicts_deterministic(out[k], v)
            out[k] = sub
            had_conflict = had_conflict or c
        elif isinstance(out[k], str) and isinstance(v, str):
            if out[k].strip() != v.strip() and out[k].strip() and v.strip():
                had_conflict = True
            # Prefer longer / richer text when both non-empty
            out[k] = v if len(v) > len(out[k]) else out[k]
        else:
            if out[k] != v:
                had_conflict = True
            out[k] = v
    return out, had_conflict


async def synthesize_summary_if_needed(
    *,
    title: str,
    text_a: Optional[str],
    text_b: Optional[str],
    llm_call,
    llm_synthesis_on_conflict: Optional[bool] = None,
) -> Optional[str]:
    """If conflict and settings allow, merge two text blobs via LLM.

    When ``llm_synthesis_on_conflict`` is set, it overrides
    ``SEMANTIC_MERGE_LLM_SYNTHESIS_ON_CONFLICT`` (and avoids loading settings when False).
    """
    if llm_synthesis_on_conflict is None:
        from contextd.core.config import settings

        use_llm = settings.SEMANTIC_MERGE_LLM_SYNTHESIS_ON_CONFLICT
    else:
        use_llm = llm_synthesis_on_conflict

    if not use_llm:
        merged, _ = merge_dicts_deterministic(
            {"description": text_a or ""},
            {"description": text_b or ""},
        )
        return merged.get("description") or None
    if not text_a and not text_b:
        return None
    if text_a and text_b and text_a.strip() != text_b.strip():
        prompt = (
            f"Merge the following two descriptions about '{title}' into one concise paragraph. "
            "Remove redundancy; keep factual detail.\n\n"
            f"A:\n{text_a}\n\nB:\n{text_b}\n"
        )
        return await llm_call(prompt)
    return text_a or text_b


def embedding_text_hash(text: str) -> str:
    """Hash for detecting embedding invalidation."""
    return _hash_text(text)
