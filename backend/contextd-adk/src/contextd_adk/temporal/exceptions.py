"""
Temporal integration exceptions.

Provides a hierarchy of exception classes for Temporal-specific errors.

Exception Hierarchy:
    OrchestratorError (base, from contextd_adk.exceptions)
    └── TemporalError
        ├── TemporalConnectionError
        ├── TemporalWorkflowError
        ├── TemporalActivityError
        ├── AgentNotRegisteredError
        ├── ApprovalTimeoutError
        └── WorkflowCancelledError
"""

from __future__ import annotations

from typing import Any

from contextd_adk.exceptions import ErrorCategory, ErrorSeverity, OrchestratorError


class TemporalError(OrchestratorError):
    """Base exception for all Temporal integration errors."""

    default_message = "Temporal integration error"
    default_error_code = "TEMPORAL_ERROR"
    default_category = ErrorCategory.INTERNAL
    default_severity = ErrorSeverity.HIGH


class TemporalConnectionError(TemporalError):
    """Raised when connection to Temporal server fails."""

    default_message = "Failed to connect to Temporal server"
    default_error_code = "TEMPORAL_CONNECTION_ERROR"
    default_category = ErrorCategory.NETWORK

    def __init__(
        self,
        message: str | None = None,
        *,
        host: str | None = None,
        namespace: str | None = None,
        **kwargs: Any,
    ):
        context = kwargs.pop("context", {}) or {}
        if host:
            context["host"] = host
        if namespace:
            context["namespace"] = namespace
        super().__init__(message, context=context, **kwargs)


class TemporalWorkflowError(TemporalError):
    """Raised when a Temporal workflow encounters an error."""

    default_message = "Temporal workflow error"
    default_error_code = "TEMPORAL_WORKFLOW_ERROR"

    def __init__(
        self,
        message: str | None = None,
        *,
        workflow_id: str | None = None,
        workflow_type: str | None = None,
        **kwargs: Any,
    ):
        context = kwargs.pop("context", {}) or {}
        if workflow_id:
            context["workflow_id"] = workflow_id
        if workflow_type:
            context["workflow_type"] = workflow_type
        super().__init__(message, context=context, **kwargs)


class TemporalActivityError(TemporalError):
    """Raised when a Temporal activity encounters an error."""

    default_message = "Temporal activity error"
    default_error_code = "TEMPORAL_ACTIVITY_ERROR"

    def __init__(
        self,
        message: str | None = None,
        *,
        activity_name: str | None = None,
        agent_name: str | None = None,
        **kwargs: Any,
    ):
        context = kwargs.pop("context", {}) or {}
        if activity_name:
            context["activity_name"] = activity_name
        if agent_name:
            context["agent_name"] = agent_name
        super().__init__(message, context=context, **kwargs)


class AgentNotRegisteredError(TemporalError):
    """Raised when an agent is not found in the registry."""

    default_message = "Agent not registered in the Temporal agent registry"
    default_error_code = "AGENT_NOT_REGISTERED"
    default_category = ErrorCategory.CONFIGURATION
    default_severity = ErrorSeverity.HIGH

    def __init__(
        self,
        message: str | None = None,
        *,
        agent_name: str | None = None,
        available_agents: list[str] | None = None,
        **kwargs: Any,
    ):
        context = kwargs.pop("context", {}) or {}
        if agent_name:
            context["agent_name"] = agent_name
        if available_agents is not None:
            context["available_agents"] = available_agents
        super().__init__(message, context=context, **kwargs)


class ApprovalTimeoutError(TemporalError):
    """Raised when a human-in-the-loop approval times out."""

    default_message = "Approval request timed out"
    default_error_code = "APPROVAL_TIMEOUT"
    default_severity = ErrorSeverity.MEDIUM

    def __init__(
        self,
        message: str | None = None,
        *,
        request_id: str | None = None,
        timeout_seconds: int | None = None,
        **kwargs: Any,
    ):
        context = kwargs.pop("context", {}) or {}
        if request_id:
            context["request_id"] = request_id
        if timeout_seconds is not None:
            context["timeout_seconds"] = timeout_seconds
        super().__init__(message, context=context, **kwargs)


class WorkflowCancelledError(TemporalError):
    """Raised when a workflow is cancelled via signal."""

    default_message = "Workflow was cancelled"
    default_error_code = "WORKFLOW_CANCELLED"
    default_severity = ErrorSeverity.MEDIUM

    def __init__(
        self,
        message: str | None = None,
        *,
        workflow_id: str | None = None,
        **kwargs: Any,
    ):
        context = kwargs.pop("context", {}) or {}
        if workflow_id:
            context["workflow_id"] = workflow_id
        super().__init__(message, context=context, **kwargs)
