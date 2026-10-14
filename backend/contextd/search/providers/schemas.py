"""Model specification schemas for LLM providers."""

from typing import Optional

from pydantic import BaseModel, field_validator


class LLMModelConfig(BaseModel):
    """Configuration for LLM models (generation and structured output)."""

    name: str
    tokenizer: str
    context_window: int

    @field_validator("tokenizer")
    @classmethod
    def validate_tokenizer(cls, v: str) -> str:
        """Validate tokenizer is not empty."""
        if not v or not v.strip():
            raise ValueError("Tokenizer is required for LLM models")
        return v


class EmbeddingModelConfig(BaseModel):
    """Configuration for embedding models."""

    name: str
    tokenizer: str
    dimensions: int
    max_tokens: int

    @field_validator("tokenizer")
    @classmethod
    def validate_tokenizer(cls, v: str) -> str:
        """Validate tokenizer is not empty."""
        if not v or not v.strip():
            raise ValueError("Tokenizer is required for embedding models")
        return v

    @field_validator("dimensions", "max_tokens")
    @classmethod
    def validate_positive(cls, v: int) -> int:
        """Validate positive integers."""
        if v <= 0:
            raise ValueError("Must be positive")
        return v


class RerankModelConfig(BaseModel):
    """Configuration for reranking models.

    Note: tokenizer and context_window are optional because Cohere's
    specialized rerank API doesn't use them. Only LLM-based reranking
    (OpenAI/Groq) needs these fields.
    """

    name: str
    tokenizer: Optional[str] = None
    context_window: Optional[int] = None
    max_tokens_per_doc: Optional[int] = None
    max_documents: Optional[int] = None


class ProviderModelSpec(BaseModel):
    """Complete model specification for a provider.

    Contains type-specific model configurations for different operations.
    Each field is optional because a provider might not support all operation types.
    For example:
    - Groq has llm_model and rerank_model, but not embedding_model
    - Cohere only has rerank_model
    - OpenAI has all three
    """

    llm_model: Optional[LLMModelConfig] = None
    embedding_model: Optional[EmbeddingModelConfig] = None
    rerank_model: Optional[RerankModelConfig] = None
