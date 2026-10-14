"""
Context Manager - Thread-safe context propagation for async operations.

Provides proper async context propagation using contextvars,
which is safe for concurrent async operations.
"""

from __future__ import annotations

import threading
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from contextd_adk.logging import get_logger

logger = get_logger(__name__)


# Context variables for async-safe context propagation
_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
_span_id: ContextVar[str | None] = ContextVar("span_id", default=None)
_user_id: ContextVar[str | None] = ContextVar("user_id", default=None)
_session_id: ContextVar[str | None] = ContextVar("session_id", default=None)
_run_id: ContextVar[str | None] = ContextVar("run_id", default=None)
_agent_name: ContextVar[str | None] = ContextVar("agent_name", default=None)


@dataclass
class ExecutionContext:
    """
    Immutable execution context for a single operation.

    This is the context that flows through all SDK operations.
    """

    trace_id: str | None = None
    span_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    run_id: str | None = None
    agent_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "agent_name": self.agent_name,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }

    def with_span(self, span_id: str) -> ExecutionContext:
        """Create new context with updated span_id."""
        return ExecutionContext(
            trace_id=self.trace_id,
            span_id=span_id,
            user_id=self.user_id,
            session_id=self.session_id,
            run_id=self.run_id,
            agent_name=self.agent_name,
            metadata=self.metadata.copy(),
            created_at=self.created_at,
        )

    def with_agent(self, agent_name: str) -> ExecutionContext:
        """Create new context with updated agent_name."""
        return ExecutionContext(
            trace_id=self.trace_id,
            span_id=self.span_id,
            user_id=self.user_id,
            session_id=self.session_id,
            run_id=self.run_id,
            agent_name=agent_name,
            metadata=self.metadata.copy(),
            created_at=self.created_at,
        )


class ContextManager:
    """
    Manages execution context using contextvars for async safety.

    This replaces global mutable state with async-safe context variables
    that work correctly with concurrent async operations.

    Example:
        ```python
        from contextd_adk.core.context import ContextManager

        ctx_manager = ContextManager()

        # Set context for current async task
        with ctx_manager.context(trace_id="trace-123", user_id="user-456"):
            # All operations in this context will have access to these values
            current = ctx_manager.get_current()
            print(current.trace_id)  # "trace-123"

            # Nested context
            with ctx_manager.span_context("span-789"):
                inner = ctx_manager.get_current()
                print(inner.span_id)  # "span-789"
                print(inner.trace_id)  # "trace-123" (inherited)
        ```
    """

    def __init__(self):
        """Initialize context manager."""
        self._lock = threading.Lock()

    def get_current(self) -> ExecutionContext:
        """
        Get the current execution context.

        Returns:
            ExecutionContext with current values
        """
        return ExecutionContext(
            trace_id=_trace_id.get(),
            span_id=_span_id.get(),
            user_id=_user_id.get(),
            session_id=_session_id.get(),
            run_id=_run_id.get(),
            agent_name=_agent_name.get(),
        )

    def set_context(
        self,
        trace_id: str | None = None,
        span_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
        agent_name: str | None = None,
    ) -> ContextToken:
        """
        Set context values and return token for restoration.

        Args:
            trace_id: Trace ID for observability
            span_id: Span ID for observability
            user_id: User identifier
            session_id: Session identifier
            run_id: Run identifier
            agent_name: Current agent name

        Returns:
            ContextToken that can be used to restore previous context
        """
        # Store previous values
        token = ContextToken(
            trace_id=_trace_id.get(),
            span_id=_span_id.get(),
            user_id=_user_id.get(),
            session_id=_session_id.get(),
            run_id=_run_id.get(),
            agent_name=_agent_name.get(),
        )

        # Set new values (only if provided)
        if trace_id is not None:
            _trace_id.set(trace_id)
        if span_id is not None:
            _span_id.set(span_id)
        if user_id is not None:
            _user_id.set(user_id)
        if session_id is not None:
            _session_id.set(session_id)
        if run_id is not None:
            _run_id.set(run_id)
        if agent_name is not None:
            _agent_name.set(agent_name)

        return token

    def restore_context(self, token: ContextToken) -> None:
        """
        Restore context from token.

        Args:
            token: Token from set_context
        """
        _trace_id.set(token.trace_id)
        _span_id.set(token.span_id)
        _user_id.set(token.user_id)
        _session_id.set(token.session_id)
        _run_id.set(token.run_id)
        _agent_name.set(token.agent_name)

    def clear_context(self) -> None:
        """Clear all context values."""
        _trace_id.set(None)
        _span_id.set(None)
        _user_id.set(None)
        _session_id.set(None)
        _run_id.set(None)
        _agent_name.set(None)

    def context(
        self,
        trace_id: str | None = None,
        span_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
        agent_name: str | None = None,
    ) -> ContextScope:
        """
        Context manager for setting execution context.

        Args:
            trace_id: Trace ID
            span_id: Span ID
            user_id: User ID
            session_id: Session ID
            run_id: Run ID
            agent_name: Agent name

        Returns:
            ContextScope for use with 'with' statement
        """
        return ContextScope(
            manager=self,
            trace_id=trace_id,
            span_id=span_id,
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
            agent_name=agent_name,
        )

    def span_context(self, span_id: str) -> ContextScope:
        """
        Create context for a new span, preserving other values.

        Args:
            span_id: New span ID

        Returns:
            ContextScope for use with 'with' statement
        """
        return ContextScope(
            manager=self,
            span_id=span_id,
        )

    def agent_context(self, agent_name: str) -> ContextScope:
        """
        Create context for an agent, preserving other values.

        Args:
            agent_name: Agent name

        Returns:
            ContextScope for use with 'with' statement
        """
        return ContextScope(
            manager=self,
            agent_name=agent_name,
        )


