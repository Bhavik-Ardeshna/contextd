"""
Tools module for the ContextD ADK SDK.

Provides MCP (Model Context Protocol) tool integration for extending
agent capabilities with external tools and resources.
"""

try:
    from .executor import ToolExecutor
    from .mcp import (
        MCPServer,
        MCPServerSse,
        MCPServerSseParams,
        MCPServerStdio,
        MCPServerStdioParams,
        MCPServerStreamableHttp,
        MCPServerStreamableHttpParams,
    )
    from .schema import (
        ensure_strict_json_schema,
        normalize_schema_for_llm,
    )
    from .types import (
        MCPToolArtifact,
        RunArtifacts,
        ToolContextConfig,
        ToolContextState,
        ToolContextVariable,
        ToolFilter,
        ToolFilterCallable,
        ToolFilterContext,
        ToolFilterStatic,
        create_static_tool_filter,
    )
    from .util import MCPUtil
except ImportError:
    pass

__all__ = [
    # MCP Server classes
    "MCPServer",
    "MCPServerSse",
    "MCPServerSseParams",
    "MCPServerStdio",
    "MCPServerStdioParams",
    "MCPServerStreamableHttp",
    "MCPServerStreamableHttpParams",
    # Utilities
    "MCPUtil",
    "ToolExecutor",
    # Schema normalization
    "normalize_schema_for_llm",
    "ensure_strict_json_schema",
    # Tool filtering
    "ToolFilter",
    "ToolFilterCallable",
    "ToolFilterContext",
    "ToolFilterStatic",
    "create_static_tool_filter",
    # Tool context (session/state management)
    "ToolContextConfig",
    "ToolContextState",
    "ToolContextVariable",
    # MCP artifacts (per-run)
    "MCPToolArtifact",
    "RunArtifacts",
]
