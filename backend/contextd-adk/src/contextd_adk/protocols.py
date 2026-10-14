"""Protocol definitions for SDK components.

These protocols allow custom implementations to be injected via the Container,
enabling easier testing and extensibility.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ILLMClient(Protocol):
    """Protocol for LLM clients."""

    async def chat(self, messages: list, **kwargs: Any) -> Any: ...
    async def chat_stream(self, messages: list, **kwargs: Any) -> AsyncIterator: ...
    def count_tokens(self, messages: list, model: str | None = None) -> int: ...


@runtime_checkable
class IMemoryClient(Protocol):
    """Protocol for memory clients."""

    @property
    def is_enabled(self) -> bool: ...
    async def search(self, query: str, **kwargs: Any) -> Any: ...
    async def add(self, messages: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class ISessionClient(Protocol):
    """Protocol for session clients."""

    @property
    def is_enabled(self) -> bool: ...
    async def get_conversation_history(self, session_id: str, **kwargs: Any) -> list: ...
    async def add_message(self, session_id: str, message: Any, **kwargs: Any) -> None: ...
