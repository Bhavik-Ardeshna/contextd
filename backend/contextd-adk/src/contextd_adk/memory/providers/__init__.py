"""
Memory Providers - Provider implementations for the memory module.

This module provides a registry for memory providers and exports
available provider implementations.

Available Providers:
    - Mem0Provider: Uses mem0 with Milvus for vector storage

Adding New Providers:
    1. Create a new file in this directory (e.g., pinecone.py)
    2. Implement the BaseMemoryProvider interface
    3. Register the provider in PROVIDER_REGISTRY
    4. Export from this __init__.py
"""

from contextd_adk.memory.base import BaseMemoryProvider
from contextd_adk.memory.config import MemoryConfig

# Provider registry maps provider names to their classes
PROVIDER_REGISTRY: dict[str, type[BaseMemoryProvider]] = {}

# Try to import Mem0Provider - may fail if mem0ai not installed
try:
    from contextd_adk.memory.providers.mem0 import Mem0Provider

    _MEM0_AVAILABLE = True
except ImportError:
    Mem0Provider = None  # type: ignore
    _MEM0_AVAILABLE = False


def register_provider(name: str, provider_class: type[BaseMemoryProvider]) -> None:
    """
    Register a memory provider.

    Args:
        name: Provider name (e.g., "mem0", "pinecone")
        provider_class: Provider class implementing BaseMemoryProvider
    """
    PROVIDER_REGISTRY[name] = provider_class


def get_provider_class(name: str) -> type[BaseMemoryProvider]:
    """
    Get a provider class by name.

    Args:
        name: Provider name

    Returns:
        Provider class

    Raises:
        ValueError: If provider is not found
    """
    if name not in PROVIDER_REGISTRY:
        available = ", ".join(PROVIDER_REGISTRY.keys()) if PROVIDER_REGISTRY else "none"
        raise ValueError(f"Unknown memory provider: {name}. Available providers: {available}")
    return PROVIDER_REGISTRY[name]


def create_provider(name: str, config: MemoryConfig) -> BaseMemoryProvider:
    """
    Create a provider instance.

    Args:
        name: Provider name
        config: Memory configuration

    Returns:
        Provider instance
    """
    provider_class = get_provider_class(name)
    return provider_class(config)


def list_providers() -> list[str]:
    """
    List available provider names.

    Returns:
        List of provider names
    """
    return list(PROVIDER_REGISTRY.keys())


def is_mem0_available() -> bool:
    """Check if mem0 provider is available."""
    return _MEM0_AVAILABLE


# Register default providers at module load
if _MEM0_AVAILABLE and Mem0Provider is not None:
    register_provider("mem0", Mem0Provider)


__all__ = [
    # Base class
    "BaseMemoryProvider",
    # Registry
    "PROVIDER_REGISTRY",
    # Functions
    "register_provider",
    "get_provider_class",
    "create_provider",
    "list_providers",
    "is_mem0_available",
    # Providers (conditional)
    "Mem0Provider",
]
