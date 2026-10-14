"""
Executor interfaces for agent execution.

Defines contracts for execution components.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from contextd_adk.agent.base import BaseAgent
    from contextd_adk.agent.types import (
        AgentEvent,
        AgentResponse,
        RunContext,
        RunState,
    )


class IExecutor(ABC):
    """Interface for core execution logic."""

    @abstractmethod
    async def execute_loop(
        self,
        agent: BaseAgent,
        messages: list[dict[str, Any]],
        context: RunContext,
        run_state: RunState,
    ) -> AgentResponse:
        """Execute the main conversation loop."""
        pass


class IStreamExecutor(ABC):
    """Interface for streaming execution."""

    @abstractmethod
    async def execute_stream(
        self,
        agent: BaseAgent,
        messages: list[dict[str, Any]],
        context: RunContext,
        run_state: RunState,
    ) -> AsyncIterator[AgentEvent]:
        """Execute with streaming output."""
        pass
