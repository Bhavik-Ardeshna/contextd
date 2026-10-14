"""Unified entity metadata configuration.

This module provides a centralized configuration system for entity definitions,
replacing the scattered `json_schema_extra` configs with structured classes.

Key Components:
- GraphEdgeConfig: Configuration for creating graph edges from fields
- GraphNodeConfig: Configuration for creating graph nodes from fields
- LLMExtractionConfig: Configuration for LLM entity extraction
- IndexConfig: Configuration for entity-level indexing (vector + fulltext)
- FieldMetadata: Unified per-field configuration
- EntityMetadata: Entity-level configuration container
"""

from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    pass


class EdgeDirection(str, Enum):
    """Direction of graph edges."""

    OUTGOING = "outgoing"
    INCOMING = "incoming"
    BIDIRECTIONAL = "bidirectional"


class GraphEdgeConfig(BaseModel):
    """Configuration for creating graph edges from a field.

    Used when a field represents a relationship to another entity,
    such as assignees, owners, or dependencies.

    Example:
        GraphEdgeConfig(
            edge_type="ASSIGNED_TO",
            to_node_type="PersonNode",
            create_reverse_edge=True,
            reverse_edge_type="ASSIGNED",
            is_list=True
        )
    """

    edge_type: str = Field(..., description="Type of edge relationship (e.g., 'ASSIGNED_TO')")
    to_node_type: str = Field(..., description="Target node type (e.g., 'PersonNode')")
    direction: EdgeDirection = Field(EdgeDirection.OUTGOING, description="Direction of the edge")
    create_reverse_edge: bool = Field(False, description="Whether to create a reverse edge")
    reverse_edge_type: Optional[str] = Field(
        None, description="Type of the reverse edge (e.g., 'ASSIGNED')"
    )
    is_list: bool = Field(False, description="Whether the field contains a list of relationships")

    # Node creation settings for the target
    create_target_node: bool = Field(
        True, description="Whether to create target node if it doesn't exist"
    )
    target_node_id_field: str = Field(
        "id", description="Field in the data to use as target node ID"
    )
    target_node_name_field: str = Field(
        "name", description="Field in the data to use as target node name"
    )

    model_config = ConfigDict(
        use_enum_values=True,
    )


class GraphNodeConfig(BaseModel):
    """Configuration for creating graph nodes from a field.

    Used when a field's value should become a separate node in the graph.

    Example:
        GraphNodeConfig(
            node_type="PersonNode",
            deduplicate_by=["id", "email"],
            create_if_missing=True
        )
    """

    node_type: str = Field(..., description="Type of node to create")
    deduplicate_by: List[str] = Field(
        default_factory=lambda: ["id", "name"],
        description="Fields to use for deduplication",
    )
    create_if_missing: bool = Field(True, description="Create node if it doesn't exist")
    node_id_source: str = Field("id", description="Field to use as node ID")


class MetadataCategory(str, Enum):
    """Categories for metadata events."""

    DESCRIPTION = "description"
    PROPERTIES = "properties"
    TAGS = "tags"
    STATUS = "status"
    CUSTOM_FIELDS = "custom_fields"
    OTHER = "other"


class GraphMetadataConfig(BaseModel):
    """Configuration for metadata-type graph events.

    Used for fields that should be tracked as metadata changes
    rather than nodes or edges.
    """

    category: MetadataCategory = Field(
        MetadataCategory.PROPERTIES, description="Category of metadata"
    )
    indexed: bool = Field(True, description="Whether this metadata should be indexed")

    model_config = ConfigDict(
        use_enum_values=True,
    )


