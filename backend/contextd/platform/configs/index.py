"""Index configuration for entity-level indexing.

This module provides configuration for entity-level indexing which enables:
- Fulltext indexes in Neo4j for exact/fuzzy text matching
"""

import os
from typing import List

from pydantic import BaseModel, ConfigDict, Field


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean env var with a default."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _settings_value(name: str, default):
    """Read Settings lazily to avoid importing app config at module load time."""
    try:
        from contextd.core.config import settings

        return getattr(settings, name, default)
    except Exception:
        return default


class IndexConfig(BaseModel):
    """Configuration for entity-level indexing.

    Controls how entities are indexed for search capabilities:
    - Fulltext indexing: Neo4j fulltext indexes for text matching

    Works with existing `embeddable=True` fields defined in entity metadata.

    Example:
        ```python
        index_config = IndexConfig(
            enabled=True,
            fulltext_enabled=True,
        )
        ```
    """

    # Master switch for entity indexing
    enabled: bool = Field(
        default_factory=lambda: _env_bool(
            "INDEX_ENABLED",
            bool(_settings_value("USE_ENTITY_INDEXING", True)),
        ),
        description="Enable entity-level indexing",
    )

    # Fulltext search configuration (Neo4j)
    fulltext_enabled: bool = Field(
        default_factory=lambda: _env_bool("INDEX_FULLTEXT_ENABLED", True),
        description="Enable Neo4j fulltext indexing for text search",
    )
    fulltext_analyzer: str = Field(
        default="standard",
        description="Lucene analyzer for fulltext indexing (standard, simple, whitespace)",
    )

    # Search behavior
    default_search_limit: int = Field(default=20, description="Default number of results to return")
    graph_expansion_depth: int = Field(
        default=2, description="Default depth for graph traversal expansion"
    )

    # Fields to exclude from indexing (even if marked embeddable)
    excluded_fields: List[str] = Field(
        default_factory=list, description="Fields to exclude from indexing even if embeddable"
    )

    model_config = ConfigDict(
        validate_assignment=True,
    )


def get_index_config() -> IndexConfig:
    """Get index configuration from environment.

    Returns:
        IndexConfig instance with values from environment variables
    """
    return IndexConfig()


class FulltextIndexConfig(BaseModel):
    """Configuration for a specific Neo4j fulltext index.

    Used internally to track which indexes have been created
    and their configurations.
    """

    index_name: str = Field(..., description="Name of the fulltext index")
    node_type: str = Field(..., description="Node type/label this index covers")
    fields: List[str] = Field(..., description="Fields included in the index")
    analyzer: str = Field(default="standard", description="Lucene analyzer")

    @property
    def cypher_create_statement(self) -> str:
        """Generate Cypher statement to create this index."""
        fields_list = ", ".join([f"n.{field}" for field in self.fields])
        return f"""
        CREATE FULLTEXT INDEX {self.index_name} IF NOT EXISTS
        FOR (n:{self.node_type})
        ON EACH [{fields_list}]
        OPTIONS {{ indexConfig: {{ `fulltext.analyzer`: '{self.analyzer}' }} }}
        """
