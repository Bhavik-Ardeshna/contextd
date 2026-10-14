"""Shared LLM gateway types and constants."""

from __future__ import annotations

from typing import Literal

LLMRole = Literal[
    "default",
    "extraction",
    "graph_enrichment",
    "agent_orchestration",
    "answer_synthesis",
    "property_synthesis",
    "schema_query_expansion",
    "schema_extraction",
    "schema_embedding",
]
LLMOperation = Literal["complete", "structured_output", "embed"]

ROLE_MODEL_FIELDS: dict[str, str] = {
    "default": "LLM_DEFAULT_MODEL",
    "extraction": "LLM_EXTRACTION_MODEL",
    "graph_enrichment": "LLM_EXTRACTION_MODEL",
    "agent_orchestration": "LLM_AGENT_MODEL",
    "answer_synthesis": "LLM_ANSWER_SYNTHESIS_MODEL",
    "property_synthesis": "LLM_PROPERTY_SYNTHESIS_MODEL",
    "schema_query_expansion": "LLM_SCHEMA_MODEL",
    "schema_extraction": "LLM_SCHEMA_MODEL",
    "schema_embedding": "LLM_SCHEMA_MODEL",
}

PROVIDER_API_KEY_SETTINGS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
}

OPERATION_TIMEOUT_FIELDS: dict[str, str] = {
    "complete": "LLM_COMPLETION_TIMEOUT_SECONDS",
    "structured_output": "LLM_STRUCTURED_OUTPUT_TIMEOUT_SECONDS",
    "embed": "LLM_EMBEDDING_TIMEOUT_SECONDS",
}

OPERATION_FAILURE_LABELS: dict[str, str] = {
    "complete": "completion",
    "structured_output": "structured output",
    "embed": "embedding",
}


class LLMGatewayError(RuntimeError):
    """Base error for ContextD LLM gateway failures."""


class LLMConfigurationError(LLMGatewayError):
    """Raised when LLM usage is requested but gateway configuration is incomplete."""


class LLMProviderError(LLMGatewayError):
    """Raised when a configured provider fails an LLM operation."""


class LLMTimeoutError(LLMProviderError):
    """Raised when a provider call exceeds the gateway timeout policy."""
