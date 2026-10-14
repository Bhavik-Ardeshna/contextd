"""LLM-based extraction of connector business logic from sample entities.

Given source_type and sample rows per entity type, calls an LLM to decide which
property keys are useful for answering user questions vs noise (sync IDs, hashes, etc.).
Output is used to build ConnectorBusinessLogic and graph schema prompt context.

Also provides per-node-type explanation generation for the node-level schema RAG:
one rich semantic explanation per node type (properties + relationships in natural language).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from contextd.platform.agent_orchestration.business_logic import ConnectorBusinessLogic

logger = logging.getLogger(__name__)

# Per-node-type explanation prompt (relationship types only in natural language, not in payload)
NODE_EXPLANATION_SYSTEM = """You are an expert graph data architect building a semantic dictionary for a Text-to-Cypher AI agent.

Your task is to write a highly concise, actionable explanation (1-3 sentences) for a specific knowledge graph node type. A downstream AI agent will read your explanation during RAG to understand WHEN to query this node and WHAT data it holds.

Based on the provided node type, property keys, and connected node types, write a description that strictly follows these rules:
1. Define the entity: State exactly what real-world object this node represents.
2. List properties: You MUST explicitly name the property keys that are useful for filtering or searching (e.g. "Filter or search by: name, email, created_at"). If properties are listed in the input, include them in your explanation; do not say "no properties" or "discover from graph".
3. List connections: You MUST name the other node types this entity connects to (e.g. "Connects to: MembersTableEntity, ClassesTableEntity"). Use natural language for how they relate (e.g. "belongs to a", "references"); never use raw edge names like "RELATES_TO" or "CONNECTED_TO".
4. No filler: Do not include introductory text like "This node represents..." or "Explanation:". Start the definition immediately.
5. Pure text: Output ONLY the raw explanation string. No JSON, no markdown formatting, no quotes.

Example Input:
Node: GmailMessage
Properties: subject, snippet, date
Connects to: GmailThread, GmailSender

Example Output:
An individual email message in a user's inbox. Filter or search by subject, snippet, or date. Connects to GmailSender (author) and GmailThread (conversation grouping)."""

# Sample size per entity type shown to LLM (matches sync hook MAX_SAMPLES_PER_ENTITY_TYPE)
MAX_SAMPLE_ROWS = 3
MAX_VALUE_LEN = 80


class EntityPropertyShapeEntry(BaseModel):
    """One entity type and its useful property keys (OpenAI schema needs fixed keys, not Dict)."""

    node_type: str = Field(..., description="Entity/node type name")
    property_keys: List[str] = Field(
        default_factory=list,
        description="USEFUL property keys only (no noise) for this entity type",
    )


class TableNodeTypeEntry(BaseModel):
    """Maps a table name to its inferred semantic node type."""

    table_name: str = Field(..., description="Original table name from the database (e.g. 'orders', 'customer_addresses')")
    node_type: str = Field(..., description="Semantic node type name (e.g. 'Order', 'CustomerAddress')")


class ColumnAliasEntry(BaseModel):
    """Human-readable alias for a database column."""

    table_name: str = Field(..., description="Table this column belongs to")
    column_name: str = Field(..., description="Original column name from the database")
    display_name: str = Field(..., description="Human-readable name (e.g. 'cust_nm' -> 'Customer Name')")


class FKEdgeTypeEntry(BaseModel):
    """Semantic edge type for a foreign key relationship."""

    source_table: str = Field(..., description="Table containing the foreign key column")
    fk_column: str = Field(..., description="Foreign key column name")
    ref_table: str = Field(..., description="Referenced table name")
    edge_type: str = Field(..., description="Semantic edge type in UPPER_SNAKE_CASE (e.g. 'PLACED_BY', 'BELONGS_TO', 'HAS_ADDRESS')")


class NameColumnEntry(BaseModel):
    """Maps a table to the column that best represents its entity name."""

    table_name: str = Field(..., description="Table name")
    column_name: str = Field(..., description="Column that best represents the entity's display name")


