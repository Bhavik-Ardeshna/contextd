"""Database metadata configuration classes.

Mirrors EntityMetadata structure but for database tables and columns.
"""

from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field

from contextd.platform.entities._metadata import (
    EntityIndexConfig,
    GraphEdgeConfig,
    GraphMetadataConfig,
    GraphNodeConfig,
    LLMExtractionConfig,
    SearchConfig,
)


class ColumnMetadata(BaseModel):
    """Column-level metadata for graph/LLM/embedding.

    Similar to FieldMetadata but for database columns.
    """

    # Search/embedding configuration
    search: SearchConfig = Field(
        default_factory=SearchConfig, description="Search/embedding configuration"
    )

    # Graph configuration
    graph: Optional[Union[GraphEdgeConfig, GraphNodeConfig, GraphMetadataConfig]] = Field(
        default=None, description="Graph construction configuration"
    )

    # LLM extraction configuration
    llm: Optional[LLMExtractionConfig] = Field(
        default=None, description="LLM extraction configuration"
    )

    # Column flags (similar to FieldMetadata flags)
    is_entity_id: bool = Field(
        default=False, description="Whether this column is the entity ID"
    )
    is_name: bool = Field(default=False, description="Whether this column is the entity name")
    is_created_at: bool = Field(
        default=False, description="Whether this is the creation timestamp"
    )
    is_updated_at: bool = Field(
        default=False, description="Whether this is the update timestamp"
    )
    unhashable: bool = Field(
        default=False,
        description="Exclude from content hash computation",
    )
    display_name: Optional[str] = Field(
        default=None,
        description="Human-readable display name inferred by LLM",
    )


class TableRelationConfig(BaseModel):
    """Table-level relationship configuration.

    Similar to EntityRelationConfig but for database tables.
    """

    edge_type: str = Field(..., description="Type of edge relationship")
    to_table: str = Field(..., description="Target table name")
    to_id_column: str = Field(..., description="Target table's ID column")
    from_column: str = Field(..., description="Source column containing foreign key")
    direction: str = Field(default="outgoing", description="Edge direction")


class TableMetadata(BaseModel):
    """Table-level metadata for graph/LLM/embedding.

    Similar to EntityMetadata but for database tables.
    """

    # Per-column configurations
    columns: Dict[str, ColumnMetadata] = Field(
        default_factory=dict, description="Column-level metadata configurations"
    )

    # Table-level graph settings
    default_graph_node_type: Optional[str] = Field(
        default=None, description="Default node type when table itself is a graph node"
    )
    create_entity_node: bool = Field(
        default=True, description="Whether to create a graph node for the table itself"
    )

    # Table-level relationships (not derived from columns)
    table_relations: List[TableRelationConfig] = Field(
        default_factory=list, description="Table-level relationship configurations"
    )

    # Global LLM settings for the table
    enable_llm_enrichment: bool = Field(
        default=False, description="Enable LLM enrichment for this table type"
    )

    # LLM-inferred FK edge labels: {fk_column: "EDGE_TYPE"}
    llm_edge_labels: Dict[str, str] = Field(
        default_factory=dict,
        description="LLM-inferred semantic edge types for FKs",
    )

    # Index configuration
    index: EntityIndexConfig = Field(
        default_factory=EntityIndexConfig,
        description="Index config (vector + fulltext)",
    )

    def get_column_metadata(self, column_name: str) -> Optional[ColumnMetadata]:
        """Get metadata for a specific column.

        Args:
            column_name: Name of the column

        Returns:
            ColumnMetadata if configured, None otherwise
        """
        return self.columns.get(column_name)

    def get_embeddable_columns(self) -> List[str]:
        """Get list of all embeddable column names.

        Returns:
            List of column names with embeddable=True
        """
        return [
            name
            for name, meta in self.columns.items()
            if meta.search.embeddable
        ]

    def get_graph_columns(self) -> Dict[str, ColumnMetadata]:
        """Get all columns with graph configuration.

        Returns:
            Dict of column name to ColumnMetadata for columns with graph config
        """
        return {
            name: meta
            for name, meta in self.columns.items()
            if meta.graph is not None
        }

    def get_llm_columns(self) -> Dict[str, ColumnMetadata]:
        """Get all columns with LLM extraction enabled.

        Returns:
            Dict of column name to ColumnMetadata for columns with LLM config
        """
        return {
            name: meta
            for name, meta in self.columns.items()
            if meta.llm is not None and meta.llm.enabled
        }
