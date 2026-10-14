"""Graph-backed schema retrieval for agent prompt construction."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


async def expand_query_for_schema(user_message: str, ctx: Any) -> str:
    """Expand user query into keywords and domain concepts for schema RAG retrieval."""
    log = getattr(ctx, "logger", logger)
    if not user_message or not user_message.strip():
        return user_message or ""
    log.info("[SchemaRAG] Query expansion input: %s", user_message.strip())

    try:
        from contextd.platform.llm.gateway import LLMConfigurationError, get_llm_gateway

        system = (
            "Given a user question, output a short comma-separated list of search keywords "
            "and domain concepts that would help find relevant schema types (e.g. entity names, "
            "actions, domain terms). Output ONLY the comma-separated list, no explanation."
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ]
        try:
            response = await get_llm_gateway().complete(
                messages,
                role="schema_query_expansion",
                ctx=ctx,
            )
        except LLMConfigurationError:
            log.info("[SchemaRAG] Query expansion output (no API key): %s", user_message.strip())
            return user_message.strip()

        terms = (response or "").strip()
        if terms:
            expanded = f"{user_message.strip()} {terms}"
            log.info("[SchemaRAG] Query expansion output: %s", expanded)
            return expanded
        log.info("[SchemaRAG] Query expansion output (no terms): %s", user_message.strip())
        return user_message.strip()
    except Exception as exc:
        log.debug("[SchemaRAG] Query expansion failed: %s; using original message", exc)
        log.info("[SchemaRAG] Query expansion output (fallback): %s", user_message.strip())
        return user_message.strip()


async def retrieve_node_types_for_query(
    organization_id: UUID,
    query_text: str,
    ctx: Any,
    *,
    collection_ids: Optional[List[str]] = None,
    source_types: Optional[List[str]] = None,
    top_k: int = 15,
) -> List[Dict[str, Any]]:
    """Retrieve relevant node types from the live Neo4j graph schema.

    The schema is derived directly from graph nodes and relationship summaries so
    it cannot drift from the indexed data.
    """
    if not query_text or not query_text.strip():
        return []

    from contextd.platform.agent_orchestration.tools import (
        get_graph_node_types_and_samples,
        get_graph_relationships_by_node_type,
    )

    scopes: List[tuple[Optional[str], Optional[str]]] = []
    if collection_ids:
        scopes.extend((collection_id, None) for collection_id in collection_ids)
    elif source_types:
        scopes.extend((None, source_type) for source_type in source_types)
    else:
        scopes.append((None, None))

    query_terms = _tokenize(query_text)
    payloads_by_key: Dict[tuple[str, Optional[str], Optional[str]], Dict[str, Any]] = {}

    for collection_id, source_type in scopes:
        node_types, samples_by_node_type = await get_graph_node_types_and_samples(
            organization_id=organization_id,
            source_type=source_type,
            ctx=ctx,
            collection_id=collection_id,
            samples_per_type=3,
            use_all_org_node_types=not (collection_id or source_type),
        )
        if not node_types:
            continue

        relationships_by_type = await get_graph_relationships_by_node_type(
            organization_id=organization_id,
            source_type=source_type,
            ctx=ctx,
            collection_id=collection_id,
            node_types=node_types,
        )

        for node_type in node_types:
            properties = _properties_from_samples(samples_by_node_type.get(node_type, []))
            relationships = relationships_by_type.get(node_type, [])
            explanation = _build_graph_schema_explanation(
                node_type=node_type,
                properties=properties,
                relationships=relationships,
            )
            key = (node_type, collection_id, source_type)
            payloads_by_key[key] = {
                "node_type": node_type,
                "organization_id": str(organization_id),
                "properties": properties,
                "explanation": explanation,
                "collection_id": collection_id,
                "source_type": source_type,
                "_score": _rank_schema_payload(
                    query_terms=query_terms,
                    node_type=node_type,
                    properties=properties,
                    explanation=explanation,
                ),
            }

    ranked = sorted(
        payloads_by_key.values(),
        key=lambda payload: (payload.get("_score", 0), payload.get("node_type", "")),
        reverse=True,
    )
    result: List[Dict[str, Any]] = []
    for payload in ranked[:top_k]:
        cleaned = dict(payload)
        cleaned.pop("_score", None)
        if cleaned.get("collection_id") is None:
            cleaned.pop("collection_id", None)
        if cleaned.get("source_type") is None:
            cleaned.pop("source_type", None)
        result.append(cleaned)
    return result


def _properties_from_samples(samples: List[Dict[str, Any]]) -> List[str]:
    skip_keys = {
        "node_id",
        "node_type",
        "organization_id",
        "sync_id",
        "collection_id",
        "source_type",
    }
    properties: List[str] = []
    seen: set[str] = set()
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        for key in sample:
            if key in skip_keys or key in seen:
                continue
            seen.add(key)
            properties.append(key)
    return properties


def _build_graph_schema_explanation(
    node_type: str,
    properties: List[str],
    relationships: List[Dict[str, Any]],
) -> str:
    parts = [f"Graph node type {node_type}."]
    if properties:
        parts.append(f"Filter or search by {', '.join(properties[:12])}.")
    relationship_summary = _relationship_summary(relationships)
    if relationship_summary:
        parts.append(f"Connects to {relationship_summary}.")
    return " ".join(parts)


def _relationship_summary(relationships: List[Dict[str, Any]]) -> str:
    if not relationships:
        return ""
    labels: List[str] = []
    seen: set[str] = set()
    for relationship in relationships:
        neighbor = str(relationship.get("neighbor_node_type") or "").strip()
        if not neighbor or neighbor in seen:
            continue
        seen.add(neighbor)
        labels.append(neighbor)
    return ", ".join(labels[:12])


def _tokenize(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z0-9_]+", text.lower())
        if len(token) > 2
    }


def _rank_schema_payload(
    query_terms: set[str],
    node_type: str,
    properties: List[str],
    explanation: str,
) -> int:
    if not query_terms:
        return len(properties)
    searchable = _tokenize(" ".join([node_type, *properties, explanation]))
    return len(query_terms & searchable) * 10 + min(len(properties), 10)


def format_pruned_schema(payloads: List[Dict[str, Any]]) -> str:  # noqa: C901
    """Format retrieved node-type payloads into a strict pruned schema string."""
    if not payloads:
        return ""

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for payload in payloads:
        node_type = str(payload.get("node_type", "")).strip()
        if not node_type:
            continue
        normalized = _normalize_type_name(node_type)
        grouped.setdefault(normalized, []).append(
            {
                "node_type": node_type,
                "properties": list(
                    dict.fromkeys(
                        (payload.get("properties") or [])
                        or _extract_props_from_explanation(str(payload.get("explanation", "")))
                    )
                ),
                "explanation": str(payload.get("explanation", "")).strip(),
            }
        )

    lines = []
    for entries in grouped.values():
        preferred = max(
            entries,
            key=lambda item: _score_payload(
                item["node_type"],
                item.get("properties") or [],
                item.get("explanation") or "",
            ),
        )
        merged_props: List[str] = []
        for item in entries:
            merged_props.extend(item.get("properties") or [])
        merged_props = list(dict.fromkeys(merged_props))

        explanation = preferred.get("explanation") or ""
        if not explanation:
            for item in entries:
                if item.get("explanation"):
                    explanation = item["explanation"]
                    break

        props_str = ", ".join(merged_props) if merged_props else "(discover from graph)"
        lines.append(
            f"Node: {preferred['node_type']} | Properties: {props_str} | Expl: {explanation}"
        )
    return "\n".join(lines)


def _extract_props_from_explanation(explanation: str) -> List[str]:
    if not explanation:
        return []
    patterns = [
        r"Filter or search by ([^.]+)",
        r"Properties:\s*([^.]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, explanation, flags=re.IGNORECASE)
        if not match:
            continue
        raw = match.group(1)
        props = [
            token.strip(" .,:;()")
            for token in re.split(r",|\bor\b|\band\b", raw)
            if token.strip(" .,:;()")
        ]
        return list(dict.fromkeys(props))
    return []


def _normalize_type_name(node_type: str) -> str:
    base = (node_type or "").strip()
    if base.endswith("TableEntity"):
        base = base[: -len("TableEntity")]
    base = base.lower()
    if base.endswith("ies") and len(base) > 3:
        base = base[:-3] + "y"
    elif base.endswith("ses") and len(base) > 3:
        base = base[:-2]
    elif base.endswith("s") and not base.endswith("ss") and len(base) > 3:
        base = base[:-1]
    return "".join(char for char in base if char.isalnum())


def _score_payload(node_type: str, props: List[str], explanation: str) -> tuple[int, int, int]:
    return (
        1 if not node_type.endswith("TableEntity") else 0,
        len(props),
        len(explanation or ""),
    )
