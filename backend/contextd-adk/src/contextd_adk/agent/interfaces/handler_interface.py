"""
Handler interfaces for agent execution components.

Defines contracts for specialized handlers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from contextd_adk.agent.base import BaseAgent
    from contextd_adk.agent.types import (
        HandoffResult,
        RunContext,
        RunState,
    )
    from contextd_adk.llm.types import ToolCallInput
    from contextd_adk.tools.types import ToolContextState


class IMessageBuilder(ABC):
    """Interface for message preparation."""

    @abstractmethod
    async def prepare_messages(
        self,
        agent: BaseAgent,
        input: str | list[dict[str, Any]] | list[Any],
        context: RunContext,
        tool_context_state: ToolContextState | None = None,
    ) -> list[dict[str, Any]]:
        """Prepare messages for agent execution."""
        pass


class IToolHandler(ABC):
    """Interface for tool execution handling."""

    @abstractmethod
    async def execute_tool_call(
        self,
        agent: BaseAgent,
        tool_call: ToolCallInput,
        context: RunContext,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Execute a single tool call."""
        pass

    @abstractmethod
    async def execute_tools_batch(
        self,
        agent: BaseAgent,
        tool_calls: list[ToolCallInput],
        context: RunContext,
    ) -> list[dict[str, Any]]:
        """Execute multiple tool calls."""
        pass


class IHandoffExecutor(ABC):
    """Interface for handoff execution."""

    @abstractmethod
    async def execute_handoff(
        self,
        agent: BaseAgent,
        target_name: str,
        tool_call: Any,
        messages: list[dict[str, Any]],
        context: RunContext,
        run_state: RunState,
    ) -> HandoffResult:
        """Execute a handoff to another agent."""
        pass