class LLMExtractionConfig(BaseModel):
    """Configuration for LLM entity extraction from a field.

    Enables automatic extraction of entities and relationships
    from unstructured text content using LLM.

    Supports two modes:
    1. Predefined extraction (extract_people, extract_companies, etc.)
    2. Dynamic extraction (LLM decides node types and edge types)

    Example (Predefined mode):
        LLMExtractionConfig(
            enabled=True,
            extract_people=True,
            extract_companies=True,
            extract_topics=True
        )

    Example (Dynamic mode for Email):
        LLMExtractionConfig(
            enabled=True,
            dynamic_extraction=True,
            base_node_type="EmailExtract",
            allow_custom_edges=True,
            content_template="Subject: {subject}\\nFrom: {sender}\\nTo: {to}\\nBody: {snippet}",
            extraction_hint="Extract action items, projects, deadlines, or other important information from this email."
        )
    """

    enabled: bool = Field(False, description="Whether LLM extraction is enabled")

    # === Predefined Extraction Mode ===
    extract_people: bool = Field(False, description="Extract person entities")
    extract_companies: bool = Field(False, description="Extract company/organization entities")
    extract_topics: bool = Field(False, description="Extract topic/concept entities")
    extract_dates: bool = Field(False, description="Extract date/event entities")
    extract_locations: bool = Field(False, description="Extract location entities")
    extract_products: bool = Field(False, description="Extract product entities")

    # Custom extraction types for predefined mode
    custom_entity_types: List[str] = Field(
        default_factory=list,
        description="Additional custom entity types to extract",
    )

    # === Dynamic Extraction Mode ===
    dynamic_extraction: bool = Field(
        False, description="Enable dynamic extraction where LLM decides node types and edge types"
    )
    base_node_type: Optional[str] = Field(
        None,
        description="Base node type for dynamic extraction (e.g., 'EmailExtract'). LLM will add subtype.",
    )
    allow_custom_edges: bool = Field(
        False,
        description="Allow LLM to define custom edge types (e.g., ASSIGNS_TASK, REQUESTS_ACTION)",
    )
    content_template: Optional[str] = Field(
        None,
        description="Template for combining multiple fields into one content block. Use {field_name} placeholders.",
    )
    content_fields: List[str] = Field(
        default_factory=list, description="List of field names to include in the content template"
    )
    extraction_hint: Optional[str] = Field(
        None, description="Hint for LLM about what types of entities/relationships to look for"
    )

    # === Extraction Settings ===
    prompt_override: Optional[str] = Field(None, description="Custom prompt for extraction")
    confidence_threshold: float = Field(
        0.7, description="Minimum confidence for extracted entities"
    )
    max_entities: int = Field(50, description="Maximum number of entities to extract per field")

    def is_dynamic_mode(self) -> bool:
        """Check if using dynamic extraction mode."""
        return self.dynamic_extraction and self.base_node_type is not None

    def is_predefined_mode(self) -> bool:
        """Check if using predefined extraction mode."""
        return any(
            [
                self.extract_people,
                self.extract_companies,
                self.extract_topics,
                self.extract_dates,
                self.extract_locations,
                self.extract_products,
                len(self.custom_entity_types) > 0,
            ]
        )


class SearchConfig(BaseModel):
    """Configuration for search/embedding behavior of a field."""

    embeddable: bool = Field(False, description="Whether field should be embedded for search")
    boost: float = Field(1.0, description="Relevance boost factor for this field")
    include_in_summary: bool = Field(
        False, description="Include in entity summary for search results"
    )


class FieldMetadata(BaseModel):
    """Unified metadata for a single entity field.

    Consolidates all field-level configurations including:
    - Graph relationship configuration
    - LLM extraction settings
    - Search/embedding behavior

    Example:
        FieldMetadata(
            search=SearchConfig(embeddable=True, boost=1.5),
            graph=GraphEdgeConfig(
                edge_type="ASSIGNED_TO",
                to_node_type="PersonNode",
                is_list=True
            ),
            llm=LLMExtractionConfig(
                enabled=True,
                extract_people=True
            )
        )
    """

    # Search configuration
    search: SearchConfig = Field(
        default_factory=SearchConfig,
        description="Search/embedding configuration",
    )

    # Graph configuration (can be edge, node, or metadata)
    graph: Optional[Union[GraphEdgeConfig, GraphNodeConfig, GraphMetadataConfig]] = Field(
        None, description="Graph construction configuration"
    )

    # LLM extraction configuration
    llm: Optional[LLMExtractionConfig] = Field(None, description="LLM extraction configuration")

    # Field flags (for backward compatibility with ContextDField)
    is_entity_id: bool = Field(False, description="Whether this field is the entity ID")
    is_name: bool = Field(False, description="Whether this field is the entity name")
    is_created_at: bool = Field(False, description="Whether this is the creation timestamp")
    is_updated_at: bool = Field(False, description="Whether this is the update timestamp")
    unhashable: bool = Field(False, description="Exclude from content hash computation")
    display_name: Optional[str] = Field(
        None,
        description="Human-readable name from LLM inference",
    )