class BusinessLogicLLMOutput(BaseModel):
    """Structured LLM output for business logic extraction."""

    node_types: List[str] = Field(
        default_factory=list,
        description="Entity/node type names present in the data",
    )
    table_node_types: List[TableNodeTypeEntry] = Field(
        default_factory=list,
        description="Mapping from each table name to its semantic node type (e.g. 'orders' -> 'Order')",
    )
    rel_types: List[str] = Field(
        default_factory=lambda: ["RELATES_TO"],
        description="Relationship types (default RELATES_TO if not specified)",
    )
    fk_edge_types: List[FKEdgeTypeEntry] = Field(
        default_factory=list,
        description="Semantic edge types for foreign key relationships",
    )
    column_aliases: List[ColumnAliasEntry] = Field(
        default_factory=list,
        description="Human-readable display names for abbreviated or unclear column names",
    )
    entity_property_shapes: List[EntityPropertyShapeEntry] = Field(
        default_factory=list,
        description="For each node_type, list of USEFUL property keys only (no noise)",
    )
    name_columns: List[NameColumnEntry] = Field(
        default_factory=list,
        description="For each table, the column that best represents the entity's display name",
    )
    schema_narrative: str = Field(
        default="",
        description="Short text describing how the entity types connect and what each means in this connector",
    )


SYSTEM_PROMPT = """You are an expert at analyzing entity schemas for knowledge-graph question answering.

Given a connector type and sample records for each entity type, your task is to:
1. For each table/entity type, assign a semantic node type name (e.g. table "orders" -> node type "Order").
2. List all distinct entity (node) types present.
3. For foreign key relationships, assign a semantic edge type in UPPER_SNAKE_CASE that describes the relationship direction FROM the FK table TO the referenced table (e.g. orders.customer_id -> customers becomes "PLACED_BY" because an order is PLACED_BY a customer).
4. List relationship types if evident (otherwise use RELATES_TO).
5. For columns with abbreviated or unclear names, provide a human-readable display name (e.g. "cust_nm" -> "Customer Name", "ord_dt" -> "Order Date"). Only include columns that genuinely need renaming - skip columns that already have clear, readable names.
6. For each entity type, list ONLY the property keys that are USEFUL for an LLM answering user questions.
7. Write a short schema_narrative (2-5 sentences) describing how these entity types connect to each other and what each type means in this connector.
8. For each table, identify which column best represents the entity's display name (the human-readable identifier). This could be "name", "title", "full_name", "display_name", "subject", "label", "first_name + last_name", etc. If a table has no clear name column, omit it.

USEFUL properties include:
- Names, titles, subjects, descriptions
- Dates (created, updated, due)
- Status, category, priority, type
- IDs that link to other entities (e.g. person_id, order_id, assignee_id)
- Emails, phones, URLs
- User-facing identifiers and labels

NOISE (exclude these):
- Internal sync IDs, hashes, checksums
- Raw API-only fields (e.g. raw_json, api_etag)
- Duplicate or redundant keys that add no semantic value
- Empty or placeholder keys

Output valid JSON with:
- table_node_types: list of objects with "table_name" and "node_type" (one per table)
- node_types: list of strings (all node type names)
- fk_edge_types: list of objects with "source_table", "fk_column", "ref_table", "edge_type" (one per FK)
- column_aliases: list of objects with "table_name", "column_name", "display_name" (only for unclear columns)
- rel_types: list of strings (all relationship/edge types)
- entity_property_shapes: list of objects with "node_type" and "property_keys"
- name_columns: list of objects with "table_name" and "column_name" (one per table that has a name-like column)
- schema_narrative: string"""


def _truncate_value(v: Any) -> str:
    if v is None:
        return "null"
    s = str(v)
    if len(s) > MAX_VALUE_LEN:
        return s[: MAX_VALUE_LEN - 3] + "..."
    return s


def build_sample_text(
    source_type: str,
    samples_by_entity_type: Dict[str, List[Dict[str, Any]]],
    *,
    foreign_keys_by_table: Optional[Dict[str, List[Dict[str, str]]]] = None,
    column_types_by_table: Optional[Dict[str, Dict[str, str]]] = None,
) -> str:
    """Build user prompt content from samples.

    Args:
        source_type: Connector short_name (e.g. gmail).
        samples_by_entity_type: Map entity_type -> list of row dicts (each row = property keys and values).
        foreign_keys_by_table: Optional map table_key -> list of FK dicts with column, ref_table, ref_column.
        column_types_by_table: Optional map table_key -> {column_name: column_type}.

    Returns:
        Formatted string for the LLM user message.
    """
    lines = [f"Connector (source_type): {source_type}", ""]
    for entity_type, rows in samples_by_entity_type.items():
        lines.append(f"Entity type: {entity_type}")
        # Include column types if available
        if column_types_by_table and entity_type in column_types_by_table:
            col_types = column_types_by_table[entity_type]
            type_strs = [f"{col}: {typ}" for col, typ in col_types.items()]
            lines.append(f"Column types: {', '.join(type_strs)}")
        # Include foreign keys if available
        if foreign_keys_by_table and entity_type in foreign_keys_by_table:
            fks = foreign_keys_by_table[entity_type]
            for fk in fks:
                lines.append(
                    f"  FK: {fk['column']} -> {fk['ref_table']}.{fk['ref_column']}"
                )
        lines.append(f"Sample rows ({min(len(rows), MAX_SAMPLE_ROWS)}):")
        for i, row in enumerate(rows[:MAX_SAMPLE_ROWS]):
            if not isinstance(row, dict):
                continue
            # Show keys and truncated values
            parts = [f"  Row {i+1}: "]
            for k, v in row.items():
                parts.append(f"{k}={_truncate_value(v)}")
            lines.append(", ".join(parts))
        lines.append("")
    lines.append(
        "Provide table_node_types, node_types, fk_edge_types, column_aliases, rel_types, "
        "entity_property_shapes (list of {node_type, property_keys}), name_columns (list of "
        "{table_name, column_name}), and schema_narrative."
    )
    return "\n".join(lines)


