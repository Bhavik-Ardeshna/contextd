"""
Custom exceptions for the LLM module.

Provides structured error handling for LLM operations. All exceptions
inherit from OrchestratorError for consistent error handling and
automatic Langfuse reporting.
"""

from __future__ import annotations

from typing import Any

from contextd_adk.exceptions import (
    ErrorCategory,
    ErrorSeverity,
    OrchestratorError,
)


class LLMError(OrchestratorError):
    """
    Base exception for all LLM-related errors.

    Inherits from OrchestratorError for automatic Langfuse reporting.
    """

    default_message = "An LLM error occurred"
    default_error_code = "LLM_ERROR"
    default_category = ErrorCategory.PROVIDER
    default_severity = ErrorSeverity.HIGH

    def __init__(
        self,
        message: str | None = None,
        *,
        model: str | None = None,
        provider: str | None = None,
        original_error: Exception | None = None,
        **kwargs: Any,
    ):
        context = kwargs.pop("context", {}) or {}
        if model:
            context["model"] = model
        if provider:
            context["provider"] = provider

        super().__init__(
            message=message,
            context=context,
            original_error=original_error,
            **kwargs,
        )
        self.model = model
        self.provider = provider


class LLMAuthenticationError(LLMError):
    """Raised when authentication with the LLM provider fails."""

    default_message = "LLM authentication failed"
    default_error_code = "LLM_AUTH_ERROR"
    default_category = ErrorCategory.AUTHENTICATION


class LLMRateLimitError(LLMError):
    """Raised when rate limits are exceeded."""

    default_message = "LLM rate limit exceeded"
    default_error_code = "LLM_RATE_LIMIT"
    default_category = ErrorCategory.RATE_LIMIT
    default_severity = ErrorSeverity.MEDIUM  # Often recoverable with retry

    def __init__(
        self,
        message: str | None = None,
        *,
        retry_after: float | None = None,
        **kwargs: Any,
    ):
        context = kwargs.pop("context", {}) or {}
        if retry_after is not None:
            context["retry_after_seconds"] = retry_after
        super().__init__(message, context=context, **kwargs)
        self.retry_after = retry_after


class LLMTimeoutError(LLMError):
    """Raised when a request times out."""

    default_message = "LLM request timed out"
    default_error_code = "LLM_TIMEOUT"
    default_category = ErrorCategory.TIMEOUT
    default_severity = ErrorSeverity.MEDIUM  # Often recoverable with retry

    def __init__(
        self,
        message: str | None = None,
        *,
        timeout: float | None = None,
        **kwargs: Any,
    ):
        context = kwargs.pop("context", {}) or {}
        if timeout is not None:
            context["timeout_seconds"] = timeout
        super().__init__(message, context=context, **kwargs)
        self.timeout = timeout


class LLMContextLengthError(LLMError):
    """Raised when the context length is exceeded."""

    default_message = "LLM context length exceeded"
    default_error_code = "LLM_CONTEXT_LENGTH"
    default_category = ErrorCategory.VALIDATION

    def __init__(
        self,
        message: str | None = None,
        *,
        max_tokens: int | None = None,
        requested_tokens: int | None = None,
        **kwargs: Any,
    ):
        context = kwargs.pop("context", {}) or {}
        if max_tokens is not None:
            context["max_tokens"] = max_tokens
        if requested_tokens is not None:
            context["requested_tokens"] = requested_tokens
        super().__init__(message, context=context, **kwargs)
        self.max_tokens = max_tokens
        self.requested_tokens = requested_tokens


class LLMInvalidRequestError(LLMError):
    """Raised when the request is invalid."""

    default_message = "Invalid LLM request"
    default_error_code = "LLM_INVALID_REQUEST"
    default_category = ErrorCategory.VALIDATION


class LLMServiceUnavailableError(LLMError):
    """Raised when the LLM service is unavailable."""

    default_message = "LLM service unavailable"
    default_error_code = "LLM_SERVICE_UNAVAILABLE"
    default_category = ErrorCategory.NETWORK
    default_severity = ErrorSeverity.HIGH


class LLMFallbackExhaustedError(LLMError):
    """Raised when all fallback models have been exhausted."""

    default_message = "All LLM fallback models exhausted"
    default_error_code = "LLM_FALLBACK_EXHAUSTED"
    default_severity = ErrorSeverity.CRITICAL

    def __init__(
        self,
        message: str | None = None,
        *,
        attempted_models: list[str] | None = None,
        errors: list[Exception] | None = None,
        **kwargs: Any,
    ):
        context = kwargs.pop("context", {}) or {}
        if attempted_models:
            context["attempted_models"] = attempted_models
        if errors:
            context["error_count"] = len(errors)
            context["error_types"] = [type(e).__name__ for e in errors]

        super().__init__(message, context=context, **kwargs)
        self.attempted_models = attempted_models or []
        self.errors = errors or []


class LLMToolCallError(LLMError):
    """Raised when a tool call fails."""

    default_message = "LLM tool call failed"
    default_error_code = "LLM_TOOL_CALL_ERROR"
    default_category = ErrorCategory.INTERNAL

    def __init__(
        self,
        message: str | None = None,
        *,
        tool_name: str | None = None,
        tool_arguments: dict[str, Any] | None = None,
        **kwargs: Any,
    ):
        context = kwargs.pop("context", {}) or {}
        if tool_name:
            context["tool_name"] = tool_name
        if tool_arguments:
            context["tool_arguments"] = tool_arguments
        super().__init__(message, context=context, **kwargs)
        self.tool_name = tool_name
        self.tool_arguments = tool_arguments


class LLMStreamingError(LLMError):
    """Raised when streaming fails."""

    default_message = "LLM streaming failed"
    default_error_code = "LLM_STREAMING_ERROR"
    default_severity = ErrorSeverity.MEDIUM


class LLMContentFilterError(LLMError):
    """Raised when content is filtered by the provider."""

    default_message = "Content filtered by LLM provider"
    default_error_code = "LLM_CONTENT_FILTER"
    default_category = ErrorCategory.VALIDATION
    default_severity = ErrorSeverity.MEDIUM

    def __init__(
        self,
        message: str | None = None,
        *,
        filter_reason: str | None = None,
        **kwargs: Any,
    ):
        context = kwargs.pop("context", {}) or {}
        if filter_reason:
            context["filter_reason"] = filter_reason
        super().__init__(message, context=context, **kwargs)
        self.filter_reason = filter_reason