class EntityRelationConfig(BaseModel):
    """Configuration for entity-level relationships.

    Defines relationships that are inherent to the entity type,
    not derived from specific fields.
    """

    edge_type: str = Field(..., description="Type of edge relationship")
    to_entity_type: str = Field(..., description="Target entity type")
    to_id_field: str = Field(..., description="Field containing the target entity ID")
    direction: EdgeDirection = Field(EdgeDirection.OUTGOING)
    create_reverse_edge: bool = Field(False)
    reverse_edge_type: Optional[str] = Field(None)

    model_config = ConfigDict(
        use_enum_values=True,
    )


class EntityIndexConfig(BaseModel):
    """Entity-level index configuration.

    Controls whether and how this entity type participates in indexing.
    Works with fields marked as embeddable=True via ContextDField.
    """

    enabled: bool = Field(
        default=True, description="Enable entity-level indexing for this entity type"
    )
    fulltext_enabled: bool = Field(default=True, description="Enable Neo4j fulltext indexing")
    excluded_fields: List[str] = Field(
        default_factory=list, description="Fields to exclude from indexing even if embeddable"
    )
    priority_fields: List[str] = Field(
        default_factory=list,
        description="Fields to prioritize in text representation (appear first)",
    )


class EntityMetadata(BaseModel):
    """Unified entity-level configuration.

    Container for all entity configurations including:
    - Per-field metadata configurations
    - Default graph node type
    - Entity-level relationships
    - Index configuration for semantic and fulltext search
    - Global settings

    Example:
        EntityMetadata(
            default_graph_node_type="TaskNode",
            index=EntityIndexConfig(enabled=True),
            fields={
                "name": FieldMetadata(
                    search=SearchConfig(embeddable=True, boost=2.0),
                    is_name=True
                ),
                "assignees": FieldMetadata(
                    search=SearchConfig(embeddable=True),
                    graph=GraphEdgeConfig(
                        edge_type="ASSIGNED_TO",
                        to_node_type="PersonNode",
                        is_list=True
                    )
                ),
            },
            entity_relations=[
                EntityRelationConfig(
                    edge_type="BELONGS_TO",
                    to_entity_type="ProjectEntity",
                    to_id_field="project_id"
                )
            ]
        )
    """

    # Per-field configurations
    fields: Dict[str, FieldMetadata] = Field(
        default_factory=dict,
        description="Field-level metadata configurations",
    )

    # Entity-level graph settings
    default_graph_node_type: Optional[str] = Field(
        None, description="Default node type when entity itself is a graph node"
    )
    create_entity_node: bool = Field(
        True, description="Whether to create a graph node for the entity itself"
    )

    # Entity-level relationships (not derived from fields)
    entity_relations: List[EntityRelationConfig] = Field(
        default_factory=list,
        description="Entity-level relationship configurations",
    )

    # Global LLM settings for the entity
    enable_llm_enrichment: bool = Field(
        False, description="Enable LLM enrichment for this entity type"
    )

    # Index configuration for entity-level search
    index: EntityIndexConfig = Field(
        default_factory=EntityIndexConfig,
        description="Configuration for entity-level fulltext indexing",
    )

    def get_field_metadata(self, field_name: str) -> Optional[FieldMetadata]:
        """Get metadata for a specific field.

        Args:
            field_name: Name of the field

        Returns:
            FieldMetadata if configured, None otherwise
        """
        return self.fields.get(field_name)

    def get_embeddable_fields(self) -> List[str]:
        """Get list of all embeddable field names.

        Returns:
            List of field names with embeddable=True
        """
        return [name for name, meta in self.fields.items() if meta.search.embeddable]

    def get_graph_fields(self) -> Dict[str, FieldMetadata]:
        """Get all fields with graph configuration.

        Returns:
            Dict of field name to FieldMetadata for fields with graph config
        """
        return {name: meta for name, meta in self.fields.items() if meta.graph is not None}

    def get_llm_fields(self) -> Dict[str, FieldMetadata]:
        """Get all fields with LLM extraction enabled.

        Returns:
            Dict of field name to FieldMetadata for fields with LLM config
        """
        return {
            name: meta
            for name, meta in self.fields.items()
            if meta.llm is not None and meta.llm.enabled
        }

    def get_indexable_fields(self, exclude_fields: Optional[List[str]] = None) -> List[str]:
        """Get list of fields to include in entity-level indexing.

        Returns embeddable fields minus any excluded fields from index config.

        Args:
            exclude_fields: Additional fields to exclude (merged with index config)

        Returns:
            List of field names to index
        """
        if not self.index.enabled:
            return []

        # Get base embeddable fields
        embeddable = self.get_embeddable_fields()

        # Build exclusion set
        excluded = set(self.index.excluded_fields)
        if exclude_fields:
            excluded.update(exclude_fields)

        # Filter out excluded fields
        indexable = [f for f in embeddable if f not in excluded]

        # Reorder by priority fields (priority fields first, then rest)
        if self.index.priority_fields:
            priority_set = set(self.index.priority_fields)
            priority = [f for f in self.index.priority_fields if f in indexable]
            rest = [f for f in indexable if f not in priority_set]
            indexable = priority + rest

        return indexable

    def get_fulltext_fields(self) -> List[str]:
        """Get fields for Neo4j fulltext indexing.

        Returns indexable fields that should be included in fulltext search.

        Returns:
            List of field names for fulltext index
        """
        if not self.index.enabled or not self.index.fulltext_enabled:
            return []

        return self.get_indexable_fields()

    def get_indexable_fields_with_boost(self) -> List[Tuple[str, float]]:
        """Get indexable fields with their boost factors.

        Returns:
            List of (field_name, boost) tuples sorted by boost descending
        """
        fields_with_boost = []

        for field_name in self.get_indexable_fields():
            meta = self.fields.get(field_name)
            boost = meta.search.boost if meta else 1.0
            fields_with_boost.append((field_name, boost))

        # Sort by boost descending
        fields_with_boost.sort(key=lambda x: x[1], reverse=True)

        return fields_with_boost


