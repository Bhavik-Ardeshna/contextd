"""
Tool Handler - Handles tool execution during agent runs.

Extracted from AgentRunner to provide clean separation of concerns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from contextd_adk.agent.interfaces.handler_interface import IToolHandler
from contextd_adk.agent.services.tool_service import ToolService
from contextd_adk.agent.types import ToolExecutionSummary

if TYPE_CHECKING:
    from contextd_adk.agent.base import BaseAgent
    from contextd_adk.agent.types import RunContext
    from contextd_adk.llm.types import ToolCallInput


class ToolHandler(IToolHandler):
    """
    Handler for tool execution.

    Delegates to ToolService for actual execution.
    """

    def __init__(
        self,
        tool_service: ToolService | None = None,
    ):
        """
        Initialize tool handler.

        Args:
            tool_service: Tool service instance
        """
        self._tool_service = tool_service

    async def execute_tool_call(
        self,
        agent: BaseAgent,
        tool_call: ToolCallInput,
        context: RunContext,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Execute a single tool call."""
        if not self._tool_service:
            raise RuntimeError("ToolService not provided to ToolHandler")
        return await self._tool_service.execute_tool_call(agent, tool_call, context)

    async def execute_tools_batch(
        self,
        agent: BaseAgent,
        tool_calls: list[ToolCallInput],
        context: RunContext,
        tool_summary: ToolExecutionSummary | None = None,
    ) -> list[dict[str, Any]]:
        """Execute multiple tool calls."""
        if not self._tool_service:
            raise RuntimeError("ToolService not provided to ToolHandler")

        # Create summary if not provided
        if tool_summary is None:
            tool_summary = ToolExecutionSummary()

        results = await self._tool_service.execute_tools_batch(
            agent, tool_calls, context, tool_summary=tool_summary
        )
        return results
