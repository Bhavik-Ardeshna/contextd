"""Prompt redaction and input metadata helpers for LLM calls."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List


def redact_llm_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Return a prompt-safe representation that never includes message content."""
    redacted: List[Dict[str, str]] = []
    for message in messages:
        role = str(message.get("role", "")) if isinstance(message, dict) else ""
        content = message.get("content", "") if isinstance(message, dict) else ""
        redacted.append({"role": role, "content": _redacted_value(content)})
    return redacted


def messages_input_metadata(messages: List[Dict[str, Any]]) -> dict[str, Any]:
    """Return redacted aggregate metadata for chat-style LLM input."""
    contents = []
    for message in messages:
        content = message.get("content", "") if isinstance(message, dict) else ""
        contents.append("" if content is None else str(content))
    return _input_metadata(contents)


def texts_input_metadata(texts: List[str]) -> dict[str, Any]:
    """Return redacted aggregate metadata for embedding input."""
    return _input_metadata(["" if text is None else str(text) for text in texts])


def _input_metadata(values: List[str]) -> dict[str, Any]:
    """Return aggregate metadata for logging and metrics without raw input content."""
    total_chars = sum(len(value) for value in values)
    joined = "\n".join(values)
    return {
        "input_items": len(values),
        "input_chars": total_chars,
        "input_sha256": _stable_hash(joined),
        "input_token_estimate": _estimated_tokens(total_chars),
        "prompt_redacted": True,
    }


def _redacted_value(value: Any) -> str:
    """Represent a sensitive prompt value by size and fingerprint only."""
    text = "" if value is None else str(value)
    return f"<redacted chars={len(text)} sha256={_stable_hash(text)}>"


def _stable_hash(value: str) -> str:
    """Return a short stable fingerprint for correlation without content exposure."""
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]


def _estimated_tokens(char_count: int) -> int:
    """Estimate input tokens from character count for lightweight observability."""
    return max(1, int(char_count * 0.3)) if char_count else 0
