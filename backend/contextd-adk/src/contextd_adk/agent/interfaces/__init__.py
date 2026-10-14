"""
Agent interfaces and abstractions.

Defines clear contracts for extensibility and testability.
"""

from contextd_adk.agent.interfaces.executor_interface import (
    IExecutor,
    IStreamExecutor,
)
from contextd_adk.agent.interfaces.handler_interface import (
    IHandoffExecutor,
    IMessageBuilder,
    IToolHandler,
)
from contextd_adk.agent.interfaces.service_interface import (
    IContextService,
    IExecutionService,
    IMemoryService,
    ISessionService,
    IToolService,
)

__all__ = [
    # Executor interfaces
    "IExecutor",
    "IStreamExecutor",
    # Service interfaces
    "IExecutionService",
    "IContextService",
    "ISessionService",
    "IMemoryService",
    "IToolService",
    # Handler interfaces
    "IMessageBuilder",
    "IToolHandler",
    "IHandoffExecutor",
]
