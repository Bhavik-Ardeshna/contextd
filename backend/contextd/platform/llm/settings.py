"""Settings helpers for the ContextD LLM gateway."""

from __future__ import annotations

from typing import Any, Optional

from contextd.core.config import settings as default_settings
from contextd.platform.llm.types import ROLE_MODEL_FIELDS, LLMConfigurationError, LLMRole


def configured_llm_model(role: LLMRole = "default", app_settings: Any | None = None) -> str:
    """Return the configured model name for a role without constructing a provider."""
    settings = app_settings or default_settings
    role_key = normalize_role(role)
    field_name = ROLE_MODEL_FIELDS.get(role_key)
    role_model = clean_optional_text(getattr(settings, field_name, None)) if field_name else None
    default_model = clean_required_text(
        getattr(settings, "LLM_DEFAULT_MODEL", None),
        "LLM_DEFAULT_MODEL",
    )
    return role_model or default_model


def normalize_role(role: str) -> str:
    """Normalize role aliases to the canonical gateway key."""
    return str(role or "default").strip().lower().replace("-", "_")


def clean_optional_text(value: Any) -> Optional[str]:
    """Return stripped text or None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def clean_required_text(value: Any, field_name: str) -> str:
    """Return stripped text or raise a typed configuration error."""
    text = clean_optional_text(value)
    if not text:
        raise LLMConfigurationError(f"{field_name} must not be empty")
    return text


def positive_int(value: Any, field_name: str) -> int:
    """Return a positive integer setting."""
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise LLMConfigurationError(f"{field_name} must be a positive integer") from exc
    if parsed <= 0:
        raise LLMConfigurationError(f"{field_name} must be a positive integer")
    return parsed


def positive_float(value: Any, field_name: str) -> float:
    """Return a positive float setting."""
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise LLMConfigurationError(f"{field_name} must be positive") from exc
    if parsed <= 0:
        raise LLMConfigurationError(f"{field_name} must be positive")
    return parsed


def non_negative_float(value: Any, field_name: str) -> float:
    """Return a non-negative float setting."""
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise LLMConfigurationError(f"{field_name} must not be negative") from exc
    if parsed < 0:
        raise LLMConfigurationError(f"{field_name} must not be negative")
    return parsed
