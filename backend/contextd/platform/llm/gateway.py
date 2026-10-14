"""Central ContextD LLM gateway.

This module owns model selection and provider construction for direct LLM usage.
Search providers still live under ``contextd.search.providers``; production code
that needs chat/structured output/embeddings should come through this boundary.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, Dict, List

from pydantic import BaseModel

from contextd.core.config import settings as default_settings
from contextd.platform.llm.redaction import (
    messages_input_metadata,
    redact_llm_messages,
    texts_input_metadata,
)
from contextd.platform.llm.settings import (
    clean_optional_text,
    clean_required_text,
    configured_llm_model,
    non_negative_float,
    normalize_role,
    positive_float,
    positive_int,
)
from contextd.platform.llm.telemetry import (
    failure_message,
    record_llm_attempt,
    timeout_message,
)
from contextd.platform.llm.types import (
    OPERATION_TIMEOUT_FIELDS,
    PROVIDER_API_KEY_SETTINGS,
    LLMConfigurationError,
    LLMGatewayError,
    LLMOperation,
    LLMProviderError,
    LLMRole,
    LLMTimeoutError,
)
from contextd.search.providers._base import BaseProvider
from contextd.search.providers.openai import OpenAIProvider
from contextd.search.providers.schemas import (
    EmbeddingModelConfig,
    LLMModelConfig,
    ProviderModelSpec,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ContextDLLMGateway",
    "LLMConfigurationError",
    "LLMGatewayError",
    "LLMOperation",
    "LLMProviderError",
    "LLMRole",
    "LLMTimeoutError",
    "configured_llm_model",
    "get_llm_gateway",
    "redact_llm_messages",
]


def get_llm_gateway(app_settings: Any | None = None) -> "ContextDLLMGateway":
    """Create a gateway bound to the current settings object."""
    return ContextDLLMGateway(app_settings or default_settings)


class ContextDLLMGateway:
    """Gateway for direct LLM calls made by ContextD platform code."""

    def __init__(self, app_settings: Any | None = None) -> None:
        self.settings = app_settings or default_settings

    def provider_name(self) -> str:
        """Return the normalized configured provider name."""
        provider = str(getattr(self.settings, "LLM_PROVIDER", "openai") or "openai")
        provider = provider.strip().lower().replace("_", "-")
        if provider not in PROVIDER_API_KEY_SETTINGS:
            raise LLMConfigurationError(f"Unsupported LLM_PROVIDER '{provider}'")
        return provider

    def api_key_setting_name(self) -> str:
        """Return the environment setting name that must hold the provider API key."""
        return PROVIDER_API_KEY_SETTINGS[self.provider_name()]

    def has_api_key(self) -> bool:
        """Return True when the configured provider has a non-empty API key."""
        return bool(clean_optional_text(getattr(self.settings, self.api_key_setting_name(), None)))

    def model_name(self, role: LLMRole = "default") -> str:
        """Return the configured model for a role."""
        return configured_llm_model(role, self.settings)

    def model_spec(
        self,
        role: LLMRole = "default",
        *,
        include_embedding: bool = False,
        embedding_dimensions: int | None = None,
    ) -> ProviderModelSpec:
        """Build a provider model spec for the requested role."""
        embedding_model = (
            self.embedding_model_config(embedding_dimensions) if include_embedding else None
        )
        llm_model = None
        if not include_embedding:
            llm_model = LLMModelConfig(
                name=self.model_name(role),
                tokenizer=clean_required_text(
                    getattr(self.settings, "LLM_TOKENIZER", None),
                    "LLM_TOKENIZER",
                ),
                context_window=int(getattr(self.settings, "LLM_CONTEXT_WINDOW", 128000)),
            )
        return ProviderModelSpec(llm_model=llm_model, embedding_model=embedding_model)

    def embedding_model_config(self, dimensions: int | None = None) -> EmbeddingModelConfig:
        """Return the configured embedding model for the requested dimensions."""
        target_dimensions = 3072 if dimensions == 3072 else 1536
        field_name = (
            "LLM_EMBEDDING_MODEL_3072"
            if target_dimensions == 3072
            else "LLM_EMBEDDING_MODEL_1536"
        )
        return EmbeddingModelConfig(
            name=clean_required_text(getattr(self.settings, field_name, None), field_name),
            tokenizer=clean_required_text(
                getattr(self.settings, "LLM_EMBEDDING_TOKENIZER", None),
                "LLM_EMBEDDING_TOKENIZER",
            ),
            dimensions=target_dimensions,
            max_tokens=int(getattr(self.settings, "LLM_EMBEDDING_MAX_TOKENS", 8192)),
        )

    def create_provider(
        self,
        role: LLMRole = "default",
        *,
        ctx: Any | None = None,
        include_embedding: bool = False,
        embedding_dimensions: int | None = None,
    ) -> BaseProvider:
        """Construct the configured provider for the requested LLM role."""
        provider_name = self.provider_name()
        api_key_setting = self.api_key_setting_name()
        api_key = clean_optional_text(getattr(self.settings, api_key_setting, None))
        if not api_key:
            raise LLMConfigurationError(f"{api_key_setting} must be configured for LLM usage")

        model_spec = self.model_spec(
            role,
            include_embedding=include_embedding,
            embedding_dimensions=embedding_dimensions,
        )
        provider_context = ctx or SimpleNamespace(logger=logger)

        if provider_name == "openai":
            return OpenAIProvider(api_key=api_key, model_spec=model_spec, ctx=provider_context)

        raise LLMConfigurationError(f"Unsupported LLM_PROVIDER '{provider_name}'")

    def operation_timeout_seconds(self, operation: LLMOperation) -> float:
        """Return the timeout policy for a gateway operation."""
        field_name = OPERATION_TIMEOUT_FIELDS[operation]
        fallback = 300.0 if operation == "embed" else 120.0
        return positive_float(getattr(self.settings, field_name, fallback), field_name)

    def max_attempts(self) -> int:
        """Return the configured maximum attempts for retryable provider failures."""
        return positive_int(getattr(self.settings, "LLM_MAX_ATTEMPTS", 2), "LLM_MAX_ATTEMPTS")

    def retry_backoff_seconds(self) -> float:
        """Return the configured linear retry backoff interval."""
        return non_negative_float(
            getattr(self.settings, "LLM_RETRY_BACKOFF_SECONDS", 0.5),
            "LLM_RETRY_BACKOFF_SECONDS",
        )

    async def complete(
        self,
        messages: List[Dict[str, str]],
        *,
        role: LLMRole = "default",
        ctx: Any | None = None,
    ) -> str:
        """Generate plain text for the requested role."""
        return await self._run_provider_operation(
            operation="complete",
            role=role,
            ctx=ctx,
            runner=lambda provider: provider.generate(messages),
            input_metadata=messages_input_metadata(messages),
        )

    async def structured_output(
        self,
        messages: List[Dict[str, str]],
        *,
        schema: type[BaseModel],
        role: LLMRole = "default",
        ctx: Any | None = None,
    ) -> BaseModel:
        """Generate structured output for the requested role."""
        return await self._run_provider_operation(
            operation="structured_output",
            role=role,
            ctx=ctx,
            runner=lambda provider: provider.structured_output(messages=messages, schema=schema),
            input_metadata=messages_input_metadata(messages),
        )

    async def embed(
        self,
        texts: List[str],
        *,
        role: LLMRole = "schema_embedding",
        ctx: Any | None = None,
        dimensions: int | None = None,
    ) -> List[List[float]]:
        """Generate embeddings through the configured gateway provider."""
        return await self._run_provider_operation(
            operation="embed",
            role=role,
            ctx=ctx,
            runner=lambda provider: provider.embed(texts, dimensions=dimensions),
            input_metadata=texts_input_metadata(texts),
            include_embedding=True,
            embedding_dimensions=dimensions,
        )

    async def _run_provider_operation(
        self,
        *,
        operation: LLMOperation,
        role: LLMRole,
        ctx: Any | None,
        runner: Callable[[BaseProvider], Awaitable[Any]],
        input_metadata: dict[str, Any],
        include_embedding: bool = False,
        embedding_dimensions: int | None = None,
    ) -> Any:
        """Run a provider operation with timeout, retry, metrics, and redacted logging."""
        role_key = normalize_role(role)
        provider_name = self.provider_name()
        model_name = (
            self.embedding_model_config(embedding_dimensions).name
            if include_embedding
            else self.model_name(role)
        )
        timeout_seconds = self.operation_timeout_seconds(operation)
        max_attempts = self.max_attempts()
        backoff_seconds = self.retry_backoff_seconds()

        for attempt in range(1, max_attempts + 1):
            started_at = time.perf_counter()
            try:
                provider = self.create_provider(
                    role,
                    ctx=ctx,
                    include_embedding=include_embedding,
                    embedding_dimensions=embedding_dimensions,
                )
                result = await asyncio.wait_for(runner(provider), timeout=timeout_seconds)
                duration_seconds = time.perf_counter() - started_at
                record_llm_attempt(
                    ctx=ctx,
                    operation=operation,
                    role=role_key,
                    provider=provider_name,
                    model=model_name,
                    status="success",
                    attempt=attempt,
                    max_attempts=max_attempts,
                    duration_seconds=duration_seconds,
                    timeout_seconds=timeout_seconds,
                    input_metadata=input_metadata,
                )
                return result
            except LLMConfigurationError:
                raise
            except asyncio.TimeoutError as exc:
                duration_seconds = time.perf_counter() - started_at
                will_retry = attempt < max_attempts
                record_llm_attempt(
                    ctx=ctx,
                    operation=operation,
                    role=role_key,
                    provider=provider_name,
                    model=model_name,
                    status="timeout",
                    attempt=attempt,
                    max_attempts=max_attempts,
                    duration_seconds=duration_seconds,
                    timeout_seconds=timeout_seconds,
                    input_metadata=input_metadata,
                    error=exc,
                    will_retry=will_retry,
                )
                if will_retry:
                    await asyncio.sleep(backoff_seconds * attempt)
                    continue

                raise LLMTimeoutError(
                    timeout_message(operation, role_key, attempt, timeout_seconds)
                ) from exc
            except Exception as exc:
                duration_seconds = time.perf_counter() - started_at
                retryable = BaseProvider.is_retryable_error(exc)
                will_retry = retryable and attempt < max_attempts
                record_llm_attempt(
                    ctx=ctx,
                    operation=operation,
                    role=role_key,
                    provider=provider_name,
                    model=model_name,
                    status="error",
                    attempt=attempt,
                    max_attempts=max_attempts,
                    duration_seconds=duration_seconds,
                    timeout_seconds=timeout_seconds,
                    input_metadata=input_metadata,
                    error=exc,
                    will_retry=will_retry,
                )
                if will_retry:
                    await asyncio.sleep(backoff_seconds * attempt)
                    continue

                raise LLMProviderError(failure_message(operation, role_key, attempt, exc)) from exc

        raise LLMProviderError(f"LLM {operation} failed for role '{role_key}'")