class BusinessLogicResult(BaseModel):
    """Result container for LLM business logic extraction."""

    logic: ConnectorBusinessLogic
    table_node_types: Dict[str, str] = Field(
        default_factory=dict,
    )
    column_aliases: Dict[str, Dict[str, str]] = Field(
        default_factory=dict,
    )
    fk_edge_types: Dict[str, str] = Field(
        default_factory=dict,
    )
    name_columns: Dict[str, str] = Field(
        default_factory=dict,
        description="table_name -> column that best represents entity name",
    )


async def extract_business_logic_with_llm(
    source_type: str,
    samples_by_entity_type: Dict[str, List[Dict[str, Any]]],
    *,
    all_node_types: Optional[List[str]] = None,
    foreign_keys_by_table: Optional[Dict[str, List[Dict[str, str]]]] = None,
    column_types_by_table: Optional[Dict[str, Dict[str, str]]] = None,
    logger_instance: Optional[logging.Logger] = None,
) -> Optional["BusinessLogicResult"]:
    """Call LLM to infer node types, rel types, edge types, column aliases, and useful property keys.

    Args:
        source_type: Connector short_name.
        samples_by_entity_type: Node/entity type -> list of sample row dicts (for LLM to infer properties).
        all_node_types: Optional full list of node types (e.g. from graph). When set, every type is
            included in the result even if we have no samples; property shapes may be empty for those.
        foreign_keys_by_table: Optional map table_key -> list of FK dicts with column, ref_table, ref_column.
        column_types_by_table: Optional map table_key -> {column_name: column_type}.
        logger_instance: Optional logger (e.g. from sync_context).

    Returns:
        BusinessLogicResult with ConnectorBusinessLogic + table_node_types, column_aliases, fk_edge_types.
    """
    # Need at least samples or an explicit all_node_types to run
    if not samples_by_entity_type and not all_node_types:
        return None

    log = logger_instance or logger
    try:
        from types import SimpleNamespace

        from contextd.platform.llm.gateway import LLMConfigurationError, get_llm_gateway

        user_content = (
            build_sample_text(
                source_type,
                samples_by_entity_type,
                foreign_keys_by_table=foreign_keys_by_table,
                column_types_by_table=column_types_by_table,
            )
            if samples_by_entity_type
            else f"Connector (source_type): {source_type}\n\nNo sample rows (node types from graph only). Provide table_node_types, node_types, fk_edge_types, column_aliases, rel_types, entity_property_shapes (list of {{node_type, property_keys}}), and schema_narrative."
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        try:
            out = await get_llm_gateway().structured_output(
                messages=messages,
                schema=BusinessLogicLLMOutput,
                role="schema_extraction",
                ctx=SimpleNamespace(logger=log),
            )
        except LLMConfigurationError as e:
            log.warning("[BusinessLogic] %s. Skipping extraction.", e)
            return None
        except Exception as e:
            log.warning("[BusinessLogic] LLM structured_output failed: %s", e)
            return None

        # Canonical list: all_node_types (from graph) if provided, else types we have samples or LLM returned
        input_types = list(samples_by_entity_type.keys())
        base_types = all_node_types if all_node_types is not None else input_types
        node_types_union = list(dict.fromkeys(base_types + (out.node_types or [])))
        if not out.rel_types:
            out.rel_types = ["RELATES_TO"]

        # Include LLM-inferred FK edge types in rel_types
        for fk_entry in out.fk_edge_types or []:
            if fk_entry.edge_type and fk_entry.edge_type not in out.rel_types:
                out.rel_types.append(fk_entry.edge_type)

        # Build shapes: only include node types that have at least one useful property key (omit empty lists).
        shapes_dict: Dict[str, List[str]] = {}
        for entry in out.entity_property_shapes or []:
            if entry.node_type and entry.property_keys:
                shapes_dict[entry.node_type] = list(entry.property_keys)

        # Build table_node_types dict: table_name -> node_type
        table_node_types: Dict[str, str] = {}
        for entry in out.table_node_types or []:
            if entry.table_name and entry.node_type:
                table_node_types[entry.table_name] = entry.node_type

        # Build column_aliases dict: table_name -> {column_name: display_name}
        column_aliases: Dict[str, Dict[str, str]] = {}
        for entry in out.column_aliases or []:
            if entry.table_name and entry.column_name and entry.display_name:
                column_aliases.setdefault(entry.table_name, {})[entry.column_name] = entry.display_name

        # Build fk_edge_types dict: "source_table.fk_column" -> edge_type
        fk_edge_types: Dict[str, str] = {}
        for entry in out.fk_edge_types or []:
            if entry.source_table and entry.fk_column and entry.edge_type:
                fk_edge_types[f"{entry.source_table}.{entry.fk_column}"] = entry.edge_type

        # Build name_columns dict: table_name -> column_name
        name_columns: Dict[str, str] = {}
        for entry in out.name_columns or []:
            if entry.table_name and entry.column_name:
                name_columns[entry.table_name] = entry.column_name

        logic = ConnectorBusinessLogic(
            source_type=source_type,
            node_types=node_types_union,
            rel_types=out.rel_types,
            entity_property_shapes=shapes_dict,
            schema_narrative=out.schema_narrative.strip() if out.schema_narrative else None,
        )

        return BusinessLogicResult(
            logic=logic,
            table_node_types=table_node_types,
            column_aliases=column_aliases,
            fk_edge_types=fk_edge_types,
            name_columns=name_columns,
        )
    except Exception as e:
        log.exception("[BusinessLogic] Extraction failed: %s", e)
        return None


def _format_relationship_summary(rels: List[Dict[str, Any]]) -> str:
    """Format relationship list for LLM input (natural-language style, no raw type names)."""
    if not rels:
        return "No relationships in the graph for this node type."
    lines = []
    for r in rels:
        direction = r.get("direction", "outgoing")
        neighbor = r.get("neighbor_node_type", "Unknown")
        # Describe in natural language; we don't want to emphasize relationship_type in prompt
        if direction == "outgoing":
            lines.append(f"  - Connects to {neighbor}")
        else:
            lines.append(f"  - Connected from {neighbor}")
    return "Relationships:\n" + "\n".join(lines) if lines else "No relationships."


async def generate_node_type_explanation(
    node_type: str,
    properties: List[str],
    relationship_summary: List[Dict[str, Any]],
    *,
    logger_instance: Optional[logging.Logger] = None,
) -> Optional[str]:
    """Generate a single rich semantic explanation for a node type (for schema RAG).

    Args:
        node_type: Node type name (e.g. GmailMessage).
        properties: List of useful property keys for this type.
        relationship_summary: List of {"relationship_type", "direction", "neighbor_node_type"}.
        logger_instance: Optional logger (e.g. from sync_context).

    Returns:
        Explanation string, or None if LLM fails.
    """
    log = logger_instance or logger
    try:
        from types import SimpleNamespace

        from contextd.platform.llm.gateway import LLMConfigurationError, get_llm_gateway

        props_str = ", ".join(properties) if properties else "(none)"
        rel_str = _format_relationship_summary(relationship_summary or [])
        user_content = (
            f"Node type: {node_type}\n"
            f"Properties: {props_str}\n\n"
            f"{rel_str}\n\n"
            "Write a single short explanation (1-3 sentences). You MUST include the property names and the connected node type names in your explanation."
        )
        messages = [
            {"role": "system", "content": NODE_EXPLANATION_SYSTEM},
            {"role": "user", "content": user_content},
        ]
        try:
            response = await get_llm_gateway().complete(
                messages,
                role="schema_extraction",
                ctx=SimpleNamespace(logger=log),
            )
        except LLMConfigurationError as e:
            log.warning("[NodeExplanation] %s. Skipping.", e)
            return None

        text = (response or "").strip()
        return text if text else None
    except Exception as e:
        log.warning("[NodeExplanation] Failed for %s: %s", node_type, e)
        return None
