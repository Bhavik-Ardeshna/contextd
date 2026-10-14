"""
ContextD ADK SDK - A Python SDK for agentic AI orchestration.

This SDK provides a unified interface for multi-LLM provider support,
memory management, monitoring, guardrails, and multi-agent workflows.

Features:
- Multi-LLM support via direct provider SDKs (OpenAI, Anthropic, Gemini)
- Long-term memory with mem0-compatible vector providers
- Short-term memory with Redis sessions
- Full observability with Langfuse integration
- Automatic error reporting and logging
- Structured tracing for debugging and auditing
- Agent orchestration with handoffs
- Workflow agents (Router, Sequential, Parallel, Loop)
- Health checks and lifecycle management
- Per-model context window management
"""

from contextd_adk.config import settings

# Core (Lifecycle, Health, Context, Container)
from contextd_adk.core import (
    Container,
    ContainerConfig,
    HealthCheck,
    HealthCheckResult,
    HealthStatus,
    OrchestratorLifecycle,
    check_all_health,
    get_container,
    get_health_checker,
    get_lifecycle_manager,
    initialize_orchestrator,
    reset_container,
    shutdown_orchestrator,
    validate_configuration,
)

# Exceptions
from contextd_adk.exceptions import (
    ConfigurationError,
    ErrorCategory,
    ErrorSeverity,
    LangfuseError,
    NetworkError,
    ObservabilityError,
    OrchestratorError,
    ProviderError,
    TracingError,
    ValidationError,
    wrap_exception,
)

# LLM
from contextd_adk.llm import (
    CompressionResult,
    CompressionStrategy,
    ContextManagementConfig,
    LLMClient,
    LLMConfig,
    ProgressiveContextManager,
    get_progressive_context_manager,
)

# Logging (import first for other modules to use)
from contextd_adk.logging import (
    LogContext,
    LogLevel,
    get_logger,
    logger_for_module,
    setup_logging,
)

# Memory
from contextd_adk.memory import (
    # Base class (for custom providers)
    BaseMemoryProvider,
    # Intelligence layer
    IntelligenceConfig,
    IntelligentMemoryClient,
    # Types
    MemoryAddResult,
    # Client
    MemoryClient,
    # Config
    MemoryConfig,
    MemoryEntry,
    MemoryFilter,
    MemoryIsolationLevel,
    MemoryMetadata,
    # Scopes
    MemoryScope,
    MemorySearchResult,
    ScopeDefinition,
    # Provider utilities
    create_provider,
    get_global_memory_client,
    get_provider_class,
    get_scope_definition,
    initialize_global_memory,
    is_scope_registered,
    list_providers,
    list_scopes,
    register_provider,
    register_scope,
)

# Observability
from contextd_adk.observability import (
    ErrorReporter,
    ErrorReportingContext,
    GenerationSpan,
    MetricsCollector,
    ObservabilityConfig,
    Span,
    SpanLevel,
    Trace,
    TracingManager,
    observe,
    report_error,
    report_exception,
    trace_agent,
    trace_tool,
)

# Tools (MCP)
try:
    from contextd_adk.tools import (
        MCPServer,
        MCPServerSse,
        MCPServerSseParams,
        MCPServerStdio,
        MCPServerStdioParams,
        MCPServerStreamableHttp,
        MCPServerStreamableHttpParams,
        MCPUtil,
        ToolExecutor,
        ToolFilter,
        ToolFilterCallable,
        ToolFilterContext,
        ToolFilterStatic,
        create_static_tool_filter,
    )
except ImportError:
    # MCP not available (missing dependency)
    pass

# Temporal (optional -- requires `pip install contextd-adk[temporal]`)
try:
    from contextd_adk.temporal import (
        AgentRegistry,
        AgentStep,
        AgentWorkflow,
        ApprovalDecision,
        ApprovalRequest,
        ApprovalStep,
        HumanInLoopManager,
        ParallelStep,
        TemporalClient,
        TemporalConfig,
        WorkerManager,
        WorkflowInput,
        WorkflowResult,
        get_agent_registry,
        get_temporal_client,
        get_worker_manager,
        run_agent_activity,
    )
except ImportError:
    pass  # temporalio not installed

# Session
# Agent Orchestration
from contextd_adk.agent import (
    # Configuration
    AgentConfig,
    # Exceptions
    AgentError,
    AgentEvent,
    AgentExecutionError,
    AgentMemoryConfig,
    # Types
    AgentResponse,
    AgentRunner,
    # Base Agent
    BaseAgent,
    EventType,
    FailStrategy,
    Handoff,
    HandoffData,
    HandoffError,
    # Handoff Management
    HandoffManager,
    HandoffResult,
    LoopAgent,
    MaxTurnsExceededError,
    MergeStrategy,
    ParallelAgent,
    PlannerAgent,
    PlanningConfig,
    ReflectionAgent,
    ReflectionConfig,
    ResponseStatus,
    Route,
    # Workflow Agents
    RouterAgent,
    RunContext,
    RunnerConfig,
    RunState,
    # State Management
    RunStateManager,
    RunStatus,
    SequentialAgent,
    TerminationConfig,
    TerminationType,
    agent_as_tool,
    create_agent,
    create_loop_agent,
    create_parallel_agent,
    create_planner_agent,
    create_reflection_agent,
    # Factory Functions
    create_router_agent,
    create_sequential_agent,
    generate_critique_prompt,
    get_global_state_manager,
)
from contextd_adk.agent import (
    MemoryScope as AgentMemoryScope,
)
from contextd_adk.session import (
    SessionClient,
    SessionConfig,
    get_global_session_client,
    initialize_global_session_client,
)

