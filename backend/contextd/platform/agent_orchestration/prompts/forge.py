"""Context Forge schema-agent prompt builders."""

from __future__ import annotations

import json
from typing import Any, Mapping

from contextd.platform.agent_orchestration.prompts.common import _adk_escape_instruction_braces

FORGE_AGENT_SYSTEM = _adk_escape_instruction_braces(
    """
You are the Context Forge schema agent. Your job is to review a database schema
snapshot and propose a graph schema that a human can review before sync.

Rules:
- Ground every entity, relationship, and fact in the provided source objects and columns.
- Prefer explicit primary keys and foreign keys. When those are absent, infer only likely
  relationships from column names, table names, and common warehouse modeling patterns.
- Do not invent external tables, users, products, or events that are not in the schema.
- Keep labels short, stable, lowercase snake_case for relationships/predicates.
- Include confidence and a short rationale for AI-inferred relationships.
- Treat PII columns as properties/facts with caution; never expose sample values or secrets.
- Return only valid JSON matching the structured output schema.
"""
)


def build_forge_agent_user_message(
    *,
    provider: str,
    source_name: str,
    mapping_schema: Mapping[str, Any],
    max_objects: int,
    max_columns_per_object: int,
) -> str:
    """Build the compact schema payload sent to the Context Forge agent."""
    compact_objects = []
    entity_by_id = {
        str(entity.get("id")): entity
        for entity in mapping_schema.get("entity_types") or []
        if isinstance(entity, Mapping)
    }
    for entity in list(entity_by_id.values())[:max_objects]:
        compact_objects.append(
            {
                "object": entity.get("source_object"),
                "current_entity": entity.get("label"),
                "rows": entity.get("rows"),
                "columns": (entity.get("properties") or [])[:max_columns_per_object],
                "primary_keys": entity.get("primary_keys") or [],
                "foreign_key_count": entity.get("foreign_keys") or 0,
                "pii": entity.get("pii") or [],
                "badges": entity.get("badges") or [],
            }
        )

    compact_relationships = [
        {
            "source": entity_by_id.get(str(rel.get("source")), {}).get("source_object"),
            "target": entity_by_id.get(str(rel.get("target")), {}).get("source_object"),
            "source_column": rel.get("source_column"),
            "label": rel.get("label"),
            "kind": rel.get("kind"),
            "confidence": rel.get("confidence"),
        }
        for rel in mapping_schema.get("relationships") or []
        if isinstance(rel, Mapping)
    ][:40]

    payload = {
        "provider": provider,
        "source_name": source_name,
        "objects": compact_objects,
        "deterministic_relationships": compact_relationships,
        "existing_warnings": mapping_schema.get("warnings") or [],
    }
    return (
        "Review this source schema and propose graph-schema improvements. "
        "Return only valid JSON that matches the structured response schema.\n\n"
        + json.dumps(payload, sort_keys=True, default=str)
    )