def build_metadata_from_fields(model_fields: Dict[str, Any]) -> EntityMetadata:
    """Build EntityMetadata from Pydantic model fields with json_schema_extra.

    This provides backward compatibility with the existing ContextDField
    configuration style while migrating to the new unified config.

    Args:
        model_fields: Pydantic model fields dict

    Returns:
        EntityMetadata populated from field configurations
    """
    fields_metadata: Dict[str, FieldMetadata] = {}

    for field_name, field_info in model_fields.items():
        json_extra = getattr(field_info, "json_schema_extra", None) or {}

        if not isinstance(json_extra, dict):
            continue

        # Build search config
        search_config = SearchConfig(
            embeddable=json_extra.get("embeddable", False),
        )

        # Build graph config from legacy format
        graph_config = None
        legacy_graph = json_extra.get("graph_config")
        if legacy_graph:
            config_type = legacy_graph.get("type")
            if config_type == "edge":
                edge_cfg = legacy_graph.get("edge_config", {})
                graph_config = GraphEdgeConfig(
                    edge_type=edge_cfg.get("edge_type", "RELATED_TO"),
                    to_node_type=edge_cfg.get("to_node", "UnknownNode"),
                    direction=edge_cfg.get("direction", "outgoing"),
                    create_reverse_edge=edge_cfg.get("create_reverse_edge", False),
                    reverse_edge_type=edge_cfg.get("reverse_edge_type"),
                    is_list=edge_cfg.get("is_list", False),
                )
            elif config_type == "node":
                node_cfg = legacy_graph.get("node_config", {})
                graph_config = GraphNodeConfig(
                    node_type=node_cfg.get("node_entity_type", "UnknownNode"),
                    deduplicate_by=node_cfg.get("deduplicate_by", ["id", "name"]),
                )
            elif config_type == "metadata":
                meta_cfg = legacy_graph.get("metadata_config", {})
                graph_config = GraphMetadataConfig(
                    category=meta_cfg.get("category", "properties"),
                    indexed=meta_cfg.get("indexed", True),
                )

        # Build LLM config from legacy format
        llm_config = None
        legacy_llm = json_extra.get("llm_extraction_config")
        if legacy_llm:
            llm_config = LLMExtractionConfig(
                enabled=legacy_llm.get("enabled", False),
                extract_people=legacy_llm.get("extract_people", False),
                extract_companies=legacy_llm.get("extract_companies", False),
                extract_topics=legacy_llm.get("extract_topics", False),
            )

        # Build field metadata
        field_meta = FieldMetadata(
            search=search_config,
            graph=graph_config,
            llm=llm_config,
            is_entity_id=json_extra.get("is_entity_id", False),
            is_name=json_extra.get("is_name", False),
            is_created_at=json_extra.get("is_created_at", False),
            is_updated_at=json_extra.get("is_updated_at", False),
            unhashable=json_extra.get("unhashable", False),
        )

        fields_metadata[field_name] = field_meta

    return EntityMetadata(fields=fields_metadata)
