"""Schema converter: TableMetadata → EntityMetadata.

Converts database table metadata to entity metadata format for use with
PolymorphicEntity classes and the sync pipeline.
"""

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional, Type

from contextd.platform.configs.database.metadata import ColumnMetadata, TableMetadata
from contextd.platform.entities._metadata import (
    EntityMetadata,
    EntityRelationConfig,
    FieldMetadata,
    GraphEdgeConfig,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from contextd.platform.configs.database.schema import DatabaseTable

# Reuse PostgreSQL type mapping from postgresql.py
PG_TYPE_MAP = {
    "integer": int,
    "bigint": int,
    "smallint": int,
    "decimal": float,
    "numeric": float,
    "real": float,
    "double precision": float,
    "character varying": str,
    "varchar": str,
    "character": str,
    "char": str,
    "text": str,
    "boolean": bool,
    "timestamp": Any,  # datetime, but using Any for compatibility
    "timestamp with time zone": Any,
    "timestamp without time zone": Any,
    "date": Any,
    "time": Any,
    "json": Any,  # JSON can be object {} or array [] or primitive
    "jsonb": Any,
    "uuid": str,
    "array": list,
}


def get_python_type(column_type: str) -> Type:
    """Convert PostgreSQL column type to Python type.

    Args:
        column_type: PostgreSQL column type (e.g., 'VARCHAR', 'INTEGER')

    Returns:
        Python type class
    """
    pg_type_lower = column_type.lower().strip()
    return PG_TYPE_MAP.get(pg_type_lower, Any)


def convert_column_metadata_to_field_metadata(
    col_meta: ColumnMetadata,
) -> FieldMetadata:
    """Convert ColumnMetadata to FieldMetadata.

    Args:
        col_meta: ColumnMetadata instance

    Returns:
        FieldMetadata instance with same configuration
    """
    return FieldMetadata(
        search=col_meta.search,
        graph=col_meta.graph,
        llm=col_meta.llm,
        is_entity_id=col_meta.is_entity_id,
        is_name=col_meta.is_name,
        is_created_at=col_meta.is_created_at,
        is_updated_at=col_meta.is_updated_at,
        unhashable=col_meta.unhashable,
        display_name=col_meta.display_name,
    )


def convert_foreign_keys_to_graph_edges(
    table: "DatabaseTable",
    all_tables: Dict[str, "DatabaseTable"],
    custom_edge_labels: Optional[
        Dict[str, str]
    ] = None,
) -> Dict[str, GraphEdgeConfig]:
    """Auto-generate graph edges from foreign keys.

    Priority for edge type naming:
    1. custom_edge_labels (explicit user overrides)
    2. LLM-inferred llm_edge_labels from TableMetadata
    3. Default RELATES_TO_{TABLE} fallback

    Args:
        table: DatabaseTable with foreign keys
        all_tables: All table definitions (for FK lookup)
        custom_edge_labels: Optional column->edge type map

    Returns:
        Dictionary mapping column name to GraphEdgeConfig
    """
    custom = custom_edge_labels or {}
    # LLM-inferred edge labels from table metadata
    llm_labels = {}
    if table.table_metadata:
        llm_labels = getattr(
            table.table_metadata, "llm_edge_labels", {}
        ) or {}
    edges = {}
    for fk in table.foreign_keys:
        ref_table_key = f"{fk.ref_schema}.{fk.ref_table}"
        ref_table = all_tables.get(ref_table_key)

        if not ref_table:
            logger.debug(
                f"FK {fk.column} -> {ref_table_key}: "
                f"ref table not found in all_tables, skipping"
            )
            continue

        target_node_type = "EntityNode"
        if ref_table.table_metadata:
            target_node_type = (
                ref_table.table_metadata.default_graph_node_type
                or target_node_type
            )

        # Priority: custom > LLM-inferred > default
        if fk.column in custom:
            edge_type = custom[fk.column]
        elif fk.column in llm_labels:
            edge_type = llm_labels[fk.column]
        else:
            edge_type = (
                f"RELATES_TO_"
                f"{ref_table.table_name.upper()}"
            )

        edges[fk.column] = GraphEdgeConfig(
            edge_type=edge_type,
            to_node_type=target_node_type,
            is_list=False,
        )
        logger.debug(
            f"FK edge: {fk.column} -> "
            f"{target_node_type} ({edge_type})"
        )

    return edges


def convert_table_metadata_to_entity_metadata(
    table_metadata: TableMetadata,
    column_mapping: Dict[str, str],
    foreign_key_edges: Optional[Dict[str, GraphEdgeConfig]] = None,
) -> EntityMetadata:
    """Convert TableMetadata to EntityMetadata format.

    Args:
        table_metadata: TableMetadata instance
        column_mapping: Dictionary mapping original column names to normalized names
        foreign_key_edges: Optional pre-computed FK edges (for efficiency)

    Returns:
        EntityMetadata instance ready for attachment to entity class
    """
    fields: Dict[str, FieldMetadata] = {}

    # Convert column metadata to field metadata with name mapping
    for original_col, col_meta in table_metadata.columns.items():
        normalized_col = column_mapping.get(original_col, original_col)

        # Check if FK edge should override explicit graph config
        graph_config = col_meta.graph
        if foreign_key_edges and original_col in foreign_key_edges:
            # FK edge takes precedence unless explicit config exists
            if graph_config is None:
                graph_config = foreign_key_edges[original_col]

        # Create field metadata
        field_meta = FieldMetadata(
            search=col_meta.search,
            graph=graph_config,
            llm=col_meta.llm,
            is_entity_id=col_meta.is_entity_id,
            is_name=col_meta.is_name,
            is_created_at=col_meta.is_created_at,
            is_updated_at=col_meta.is_updated_at,
            unhashable=col_meta.unhashable,
            display_name=col_meta.display_name,
        )

        fields[normalized_col] = field_meta

    # Convert table relations to entity relations
    entity_relations = []
    for table_rel in table_metadata.table_relations:
        entity_rel = EntityRelationConfig(
            edge_type=table_rel.edge_type,
            to_entity_type=table_rel.to_table,
            to_id_field=table_rel.to_id_column,
        )
        entity_relations.append(entity_rel)

    return EntityMetadata(
        fields=fields,
        default_graph_node_type=table_metadata.default_graph_node_type,
        create_entity_node=table_metadata.create_entity_node,
        entity_relations=entity_relations,
        enable_llm_enrichment=table_metadata.enable_llm_enrichment,
        index=table_metadata.index,
    )
