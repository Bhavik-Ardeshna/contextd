"""
Exceptions for the tools module.
"""

from typing import Any

from contextd_adk.exceptions import OrchestratorError


class ToolError(OrchestratorError):
    """Base exception for tool-related errors."""

    default_message = "Tool error"
    default_error_code = "TOOL_ERROR"


class MCPError(ToolError):
    """Raised when MCP operations fail."""

    default_message = "MCP error"
    default_error_code = "MCP_ERROR"

    def __init__(
        self,
        message: str | None = None,
        *,
        server_name: str | None = None,
        tool_name: str | None = None,
        **kwargs: Any,
    ):
        context = kwargs.pop("context", {}) or {}
        if server_name:
            context["server_name"] = server_name
        if tool_name:
            context["tool_name"] = tool_name
        super().__init__(message, context=context, **kwargs)


class MCPConnectionError(MCPError):
    """Raised when MCP connection fails."""

    default_message = "MCP connection error"
    default_error_code = "MCP_CONNECTION_ERROR"


class MCPToolError(MCPError):
    """Raised when MCP tool invocation fails."""

    default_message = "MCP tool error"
    default_error_code = "MCP_TOOL_ERROR"
