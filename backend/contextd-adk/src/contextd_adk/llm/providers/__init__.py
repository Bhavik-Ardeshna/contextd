"""
Provider router — selects the right LLM provider based on model name.
"""

from __future__ import annotations

from contextd_adk.llm.config import LLMConfig
from contextd_adk.llm.providers.base import BaseProvider


def get_provider(config: LLMConfig) -> BaseProvider:
    """
    Return the appropriate provider for a given LLMConfig.

    Routing rules (checked in order):
      - gemini/ or google/  → GeminiProvider (OpenAI compat endpoint)
      - claude/ or anthropic/ or starts with "claude-" → AnthropicProvider
      - everything else (gpt-*, azure/, etc.) → OpenAIProvider
    """
    from contextd_adk.config import settings

    model = config.model.lower()

    if any(model.startswith(p) for p in ("gemini/", "google/")):
        from contextd_adk.llm.providers.gemini_provider import GeminiProvider
        return GeminiProvider(api_key=settings.gemini_api_key)

    if any(model.startswith(p) for p in ("claude/", "anthropic/", "claude-")):
        from contextd_adk.llm.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider(api_key=settings.anthropic_api_key)

    # Default: OpenAI (handles gpt-*, azure/, openai/, etc.)
    from contextd_adk.llm.providers.openai_provider import OpenAIProvider
    return OpenAIProvider(
        api_key=config.api_key or settings.openai_api_key,
        organization=settings.openai_organization,
        api_base=config.api_base,
        api_version=config.api_version,
    )


__all__ = ["get_provider", "BaseProvider"]
