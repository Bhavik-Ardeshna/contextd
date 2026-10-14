"""Metrics and logging helpers for ContextD LLM gateway attempts."""

from __future__ import annotations

import logging
from typing import Any

from contextd.platform.llm.types import OPERATION_FAILURE_LABELS, LLMOperation

try:
    from prometheus_client import Counter, Histogram
except ImportError:  # pragma: no cover - prometheus-client is an application dependency.
    Counter = None  # type: ignore[assignment]
    Histogram = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_LLM_CALL_LABELS = ["operation", "role", "provider", "model", "status"]
if Counter is not None and Histogram is not None:
    _LLM_CALLS_TOTAL = Counter(
        "contextd_llm_calls_total",
        "Total ContextD LLM provider attempts by operation, role, model, and status.",
        _LLM_CALL_LABELS,
    )
    _LLM_CALL_LATENCY_SECONDS = Histogram(
        "contextd_llm_call_latency_seconds",
        "ContextD LLM provider attempt latency in seconds.",
        _LLM_CALL_LABELS,
        buckets=(0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600),
    )
    _LLM_RETRIES_TOTAL = Counter(
        "contextd_llm_retries_total",
        "Total ContextD LLM retry attempts scheduled by the gateway.",
        ["operation", "role", "provider", "model", "error_type"],
    )
    _LLM_INPUT_TOKENS_TOTAL = Counter(
        "contextd_llm_estimated_input_tokens_total",
        "Estimated ContextD LLM input tokens submitted to providers.",
        ["operation", "role", "provider", "model"],
    )
else:  # pragma: no cover - defensive fallback for stripped runtimes.
    _LLM_CALLS_TOTAL = None
    _LLM_CALL_LATENCY_SECONDS = None
    _LLM_RETRIES_TOTAL = None
    _LLM_INPUT_TOKENS_TOTAL = None


def failure_message(
    operation: LLMOperation,
    role: str,
    attempts: int,
    error: Exception,
) -> str:
    """Build a provider failure message without provider text that may include prompts."""
    label = OPERATION_FAILURE_LABELS[operation]
    return (
        f"LLM {label} failed for role '{role}' after {attempts} attempt(s): "
        f"{type(error).__name__}"
    )


def timeout_message(
    operation: LLMOperation,
    role: str,
    attempts: int,
    timeout_seconds: float,
) -> str:
    """Build a timeout failure message without input content."""
    label = OPERATION_FAILURE_LABELS[operation]
    return (
        f"LLM {label} timed out for role '{role}' after {attempts} attempt(s) "
        f"at {timeout_seconds:.2f}s"
    )


def record_llm_attempt(
    *,
    ctx: Any | None,
    operation: LLMOperation,
    role: str,
    provider: str,
    model: str,
    status: str,
    attempt: int,
    max_attempts: int,
    duration_seconds: float,
    timeout_seconds: float,
    input_metadata: dict[str, Any],
    error: Exception | None = None,
    will_retry: bool = False,
) -> None:
    """Record metrics and structured logs for a single provider attempt."""
    _observe_llm_metrics(
        operation=operation,
        role=role,
        provider=provider,
        model=model,
        status=status,
        duration_seconds=duration_seconds,
        estimated_input_tokens=int(input_metadata.get("input_token_estimate", 0)),
        error=error,
        will_retry=will_retry,
    )

    dimensions = {
        "component": "llm_gateway",
        "llm_operation": operation,
        "llm_role": role,
        "llm_provider": provider,
        "llm_model": model,
        "llm_status": status,
        "llm_attempt": attempt,
        "llm_max_attempts": max_attempts,
        "llm_duration_ms": round(duration_seconds * 1000, 2),
        "llm_timeout_seconds": timeout_seconds,
        "llm_input_items": int(input_metadata.get("input_items", 0)),
        "llm_input_chars": int(input_metadata.get("input_chars", 0)),
        "llm_input_token_estimate": int(input_metadata.get("input_token_estimate", 0)),
        "llm_input_sha256": str(input_metadata.get("input_sha256", "")),
        "prompt_redacted": True,
    }
    if error is not None:
        dimensions["llm_error_type"] = type(error).__name__
    if will_retry:
        dimensions["llm_will_retry"] = True

    level = "info" if status == "success" else "warning"
    _log_with_dimensions(ctx, level, "ContextD LLM gateway attempt completed", dimensions)


def _observe_llm_metrics(
    *,
    operation: str,
    role: str,
    provider: str,
    model: str,
    status: str,
    duration_seconds: float,
    estimated_input_tokens: int,
    error: Exception | None,
    will_retry: bool,
) -> None:
    """Update Prometheus metrics without letting instrumentation affect the request."""
    try:
        if _LLM_CALLS_TOTAL is not None:
            _LLM_CALLS_TOTAL.labels(operation, role, provider, model, status).inc()
        if _LLM_CALL_LATENCY_SECONDS is not None:
            _LLM_CALL_LATENCY_SECONDS.labels(
                operation,
                role,
                provider,
                model,
                status,
            ).observe(duration_seconds)
        if _LLM_INPUT_TOKENS_TOTAL is not None and estimated_input_tokens:
            _LLM_INPUT_TOKENS_TOTAL.labels(operation, role, provider, model).inc(
                estimated_input_tokens
            )
        if _LLM_RETRIES_TOTAL is not None and will_retry:
            error_type = type(error).__name__ if error is not None else "UnknownError"
            _LLM_RETRIES_TOTAL.labels(operation, role, provider, model, error_type).inc()
    except Exception:
        logger.debug("Failed to record ContextD LLM gateway metrics", exc_info=True)


def _log_with_dimensions(
    ctx: Any | None,
    level: str,
    message: str,
    dimensions: dict[str, Any],
) -> None:
    """Log structured dimensions while tolerating lightweight test loggers."""
    ctx_logger = getattr(ctx, "logger", None) if ctx is not None else None
    active_logger = ctx_logger or logger
    log_method = getattr(active_logger, level, logger.info)

    try:
        if hasattr(active_logger, "with_context"):
            contextual_logger = active_logger.with_context(**dimensions)
            getattr(contextual_logger, level)(message)
        else:
            log_method(message, extra={"custom_dimensions": dimensions})
    except TypeError:
        log_method(f"{message}: {dimensions}")