__version__ = "0.2.0"

__all__ = [
    # Version
    "__version__",
    # Config
    "settings",
    # Core - Lifecycle & Health
    "OrchestratorLifecycle",
    "get_lifecycle_manager",
    "initialize_orchestrator",
    "shutdown_orchestrator",
    "HealthCheck",
    "HealthCheckResult",
    "HealthStatus",
    "get_health_checker",
    "check_all_health",
    # Core - Configuration Validation
    "validate_configuration",
    # Core - Dependency Injection
    "Container",
    "ContainerConfig",
    "get_container",
    "reset_container",
    # Logging
    "setup_logging",
    "get_logger",
    "logger_for_module",
    "LogContext",
    "LogLevel",
    # Exceptions
    "OrchestratorError",
    "ConfigurationError",
    "ValidationError",
    "ObservabilityError",
    "LangfuseError",
    "TracingError",
    "NetworkError",
    "ProviderError",
    "ErrorCategory",
    "ErrorSeverity",
    "wrap_exception",
    # LLM
    "LLMClient",
    "LLMConfig",
    # Context Management
    "CompressionStrategy",
    "CompressionResult",
    "ContextManagementConfig",
    "ProgressiveContextManager",
    "get_progressive_context_manager",
    # Memory - Client
    "MemoryClient",
    "get_global_memory_client",
    "initialize_global_memory",
    # Memory - Intelligence layer
    "IntelligentMemoryClient",
    "IntelligenceConfig",
    # Memory - Config
    "MemoryConfig",
    # Memory - Scopes
    "MemoryScope",
    "MemoryIsolationLevel",
    "ScopeDefinition",
    "register_scope",
    "get_scope_definition",
    "list_scopes",
    "is_scope_registered",
    # Memory - Types
    "MemoryEntry",
    "MemorySearchResult",
    "MemoryAddResult",
    "MemoryMetadata",
    "MemoryFilter",
    # Memory - Base class (for custom providers)
    "BaseMemoryProvider",
    # Memory - Provider utilities
    "create_provider",
    "get_provider_class",
    "list_providers",
    "register_provider",
    # Session
    "SessionClient",
    "SessionConfig",
    "get_global_session_client",
    "initialize_global_session_client",
    # Observability
    "ObservabilityConfig",
    "TracingManager",
    "Trace",
    "Span",
    "GenerationSpan",
    "SpanLevel",
    "observe",
    "trace_tool",
    "trace_agent",
    "MetricsCollector",
    # Error Reporting
    "ErrorReporter",
    "ErrorReportingContext",
    "report_error",
    "report_exception",
    # Tools (MCP)
    "MCPServer",
    "MCPServerSse",
    "MCPServerSseParams",
    "MCPServerStdio",
    "MCPServerStdioParams",
    "MCPServerStreamableHttp",
    "MCPServerStreamableHttpParams",
    "MCPUtil",
    "ToolExecutor",
    "ToolFilter",
    "ToolFilterCallable",
    "ToolFilterContext",
    "ToolFilterStatic",
    "create_static_tool_filter",
    # Agent Orchestration
    "BaseAgent",
    "AgentRunner",
    "create_agent",
    "agent_as_tool",
    # Workflow Agents
    "RouterAgent",
    "SequentialAgent",
    "ParallelAgent",
    "LoopAgent",
    "ReflectionAgent",
    "create_router_agent",
    "create_sequential_agent",
    "create_parallel_agent",
    "create_loop_agent",
    "create_planner_agent",
    "create_reflection_agent",
    "generate_critique_prompt",
    "PlannerAgent",
    "PlanningConfig",
    # Reasoning Configuration
    "ReflectionConfig",
    # Handoff
    "HandoffManager",
    "Handoff",
    "HandoffData",
    "HandoffResult",
    # State Management
    "RunStateManager",
    "get_global_state_manager",
    # Agent Types
    "AgentResponse",
    "AgentEvent",
    "EventType",
    "ResponseStatus",
    "RunStatus",
    "RunState",
    "RunContext",
    "Route",
    "TerminationConfig",
    "TerminationType",
    "MergeStrategy",
    "FailStrategy",
    "AgentMemoryScope",
    # Agent Configuration
    "AgentConfig",
    "AgentMemoryConfig",
    "RunnerConfig",
    # Agent Exceptions
    "AgentError",
    "AgentExecutionError",
    "MaxTurnsExceededError",
    "HandoffError",
    # Temporal (optional)
    "TemporalClient",
    "TemporalConfig",
    "WorkerManager",
    "AgentRegistry",
    "get_agent_registry",
    "get_temporal_client",
    "get_worker_manager",
    "HumanInLoopManager",
    "AgentStep",
    "ApprovalStep",
    "ParallelStep",
    "WorkflowInput",
    "WorkflowResult",
    "ApprovalRequest",
    "ApprovalDecision",
    "AgentWorkflow",
    "run_agent_activity",
]