@dataclass
class ContextToken:
    """Token for restoring previous context."""

    trace_id: str | None = None
    span_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    run_id: str | None = None
    agent_name: str | None = None


class ContextScope:
    """
    Context manager scope for automatic context restoration.

    Used with 'with' statement to automatically restore context on exit.
    """

    def __init__(
        self,
        manager: ContextManager,
        trace_id: str | None = None,
        span_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
        agent_name: str | None = None,
    ):
        self._manager = manager
        self._trace_id = trace_id
        self._span_id = span_id
        self._user_id = user_id
        self._session_id = session_id
        self._run_id = run_id
        self._agent_name = agent_name
        self._token: ContextToken | None = None

    def __enter__(self) -> ExecutionContext:
        """Enter context."""
        self._token = self._manager.set_context(
            trace_id=self._trace_id,
            span_id=self._span_id,
            user_id=self._user_id,
            session_id=self._session_id,
            run_id=self._run_id,
            agent_name=self._agent_name,
        )
        return self._manager.get_current()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context and restore previous values."""
        if self._token is not None:
            self._manager.restore_context(self._token)

    async def __aenter__(self) -> ExecutionContext:
        """Enter async context."""
        return self.__enter__()

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit async context."""
        self.__exit__(exc_type, exc_val, exc_tb)


# Global context manager
_global_context_manager: ContextManager | None = None
_global_lock = threading.Lock()


def get_context_manager() -> ContextManager:
    """
    Get the global context manager.

    Returns:
        ContextManager instance
    """
    global _global_context_manager

    if _global_context_manager is None:
        with _global_lock:
            if _global_context_manager is None:
                _global_context_manager = ContextManager()

    return _global_context_manager


# Convenience functions
def get_current_context() -> ExecutionContext:
    """Get current execution context."""
    return get_context_manager().get_current()


def get_trace_id() -> str | None:
    """Get current trace ID."""
    return _trace_id.get()


def get_span_id() -> str | None:
    """Get current span ID."""
    return _span_id.get()


def get_user_id() -> str | None:
    """Get current user ID."""
    return _user_id.get()


def get_session_id() -> str | None:
    """Get current session ID."""
    return _session_id.get()


def get_run_id() -> str | None:
    """Get current run ID."""
    return _run_id.get()


def get_agent_name() -> str | None:
    """Get current agent name."""
    return _agent_name.get()
