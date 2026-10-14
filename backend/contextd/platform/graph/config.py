"""Graph configuration."""

import os
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


def _parse_csv_list(value: str) -> List[str]:
    """Parse comma-separated environment variables into a list."""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


class GraphConfig(BaseModel):
    """Configuration for Neo4j graph database.

    Loads from environment variables with sensible defaults.
    """

    # Neo4j connection
    uri: str = Field(
        default_factory=lambda: os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        description="Neo4j connection URI",
    )
    user: str = Field(
        default_factory=lambda: os.getenv("NEO4J_USER", "neo4j"),
        description="Neo4j username",
    )
    password: str = Field(
        default_factory=lambda: os.getenv("NEO4J_PASSWORD", "contextd-dev-password"),
        description="Neo4j password",
    )
    database: str = Field(
        default_factory=lambda: os.getenv("NEO4J_DATABASE", "neo4j"),
        description="Neo4j database name",
    )

    # Graph construction settings
    enabled: bool = Field(
        default_factory=lambda: os.getenv("GRAPH_ENABLED", "true").lower() == "true",
        description="Whether graph construction is enabled",
    )
    batch_size: int = Field(
        default_factory=lambda: int(os.getenv("GRAPH_BATCH_SIZE", "100")),
        description="Batch size for graph operations",
    )

    # Graph scope
    organization_scoped: bool = Field(
        default=True, description="Whether graphs are scoped by organization"
    )

    # Embedding settings (for future use)
    generate_embeddings: bool = Field(
        default=False, description="Whether to generate fact embeddings (future feature)"
    )

    # Fulltext index settings
    fulltext_enabled: bool = Field(
        default_factory=lambda: os.getenv("GRAPH_FULLTEXT_ENABLED", "true").lower() == "true",
        description="Whether fulltext indexing is enabled",
    )
    fulltext_analyzer: str = Field(
        default_factory=lambda: os.getenv("GRAPH_FULLTEXT_ANALYZER", "standard"),
        description="Lucene analyzer for fulltext indexes (standard, simple, whitespace)",
    )
    fulltext_auto_create: bool = Field(
        default=True, description="Automatically create fulltext indexes for indexed entities"
    )

    # Graph traversal strategy
    traversal_strategy: str = Field(
        default_factory=lambda: os.getenv("GRAPH_TRAVERSAL_STRATEGY", "ppr"),
        description=(
            "Graph traversal strategy name (apoc, pcst, ppr). Default ppr for better relevance."
        ),
    )

    # Subgraph-to-text serialization for LLM context
    subgraph_text_mode: str = Field(
        default_factory=lambda: os.getenv("GRAPH_SUBGRAPH_TEXT_MODE", "eulerian_path"),
        description=(
            "How to convert subgraph to text: rule_based_flattening (sections by type) "
            "or eulerian_path (NodeA -> Edge -> NodeB -> ...)"
        ),
    )

    # GDS configuration for PCST
    gds_enabled: bool = Field(
        default_factory=lambda: os.getenv("GRAPH_GDS_ENABLED", "true").lower() == "true",
        description="Whether Neo4j GDS is enabled for graph traversal",
    )
    gds_graph_name: str = Field(
        default_factory=lambda: os.getenv("GRAPH_GDS_GRAPH_NAME", "contextd_graph"),
        description="Base name for GDS in-memory graphs",
    )
    pcst_node_labels: List[str] = Field(
        default_factory=lambda: _parse_csv_list(os.getenv("GRAPH_PCST_NODE_LABELS", "GraphNode")),
        description="Fixed node labels to consider for PCST",
    )
    pcst_rel_types: List[str] = Field(
        default_factory=lambda: _parse_csv_list(os.getenv("GRAPH_PCST_REL_TYPES", "RELATES_TO")),
        description="Fixed relationship types to consider for PCST",
    )
    pcst_prize_property: str = Field(
        default_factory=lambda: os.getenv("GRAPH_PCST_PRIZE_PROPERTY", "pcst_prize"),
        description="Prize property name used in PCST projection",
    )
    pcst_edge_weight_property: Optional[str] = Field(
        default_factory=lambda: os.getenv("GRAPH_PCST_EDGE_WEIGHT_PROPERTY", "") or None,
        description="Relationship property name to use as PCST cost (null for constant)",
    )
    pcst_prize_scale: float = Field(
        default_factory=lambda: float(os.getenv("GRAPH_PCST_PRIZE_SCALE", "1")),
        description="Multiplier applied to PCST prize values",
    )

    # GDS configuration for PPR (Personalized PageRank) traversal
    ppr_node_labels: List[str] = Field(
        default_factory=lambda: _parse_csv_list(os.getenv("GRAPH_PPR_NODE_LABELS", "GraphNode")),
        description="Node labels for PPR graph projection",
    )
    ppr_rel_types: List[str] = Field(
        default_factory=lambda: _parse_csv_list(os.getenv("GRAPH_PPR_REL_TYPES", "RELATES_TO")),
        description=(
            "Relationship types for PPR graph projection. Empty list = all types. "
            "Set GRAPH_PPR_REL_TYPES= (empty) for all edges; default RELATES_TO only."
        ),
    )
    ppr_damping_factor: float = Field(
        default_factory=lambda: float(os.getenv("GRAPH_PPR_DAMPING_FACTOR", "0.85")),
        description="PageRank damping factor (teleport probability)",
    )
    ppr_max_iterations: int = Field(
        default_factory=lambda: int(os.getenv("GRAPH_PPR_MAX_ITERATIONS", "20")),
        description="Maximum PageRank iterations",
    )
    ppr_use_elbow: bool = Field(
        default_factory=lambda: os.getenv("GRAPH_PPR_USE_ELBOW", "true").lower() == "true",
        description="Use elbow detection to select PPR nodes; else use top_k or score_threshold",
    )
    ppr_top_k: int = Field(
        default_factory=lambda: int(os.getenv("GRAPH_PPR_TOP_K", "100")),
        description=(
            "Max number of PPR nodes: caps both elbow selection and fallback when elbow is disabled"
        ),
    )
    ppr_score_threshold: Optional[float] = Field(
        default_factory=lambda: (
            float(x) if (x := os.getenv("GRAPH_PPR_SCORE_THRESHOLD", "").strip()) else None
        ),
        description="Optional minimum score threshold for PPR nodes (overrides top_k when set)",
    )

    model_config = ConfigDict(
        validate_assignment=True,
    )

    # Convenience properties for Neo4j connection
    @property
    def neo4j_uri(self) -> str:
        """Get Neo4j URI (alias for uri)."""
        return self.uri

    @property
    def neo4j_user(self) -> str:
        """Get Neo4j user (alias for user)."""
        return self.user

    @property
    def neo4j_password(self) -> str:
        """Get Neo4j password (alias for password)."""
        return self.password

    @property
    def neo4j_database(self) -> str:
        """Get Neo4j database (alias for database)."""
        return self.database


def get_graph_config() -> GraphConfig:
    """Get graph configuration from environment.

    Returns:
        GraphConfig instance
    """
    return GraphConfig()
