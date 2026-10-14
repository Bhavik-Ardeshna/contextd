"""Database graph configuration.

Unified configuration combining connection, schema, graph LLM, and embedding settings.
"""

from typing import Dict, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from contextd.platform.configs.database.schema import DatabaseTable


def _default_llm_provider() -> str:
    """Return the configured gateway provider for database graph settings."""
    from contextd.core.config import settings

    return settings.LLM_PROVIDER


def _default_graph_llm_model() -> str:
    """Return the configured extraction model for database graph settings."""
    from contextd.platform.llm.gateway import configured_llm_model

    return configured_llm_model("extraction")


def _default_embedding_model() -> str:
    """Return the configured large embedding model for database graph settings."""
    from contextd.core.config import settings

    return settings.LLM_EMBEDDING_MODEL_3072


class DatabaseConnectionConfig(BaseModel):
    """Database connection configuration."""

    model_config = ConfigDict(populate_by_name=True)

    host: str = Field(..., description="Database host")
    port: int = Field(default=5432, description="Database port")
    database: str = Field(..., description="Database name")
    user: str = Field(..., description="Database user")
    password: str = Field(..., description="Database password")
    schema_name: str = Field(default="public", alias="schema", description="Schema name")
    sslmode: str = Field(default="prefer", description="SSL mode")


class GraphLLMConfig(BaseModel):
    """Graph LLM configuration (collection-level)."""

    enabled: bool = Field(default=False, description="Enable LLM enrichment")
    provider: str = Field(default_factory=_default_llm_provider, description="LLM provider")
    model: str = Field(default_factory=_default_graph_llm_model, description="LLM model name")
    extraction_mode: str = Field(
        default="predefined", description="Extraction mode: predefined or dynamic"
    )
    confidence_threshold: float = Field(
        default=0.7, description="Minimum confidence for extracted entities"
    )
    batch_size: int = Field(default=10, description="Batch size for LLM calls")
    rate_limits: Dict[str, int] = Field(default_factory=dict, description="Rate limit settings")

    @classmethod
    def from_collection(cls, collection_id: UUID) -> "GraphLLMConfig":
        """Create config from collection settings.

        Args:
            collection_id: Collection ID

        Returns:
            GraphLLMConfig instance
        """
        # For now, return defaults. Can be extended to load from collection config.
        return cls()


class DatabaseEmbeddingConfig(BaseModel):
    """Database embedding configuration."""

    enabled: bool = Field(default=True, description="Enable embeddings")
    model_name: str = Field(
        default_factory=_default_embedding_model, description="Embedding model name"
    )
    vector_size: int = Field(default=3072, description="Vector dimensions")
    provider: str = Field(default_factory=_default_llm_provider, description="Embedding provider")
    batch_size: int = Field(default=100, description="Batch size for embeddings")
    parallel_requests: int = Field(default=10, description="Parallel embedding requests")

    @classmethod
    def from_collection(cls, collection_id: UUID) -> "DatabaseEmbeddingConfig":
        """Create config from collection settings.

        Args:
            collection_id: Collection ID

        Returns:
            DatabaseEmbeddingConfig instance
        """
        # For now, return defaults. Can be extended to load from collection config.
        return cls()


class DatabaseIndexConfig(BaseModel):
    """Database index configuration."""

    vector_index_enabled: bool = Field(
        default=False, description="Reserved for future vector indexing"
    )
    fulltext_index_enabled: bool = Field(default=True, description="Enable fulltext index (Neo4j)")
    hybrid_search_enabled: bool = Field(default=True, description="Enable hybrid search")
    index_refresh_strategy: str = Field(default="immediate", description="Index refresh strategy")


class DatabaseGraphConfig(BaseModel):
    """Unified database configuration: connection + schema + graph/LLM/embedding.

    Combines all database-related configuration in one place.
    """

    model_config = ConfigDict(populate_by_name=True)

    # Connection configuration
    connection: Optional[DatabaseConnectionConfig] = Field(
        default=None, description="Database connection configuration"
    )

    # Schema definitions (tables with metadata)
    schema_definitions: Dict[str, DatabaseTable] = Field(
        alias="schema", default_factory=dict, description="Schema definitions keyed by table_key"
    )

    # Graph LLM configuration (collection-level)
    graph_llm: GraphLLMConfig = Field(
        default_factory=GraphLLMConfig, description="Graph LLM configuration"
    )

    # Embedding configuration (collection-level)
    embedding: DatabaseEmbeddingConfig = Field(
        default_factory=DatabaseEmbeddingConfig, description="Embedding configuration"
    )

    # Index configuration
    indexing: DatabaseIndexConfig = Field(
        default_factory=DatabaseIndexConfig, description="Index configuration"
    )

    @classmethod
    def from_collection(
        cls,
        collection_id: UUID,
        connection_config: Optional[Dict] = None,
        schema_definitions: Optional[Dict[str, DatabaseTable]] = None,
    ) -> "DatabaseGraphConfig":
        """Build config from collection and schema definitions.

        Args:
            collection_id: Collection ID
            connection_config: Optional connection configuration dict
            schema_definitions: Optional schema definitions

        Returns:
            DatabaseGraphConfig instance
        """
        connection = None
        if connection_config:
            connection = DatabaseConnectionConfig(**connection_config)

        return cls(
            connection=connection,
            schema_definitions=schema_definitions or {},
            graph_llm=GraphLLMConfig.from_collection(collection_id),
            embedding=DatabaseEmbeddingConfig.from_collection(collection_id),
            indexing=DatabaseIndexConfig(),
        )
