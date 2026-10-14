"""
Core module for ContextD ADK SDK.

Provides foundational infrastructure including:
- Health checks for all dependencies
- Resource lifecycle management
- Connection verification
- Graceful shutdown handling
- Dependency injection container
- Configuration validation
"""

from contextd_adk.core.container import (
    Container,
    ContainerConfig,
    get_container,
    reset_container,
)
from contextd_adk.core.health import (
    HealthCheck,
    HealthCheckResult,
    HealthStatus,
    check_all_health,
    get_health_checker,
)
from contextd_adk.core.lifecycle import (
    ConfigurationError,
    OrchestratorLifecycle,
    get_lifecycle_manager,
    initialize_orchestrator,
    shutdown_orchestrator,
    validate_configuration,
)

__all__ = [
    # Health
    "HealthCheck",
    "HealthCheckResult",
    "HealthStatus",
    "get_health_checker",
    "check_all_health",
    # Lifecycle
    "ConfigurationError",
    "OrchestratorLifecycle",
    "get_lifecycle_manager",
    "initialize_orchestrator",
    "shutdown_orchestrator",
    "validate_configuration",
    # Container (DI)
    "Container",
    "ContainerConfig",
    "get_container",
    "reset_container",
]
