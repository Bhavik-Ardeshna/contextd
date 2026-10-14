"""Graph API endpoints for knowledge graph visualization."""

import hashlib
import json
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import String, cast, func, or_, select

from contextd import crud
from contextd.api.context import ApiContext
from contextd.api.deps import get_context
from contextd.core.exceptions import NotFoundException
from contextd.db.session import get_db_context
from contextd.models.context_intelligence import (
    ContextDecision,
    ContextDriftSignal,
    ContextLineageEdge,
    ContextQueryDecisionTrace,
    ContextTemporalFact,
)
from contextd.platform.graph.config import get_graph_config
from contextd.platform.graph.factory import get_graph_constructor
from contextd.platform.sync.pii_masking import MASKED_FIELDS_PROPERTY, MASKING_POLICY_PROPERTY

logger = logging.getLogger(__name__)

router = APIRouter()

DECISION_EDGE_TYPES = {
    "DECIDED_BY",
    "INFORMED_BY",
    "APPLIED_POLICY",
    "AFFECTED",
    "MAKES_DECISION",
    "APPROVES",
    "REJECTS",
    "SUPERSEDES_DECISION",
}

INSPECTOR_FACT_SAMPLE_LIMIT = 16
NATIVE_CURRENT_FACT_LIMIT = 24
NATIVE_SUPERSESSION_LIMIT = 16
NATIVE_LINEAGE_LIMIT = 48
NATIVE_DECISION_LIMIT = 24
NATIVE_QUERY_TRACE_LIMIT = 24
NATIVE_DRIFT_LIMIT = 12
INTERNAL_FACT_KEYS = {
    "id",
    "entity_type",
    "collection_id",
    MASKED_FIELDS_PROPERTY,
    MASKING_POLICY_PROPERTY,
}


def _json_loads(value: Any) -> Dict[str, Any]:
    """Best-effort decode for Neo4j JSON-string properties."""
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        decoded = json.loads(value)
        return decoded if isinstance(decoded, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _json_safe(value: Any) -> Any:
    """Convert date-like values recursively so FastAPI responses stay stable."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _masked_field_metadata(properties: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    metadata = properties.get(MASKED_FIELDS_PROPERTY)
    if not isinstance(metadata, dict):
        return {}
    return {
        str(key): value if isinstance(value, dict) else {"strategy": "redact"}
        for key, value in metadata.items()
    }


def _fact_response(key: str, value: Any, masked_fields: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    fact = {"key": key, "value": value}
    mask = masked_fields.get(key)
    if mask:
        fact["masked"] = True
        fact["mask"] = mask
    return fact


def _display_label(node_id: str, node_type: str, properties: Dict[str, Any]) -> str:
    for key in (
        "name",
        "title",
        "label",
        "display_name",
        "email",
        "organization_name",
        "class_name",
        "studio_name",
    ):
        value = properties.get(key)
        if value not in (None, ""):
            return str(value)

    source_object = properties.get("source_object") or properties.get("table") or properties.get("object")
    if source_object:
        return str(source_object)

    compact_type = node_type.replace("DatabaseTableNode_", "").replace("Entity", "")
    if compact_type and compact_type != "Unknown":
        return compact_type.replace("_", " ").title()
    return node_id


def _node_visual_kind(node_type: str, properties: Dict[str, Any]) -> str:
    """Map raw graph types into the visual language from the UI system."""
    text = f"{node_type} {properties.get('entity_type', '')} {properties.get('source_type', '')}".lower()
    if "databasetablenode" in text:
        if any(token in text for token in ("member", "trainer", "user", "contact")):
            return "person"
        if any(token in text for token in ("studio", "organization", "account", "company", "team")):
            return "organization"
        if any(token in text for token in ("booking", "subscription", "event")):
            return "temporal_event"
        if any(token in text for token in ("class", "product", "project")):
            return "entity"
        return "database_table"
    if any(token in text for token in ("person", "user", "member", "trainer", "contact")):
        return "person"
    if any(token in text for token in ("organization", "account", "company", "studio", "team")):
        return "organization"
    if any(token in text for token in ("llm", "extraction", "inferred")):
        return "llm_extraction"
    if any(token in text for token in ("episode", "event", "temporal")):
        return "temporal_event"
    if "decision" in text:
        return "decision"
    if any(token in text for token in ("fact", "property", "metric")):
        return "forge_fact"
    return "entity"


def _edge_visual_kind(relationship_type: str, properties: Dict[str, Any]) -> str:
    text = f"{relationship_type} {properties.get('relation_type', '')} {properties.get('source', '')}".lower()
    if any(token in text for token in ("decided_by", "informed_by", "applied_policy", "affected", "decision")):
        return "decision"
    if any(token in text for token in ("lineage", "provenance", "derived_from", "committed_as")):
        return "lineage"
    if "inferred" in text or "llm" in text:
        return "inferred"
    if "temporal" in text or "historical" in text:
        return "temporal"
    if "foreign" in text or "fk" in text or "join" in text or "related_to" in text:
        return "confirmed"
    return "confirmed"


def _node_response(
    record: Dict[str, Any],
    *,
    seed_ids: set[str],
    selected_node_id: Optional[str],
    degree: int = 0,
) -> Dict[str, Any]:
    node_id = str(record.get("node_id") or "")
    node_type = str(record.get("node_type") or "Unknown")
    properties = _json_loads(record.get("properties"))
    source_type = properties.get("source_type") or properties.get("source") or "graph"
    collection_id = properties.get("collection_id") or record.get("collection_id")
    label = _display_label(node_id, node_type, properties)
    return {
        "id": node_id,
        "node_id": node_id,
        "label": label,
        "node_type": node_type,
        "visual_kind": _node_visual_kind(node_type, properties),
        "source": source_type,
        "collection_id": collection_id,
        "properties": _json_safe(properties),
        "labels": record.get("labels") or ["GraphNode"],
        "degree": degree,
        "depth": 0 if node_id in seed_ids else 1,
        "is_seed": node_id in seed_ids,
        "is_selected": selected_node_id == node_id,
        "created_at": _json_safe(record.get("created_at")),
        "updated_at": _json_safe(record.get("updated_at")),
    }


def _edge_response(record: Dict[str, Any]) -> Dict[str, Any]:
    relationship_type = str(record.get("relationship_type") or "RELATED_TO")
    properties = _json_loads(record.get("properties"))
    source = str(record.get("source_node_id") or "")
    target = str(record.get("target_node_id") or "")
    edge_id = str(record.get("edge_id") or f"{source}:{relationship_type}:{target}")
    label = (
        properties.get("relation_type")
        or properties.get("label")
        or relationship_type
    )
    return {
        "id": edge_id,
        "edge_id": edge_id,
        "source": source,
        "target": target,
        "source_node_id": source,
        "target_node_id": target,
        "relationship_type": relationship_type,
        "label": str(label).replace("_", " "),
        "visual_kind": _edge_visual_kind(relationship_type, properties),
        "properties": _json_safe(properties),
        "fact": record.get("fact") or "",
        "created_at": _json_safe(record.get("created_at")),
        "updated_at": _json_safe(record.get("updated_at")),
    }


def _relationship_identity(
    source: str,
    target: str,
    relationship_type: str,
    properties: Optional[Dict[str, Any]] = None,
) -> tuple[str, str, str, str]:
    """Return the logical graph relationship identity used by explorer views.

    The sync pipeline can persist reciprocal RELATES_TO rows for the same FK/join
    fabric. The explorer presents a relationship fabric, not raw storage rows, so
    reciprocal duplicates with the same semantic relation collapse into one link.
    Directional decision/provenance edges keep direction in the key.
    """
    rel_type = relationship_type or "RELATED_TO"
    relation_name = str((properties or {}).get("relation_type") or rel_type).lower()
    if rel_type in DECISION_EDGE_TYPES or relation_name in {"derived_from", "committed_as"}:
        return (source, target, rel_type, relation_name)
    left, right = sorted((source, target))
    return (left, right, rel_type, relation_name)


def _edge_logical_key(edge: Dict[str, Any]) -> tuple[str, str, str, str]:
    return _relationship_identity(
        str(edge.get("source_node_id") or edge.get("source") or ""),
        str(edge.get("target_node_id") or edge.get("target") or ""),
        str(edge.get("relationship_type") or "RELATED_TO"),
        edge.get("properties") if isinstance(edge.get("properties"), dict) else {},
    )


def _dedupe_logical_edges(edges: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse reciprocal duplicate rows while preserving deterministic order."""
    seen: set[tuple[str, str, str, str]] = set()
    unique: List[Dict[str, Any]] = []
    for edge in edges:
        key = _edge_logical_key(edge)
        if key in seen:
            continue
        seen.add(key)
        unique.append(edge)
    return unique


def _filter_properties_by_collection(properties: Dict[str, Any], collection_id: Optional[str]) -> bool:
    if not collection_id:
        return True
    return properties.get("collection_id") == collection_id


def _node_collection_predicate(alias: str) -> str:
    """Cypher predicate for strict ContextD database scoping."""
    return f"($collection_id IS NULL OR {alias}.collection_id = $collection_id)"


def _authorize_organization_scope(organization_id: UUID, ctx: ApiContext) -> None:
    """Ensure graph APIs only serve the active workspace organization."""
    if organization_id != ctx.organization.id:
        raise HTTPException(status_code=403, detail="Organization scope does not match the active workspace")


async def _validate_collection_scope(collection_id: Optional[str], ctx: ApiContext) -> None:
    """Validate collection ownership before opening or querying its graph database."""
    if not collection_id:
        return
    try:
        async with get_db_context() as db:
            await crud.collection.get_by_readable_id(db, readable_id=collection_id, ctx=ctx)
    except NotFoundException as exc:
        raise HTTPException(status_code=404, detail=f"Context database '{collection_id}' not found") from exc


def _sort_facets(items: Dict[str, int], limit: int = 16) -> List[Dict[str, Any]]:
    return [
        {"value": key, "count": value}
        for key, value in sorted(items.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]
        if key
    ]


def _temporal_fact_payload(item: ContextTemporalFact) -> Dict[str, Any]:
    return {
        "id": str(item.id),
        "primitive_ref": item.primitive_ref,
        "primitive_type": item.primitive_type,
        "subject_node_id": item.subject_node_id,
        "predicate": item.predicate,
        "status": item.status,
        "valid_at": item.valid_at.isoformat() if item.valid_at else None,
        "invalid_at": item.invalid_at.isoformat() if item.invalid_at else None,
        "created_at": item.transaction_created_at.isoformat() if item.transaction_created_at else None,
        "expired_at": item.transaction_expired_at.isoformat() if item.transaction_expired_at else None,
        "confidence": item.confidence,
        "feedback_weight": item.feedback_weight,
        "provenance": item.provenance or {},
        "object_value": item.object_value or {},
    }


def _lineage_edge_payload(item: ContextLineageEdge) -> Dict[str, Any]:
    return {
        "id": str(item.id),
        "from_ref": item.from_ref,
        "from_type": item.from_type,
        "to_ref": item.to_ref,
        "to_type": item.to_type,
        "relationship_type": item.relationship_type,
        "confidence": item.confidence,
        "status": item.status,
        "valid_at": item.valid_at.isoformat() if item.valid_at else None,
        "invalid_at": item.invalid_at.isoformat() if item.invalid_at else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "evidence": item.evidence or {},
    }


def _stable_edge_ref(
    source_node_id: str,
    target_node_id: str,
    relationship_type: str,
    *,
    collection_id: Optional[str] = None,
) -> str:
    parts = [source_node_id, relationship_type, target_node_id]
    if collection_id:
        parts.insert(0, collection_id)
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
    return f"edge_{digest}"


def _decision_payload(item: ContextDecision) -> Dict[str, Any]:
    return {
        "id": str(item.id),
        "decision_key": item.decision_key,
        "decision_type": item.decision_type,
        "subject": item.subject,
        "outcome": item.outcome,
        "decided_by": item.decided_by_name or item.decided_by_ref,
        "decided_at": item.decided_at.isoformat() if item.decided_at else None,
        "policy_ref": item.policy_ref,
        "exception": item.exception,
        "justification": item.justification,
        "affected_refs": item.affected_refs or [],
        "confidence": item.confidence,
    }


def _query_trace_decision_payload(item: ContextQueryDecisionTrace) -> Dict[str, Any]:
    decision_tree = item.decision_tree or {}
    feedback = decision_tree.get("feedback") or {}
    metrics = dict(decision_tree.get("metrics") or {})
    metrics["decisions"] = max(int(metrics.get("decisions") or 0), 1)
    metrics["query_traces"] = max(int(metrics.get("query_traces") or 0), 1)
    steps = []
    for index, step in enumerate((decision_tree.get("steps") or [])[:10]):
        if not isinstance(step, dict):
            continue
        output = step.get("output") if isinstance(step.get("output"), dict) else {}
        step_key = step.get("key") or f"step_{index + 1}"
        if step_key == "decision_lineage":
            output = {
                **output,
                "decision_count": max(int(output.get("decision_count") or 0), 1),
                "query_traces": max(int(output.get("query_traces") or 0), 1),
                "native_decisions": int(output.get("native_decisions") or 0),
            }
        steps.append(
            {
                "key": step_key,
                "label": step.get("label") or f"Step {index + 1}",
                "detail": step.get("detail") or "ContextD decision step",
                "status": "done" if step_key == "decision_lineage" else step.get("status") or "done",
                "input_count": step.get("input_count"),
                "output_count": step.get("output_count"),
                "output": {
                    key: output.get(key)
                    for key in (
                        "recipe",
                        "path",
                        "seed_count",
                        "node_count",
                        "edge_count",
                        "current_facts",
                        "superseded_facts",
                        "decision_count",
                        "native_decisions",
                        "query_traces",
                        "severity",
                        "active_count",
                        "token_estimate",
                    )
                    if output.get(key) is not None
                },
            }
        )
    return {
        "id": str(item.id),
        "decision_key": item.query_id,
        "decision_type": "query_trace",
        "subject": item.query_text,
        "outcome": item.status,
        "decided_by": "ContextD Query Console",
        "decided_at": item.created_at.isoformat() if item.created_at else None,
        "policy_ref": item.recipe,
        "exception": item.status not in {"completed", "ok", "success"},
        "justification": item.path_used,
        "affected_refs": item.retrieved_node_ids or [],
        "confidence": feedback.get("target_weight"),
        "query_id": item.query_id,
        "query": item.query_text,
        "recipe": item.recipe,
        "path_used": item.path_used,
        "decision_steps": len(decision_tree.get("steps") or []),
        "steps": steps,
        "metrics": metrics,
        "drift_severity": (item.drift_context or {}).get("severity") or metrics.get("drift_severity"),
        "retrieved_node_count": len(item.retrieved_node_ids or []),
        "retrieved_edge_count": len(item.retrieved_edge_ids or []),
        "latency_ms": item.latency_ms,
        "token_estimate": item.token_estimate,
        "trace_kind": "query_decision_trace",
    }


def _drift_payload(item: ContextDriftSignal) -> Dict[str, Any]:
    return {
        "id": str(item.id),
        "drift_type": item.drift_type,
        "severity": item.severity,
        "summary": item.summary,
        "expected": item.expected or {},
        "actual": item.actual or {},
        "details": item.details or {},
        "detected_at": item.detected_at.isoformat() if item.detected_at else None,
    }


def _score_feedback(facts: Sequence[ContextTemporalFact], lineage: Sequence[ContextLineageEdge]) -> Dict[str, Any]:
    confidences = [float(item.confidence or 0) for item in facts if item.confidence is not None]
    feedback = [float(item.feedback_weight or 0) for item in facts if item.feedback_weight is not None]
    lineage_conf = [float(item.confidence or 0) for item in lineage if item.confidence is not None]
    combined = confidences + lineage_conf
    return {
        "confidence": round(sum(combined) / len(combined), 3) if combined else None,
        "feedback_weight": round(sum(feedback) / len(feedback), 3) if feedback else None,
        "facts": len(facts),
        "lineage_edges": len(lineage),
    }


async def _fulltext_seed_ids(
    *,
    organization_id: UUID,
    query: str,
    limit: int,
    collection_id: Optional[str],
) -> List[Dict[str, Any]]:
    from contextd.platform.graph.fulltext_service import FulltextService

    service = await FulltextService.create(
        organization_id=organization_id,
        readable_collection_id=collection_id,
    )
    try:
        results = await service.search_fulltext(
            query=query,
            limit=max(limit * 3, 20),
            organization_id=str(organization_id),
        )
    finally:
        await service.close()

    filtered: List[Dict[str, Any]] = []
    for result in results:
        if _filter_properties_by_collection(result.get("properties") or {}, collection_id):
            filtered.append(
                {
                    "node_id": result.get("node_id"),
                    "label": result.get("name") or result.get("node_id"),
                    "node_type": result.get("node_type"),
                    "score": result.get("score", 0),
                    "source": "fulltext",
                }
            )
        if len(filtered) >= limit:
            break
    return filtered


async def _fallback_seed_ids(
    driver: Any,
    *,
    organization_id: UUID,
    query: Optional[str],
    collection_id: Optional[str],
    node_type: Optional[str],
    limit: int,
) -> List[Dict[str, Any]]:
    params = {
        "org_id": str(organization_id),
        "query": (query or "").strip().lower(),
        "collection_id": collection_id,
        "node_type": node_type,
        "limit": limit,
    }
    where_query = """
        ($query = ''
          OR toLower(coalesce(n.node_id, '')) CONTAINS $query
          OR toLower(coalesce(n.node_type, '')) CONTAINS $query
          OR toLower(toString(coalesce(n.properties, ''))) CONTAINS $query)
    """
    rows = await driver.execute_read(
        f"""
        MATCH (n:GraphNode {{organization_id: $org_id}})
        WHERE {where_query}
          AND ($node_type IS NULL OR n.node_type = $node_type)
          AND {_node_collection_predicate("n")}
        OPTIONAL MATCH (n)-[degree_rel:RELATES_TO]-(degree_other:GraphNode {{organization_id: $org_id}})
        WHERE degree_other IS NULL OR $collection_id IS NULL
          OR (degree_other.collection_id = $collection_id AND degree_rel.collection_id = $collection_id)
        WITH n, count(DISTINCT degree_other.node_id) AS degree
        ORDER BY degree DESC, n.updated_at DESC
        RETURN n.node_id AS node_id,
               n.node_type AS node_type,
               n.collection_id AS collection_id,
               n.properties AS properties,
               degree
        LIMIT $limit
        """,
        params,
    )
    seeds = []
    for row in rows:
        props = _json_loads(row.get("properties"))
        seeds.append(
            {
                "node_id": row.get("node_id"),
                "label": _display_label(str(row.get("node_id")), str(row.get("node_type") or "Unknown"), props),
                "node_type": row.get("node_type"),
                "score": row.get("degree", 0),
                "source": "cypher",
            }
        )
    return seeds


async def _fetch_neighborhood(
    driver: Any,
    *,
    organization_id: UUID,
    seed_ids: Sequence[str],
    focus_node_id: Optional[str],
    depth: int,
    limit: int,
    collection_id: Optional[str],
    node_type: Optional[str],
    edge_type: Optional[str],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
    if not seed_ids:
        return [], [], {}

    hop_depth = max(1, min(depth, 3))
    edge_limit = max(limit * 4, 200)
    params = {
        "org_id": str(organization_id),
        "seed_ids": list(dict.fromkeys(seed_ids)),
        "collection_id": collection_id,
        "node_type": node_type,
        "edge_type": edge_type,
        "limit": limit,
        "edge_limit": edge_limit,
        "focus_node_id": focus_node_id,
        "focus_neighbor_ids": [],
    }
    if focus_node_id:
        focus_rows = await driver.execute_read(
            f"""
            MATCH (focus:GraphNode {{organization_id: $org_id, node_id: $focus_node_id}})
            WHERE {_node_collection_predicate("focus")}
            OPTIONAL MATCH (focus)-[r:RELATES_TO]-(neighbor:GraphNode {{organization_id: $org_id}})
            WHERE {_node_collection_predicate("neighbor")}
              AND ($collection_id IS NULL OR r.collection_id = $collection_id)
              AND ($edge_type IS NULL OR coalesce(properties(r)['relationship_type'], type(r)) = $edge_type)
            RETURN collect(DISTINCT neighbor.node_id) AS neighbor_ids
            """,
            params,
        )
        params["focus_neighbor_ids"] = [
            str(neighbor_id)
            for neighbor_id in (focus_rows[0].get("neighbor_ids") if focus_rows else []) or []
            if neighbor_id
        ]
    node_rows = await driver.execute_read(
        f"""
        MATCH (seed:GraphNode {{organization_id: $org_id}})
        WHERE seed.node_id IN $seed_ids
          AND {_node_collection_predicate("seed")}
        OPTIONAL MATCH path = (seed)-[:RELATES_TO*1..{hop_depth}]-(neighbor:GraphNode {{organization_id: $org_id}})
        WHERE {_node_collection_predicate("neighbor")}
          AND all(path_node IN nodes(path) WHERE $collection_id IS NULL OR path_node.collection_id = $collection_id)
          AND all(path_edge IN relationships(path) WHERE $collection_id IS NULL OR path_edge.collection_id = $collection_id)
        WITH collect(DISTINCT seed) + collect(DISTINCT neighbor) AS node_bag
        UNWIND node_bag AS n
        WITH DISTINCT n
        WHERE n IS NOT NULL
          AND ($node_type IS NULL OR n.node_type = $node_type)
        OPTIONAL MATCH (n)-[degree_rel:RELATES_TO]-(degree_other:GraphNode {{organization_id: $org_id}})
        WHERE degree_other IS NULL OR $collection_id IS NULL
          OR (degree_other.collection_id = $collection_id AND degree_rel.collection_id = $collection_id)
        WITH n, count(DISTINCT degree_other.node_id) AS degree
        ORDER BY CASE
          WHEN $focus_node_id IS NOT NULL AND n.node_id = $focus_node_id THEN 0
          WHEN n.node_id IN $focus_neighbor_ids THEN 1
          WHEN n.node_id IN $seed_ids THEN 2
          ELSE 3
        END,
        degree DESC,
        n.updated_at DESC
        RETURN n.node_id AS node_id,
               n.node_type AS node_type,
               n.collection_id AS collection_id,
               n.properties AS properties,
               NULL AS labels,
               n.created_at AS created_at,
               n.updated_at AS updated_at,
               degree
        LIMIT $limit
        """,
        params,
    )
    node_ids = [row.get("node_id") for row in node_rows if row.get("node_id")]
    if not node_ids:
        return [], [], {}

    edge_rows = await driver.execute_read(
        """
        MATCH (source:GraphNode {organization_id: $org_id})-[r:RELATES_TO]->(target:GraphNode {organization_id: $org_id})
        WHERE source.node_id IN $node_ids
          AND target.node_id IN $node_ids
          AND ($edge_type IS NULL OR coalesce(properties(r)['relationship_type'], type(r)) = $edge_type)
          AND ($collection_id IS NULL OR (
            source.collection_id = $collection_id
            AND target.collection_id = $collection_id
            AND r.collection_id = $collection_id
          ))
        RETURN r.edge_id AS edge_id,
               coalesce(properties(r)['relationship_type'], type(r)) AS relationship_type,
               NULL AS fact,
               r.properties AS properties,
               r.created_at AS created_at,
               r.updated_at AS updated_at,
               source.node_id AS source_node_id,
               target.node_id AS target_node_id
        LIMIT $edge_limit
        """,
        {**params, "node_ids": node_ids},
    )
    degree_map = {str(row.get("node_id")): int(row.get("degree") or 0) for row in node_rows}
    seed_set = {str(seed_id) for seed_id in seed_ids}
    nodes = [
        _node_response(row, seed_ids=seed_set, selected_node_id=None, degree=degree_map.get(str(row.get("node_id")), 0))
        for row in node_rows
    ]
    edges = _dedupe_logical_edges([_edge_response(row) for row in edge_rows])
    return nodes, edges, degree_map


async def _fetch_graph_facets(
    driver: Any,
    *,
    organization_id: UUID,
    collection_id: Optional[str],
) -> Dict[str, Any]:
    rows = await driver.execute_read(
        """
        MATCH (n:GraphNode {organization_id: $org_id})
        WHERE ($collection_id IS NULL OR n.collection_id = $collection_id)
        RETURN n.node_type AS node_type,
               n.collection_id AS collection_id,
               n.properties AS properties
        LIMIT 25000
        """,
        {"org_id": str(organization_id), "collection_id": collection_id},
    )
    node_types: Dict[str, int] = {}
    sources: Dict[str, int] = {}
    collections: Dict[str, int] = {}
    for row in rows:
        node_type = row.get("node_type") or "Unknown"
        node_types[node_type] = node_types.get(node_type, 0) + 1
        props = _json_loads(row.get("properties"))
        source = str(props.get("source_type") or props.get("source") or "graph")
        collection = str(row.get("collection_id") or props.get("collection_id") or "")
        sources[source] = sources.get(source, 0) + 1
        if collection:
            collections[collection] = collections.get(collection, 0) + 1

    rel_rows = await driver.execute_read(
        """
        MATCH (source:GraphNode {organization_id: $org_id})-[r:RELATES_TO]->(target:GraphNode {organization_id: $org_id})
        WHERE ($collection_id IS NULL
          OR (source.collection_id = $collection_id
              AND target.collection_id = $collection_id
              AND r.collection_id = $collection_id))
        WITH coalesce(properties(r)['relationship_type'], type(r)) AS relationship_type,
             CASE
               WHEN source.node_id < target.node_id
               THEN source.node_id + '|' + coalesce(properties(r)['relationship_type'], type(r)) + '|' + target.node_id
               ELSE target.node_id + '|' + coalesce(properties(r)['relationship_type'], type(r)) + '|' + source.node_id
             END AS logical_edge
        RETURN relationship_type, count(DISTINCT logical_edge) AS count
        ORDER BY count DESC
        LIMIT 24
        """,
        {"org_id": str(organization_id), "collection_id": collection_id},
    )
    relationship_types = [
        {"value": row.get("relationship_type") or "RELATED_TO", "count": int(row.get("count") or 0)}
        for row in rel_rows
    ]
    return {
        "node_types": _sort_facets(node_types),
        "relationship_types": relationship_types,
        "sources": _sort_facets(sources),
        "collections": _sort_facets(collections, limit=32),
    }


async def _fetch_graph_stats(
    driver: Any,
    *,
    organization_id: UUID,
    collection_id: Optional[str],
) -> Dict[str, int]:
    params = {"org_id": str(organization_id), "collection_id": collection_id}
    node_rows = await driver.execute_read(
        """
        MATCH (n:GraphNode {organization_id: $org_id})
        WHERE ($collection_id IS NULL OR n.collection_id = $collection_id)
        RETURN count(n) AS count
        """,
        params,
    )
    edge_rows = await driver.execute_read(
        """
        MATCH (source:GraphNode {organization_id: $org_id})-[r:RELATES_TO]->(target:GraphNode {organization_id: $org_id})
        WHERE ($collection_id IS NULL
          OR (source.collection_id = $collection_id
              AND target.collection_id = $collection_id
              AND r.collection_id = $collection_id))
        WITH CASE
               WHEN source.node_id < target.node_id
               THEN source.node_id + '|' + coalesce(properties(r)['relationship_type'], type(r)) + '|' + target.node_id
               ELSE target.node_id + '|' + coalesce(properties(r)['relationship_type'], type(r)) + '|' + source.node_id
             END AS logical_edge
        RETURN count(DISTINCT logical_edge) AS count
        """,
        params,
    )
    return {
        "total_nodes": int(node_rows[0].get("count") or 0) if node_rows else 0,
        "total_edges": int(edge_rows[0].get("count") or 0) if edge_rows else 0,
    }


async def _ensure_collection_graph_materialized(
    driver: Any,
    *,
    organization_id: UUID,
    collection_id: Optional[str],
    target_database: str,
) -> bool:
    """Repair an empty scoped Neo4j database from committed graph events."""
    if not collection_id:
        return False

    node_rows = await driver.execute_read(
        """
        MATCH (n:GraphNode {organization_id: $organization_id, collection_id: $collection_id})
        RETURN count(n) AS nodes
        """,
        {
            "organization_id": str(organization_id),
            "collection_id": collection_id,
        },
        database=target_database,
    )
    if int((node_rows[0] if node_rows else {}).get("nodes") or 0) > 0:
        return False

    from contextd.models.source_connection import SourceConnection
    from contextd.platform.sync.graph.commit_service import GraphCommitService

    async with get_db_context() as db:
        sync_rows = await db.execute(
            select(SourceConnection.sync_id)
            .where(SourceConnection.organization_id == organization_id)
            .where(SourceConnection.readable_collection_id == collection_id)
            .where(SourceConnection.sync_id.is_not(None))
        )
        sync_ids = [row.sync_id for row in sync_rows if row.sync_id]

    if not sync_ids:
        return False

    commit_service = GraphCommitService(driver)
    repaired = False
    for sync_id in sync_ids:
        result = await commit_service.rehydrate_committed_sync_events(
            sync_id=sync_id,
            organization_id=organization_id,
            readable_collection_id=collection_id,
        )
        if result.success and (result.nodes_committed or result.edges_committed):
            repaired = True
        elif not result.success:
            logger.warning(
                "Graph explorer rehydrate failed for collection %s sync %s: %s",
                collection_id,
                sync_id,
                result.error,
            )

    return repaired


async def _fetch_inspector(
    driver: Any,
    *,
    organization_id: UUID,
    node_id: Optional[str],
    collection_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    if not node_id:
        return None
    rows = await driver.execute_read(
        """
        MATCH (n:GraphNode {organization_id: $org_id, node_id: $node_id})
        WHERE ($collection_id IS NULL OR n.collection_id = $collection_id)
        OPTIONAL MATCH (n)-[degree_rel:RELATES_TO]-(degree_other:GraphNode {organization_id: $org_id})
        WITH n,
             count(CASE
               WHEN degree_other IS NOT NULL AND (
                 $collection_id IS NULL
                 OR (degree_other.collection_id = $collection_id AND degree_rel.collection_id = $collection_id)
               )
               THEN degree_rel
             END) AS raw_degree,
             count(DISTINCT CASE
               WHEN degree_other IS NOT NULL AND (
                 $collection_id IS NULL
                 OR (degree_other.collection_id = $collection_id AND degree_rel.collection_id = $collection_id)
               )
               THEN degree_other.node_id
             END) AS degree
        OPTIONAL MATCH (n)-[r:RELATES_TO]-(other:GraphNode {organization_id: $org_id})
        WHERE r IS NULL OR $collection_id IS NULL
          OR (other.collection_id = $collection_id AND r.collection_id = $collection_id)
        WITH n, degree, raw_degree, r, other
        ORDER BY r.updated_at DESC
        RETURN n.node_id AS node_id,
               n.node_type AS node_type,
               n.collection_id AS collection_id,
               n.properties AS properties,
               NULL AS labels,
               n.created_at AS created_at,
               n.updated_at AS updated_at,
               degree,
               raw_degree,
               collect({
                 edge_id: r.edge_id,
                 relationship_type: coalesce(properties(r)['relationship_type'], type(r)),
                 properties: r.properties,
                 fact: NULL,
                 direction: CASE WHEN startNode(r).node_id = n.node_id THEN 'out' ELSE 'in' END,
                 other_node_id: other.node_id,
                 other_node_type: other.node_type,
                 other_properties: other.properties
               }) AS relationships
        """,
        {
            "org_id": str(organization_id),
            "node_id": node_id,
            "collection_id": collection_id,
        },
    )
    if not rows:
        return None
    row = rows[0]
    node = _node_response(row, seed_ids={node_id}, selected_node_id=node_id, degree=int(row.get("degree") or 0))
    relationships = []
    rel_type_counts: Dict[str, int] = {}
    seen_relationships: set[tuple[str, str, str, str]] = set()
    for rel in row.get("relationships") or []:
        if not rel.get("edge_id") or not rel.get("other_node_id"):
            continue
        other_props = _json_loads(rel.get("other_properties"))
        rel_props = _json_loads(rel.get("properties"))
        rel_type = rel.get("relationship_type") or "RELATED_TO"
        logical_key = _relationship_identity(node_id, str(rel.get("other_node_id")), rel_type, rel_props)
        if logical_key in seen_relationships:
            continue
        seen_relationships.add(logical_key)
        rel_type_counts[rel_type] = rel_type_counts.get(rel_type, 0) + 1
        relationships.append(
            {
                "edge_id": rel.get("edge_id"),
                "relationship_type": rel_type,
                "direction": rel.get("direction"),
                "label": str(rel_props.get("relation_type") or rel_type).replace("_", " "),
                "fact": rel.get("fact") or "",
                "other_node_id": rel.get("other_node_id"),
                "other_label": _display_label(
                    str(rel.get("other_node_id")),
                    str(rel.get("other_node_type") or "Unknown"),
                    other_props,
                ),
                "other_node_type": rel.get("other_node_type") or "Unknown",
            }
        )

    properties = node["properties"]
    provenance = {
        "source": properties.get("source_type") or properties.get("source") or "graph",
        "collection_id": properties.get("collection_id"),
        "entity_type": properties.get("entity_type") or node["node_type"],
        "name_field": properties.get("name_field") or properties.get("name"),
        "extraction": properties.get("extraction_method") or "sync graph commit",
    }
    masked_fields = _masked_field_metadata(properties)
    all_facts = [
        _fact_response(key, value, masked_fields)
        for key, value in properties.items()
        if value not in (None, "") and key not in INTERNAL_FACT_KEYS
    ]
    facts = all_facts[:INSPECTOR_FACT_SAMPLE_LIMIT]
    adjacent_edge_ids = [
        str(rel.get("edge_id"))
        for rel in relationships
        if rel.get("edge_id")
    ]
    native_context = await _fetch_native_node_context(
        organization_id=organization_id,
        collection_id=collection_id,
        node_id=node_id,
        edge_ids=adjacent_edge_ids,
    )
    raw_relationship_count = int(row.get("raw_degree") or len(row.get("relationships") or []))
    relationship_count = len(seen_relationships)
    relationship_sample_count = len(relationships)
    return {
        "node": node,
        "facts": facts,
        "facts_total": len(all_facts),
        "facts_sample_count": len(facts),
        "facts_truncated": len(all_facts) > len(facts),
        "top_edges": _sort_facets(rel_type_counts, limit=8),
        "relationships": relationships,
        "relationship_count": relationship_count,
        "relationship_sample_count": relationship_sample_count,
        "neighbor_count": int(row.get("degree") or len({rel["other_node_id"] for rel in relationships})),
        "raw_relationship_count": raw_relationship_count,
        "relationships_truncated": False,
        "provenance": provenance,
        "temporal": {
            "valid_at": properties.get("created_at_field") or properties.get("created_at") or node.get("created_at"),
            "last_seen": properties.get("modified_at") or properties.get("updated_at") or node.get("updated_at"),
            "current": True,
        },
        "cohorts": [
            value
            for value in (
                properties.get("source_type"),
                properties.get("collection_id"),
                node["visual_kind"],
            )
            if value
        ],
        "native": native_context,
        "raw": {
            "node": node,
            "properties": properties,
            "labels": node.get("labels") or [],
        },
    }


async def _fetch_native_node_context(
    *,
    organization_id: UUID,
    collection_id: Optional[str],
    node_id: str,
    edge_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    if not collection_id or not node_id:
        return {
            "temporal_facts": [],
            "supersession_chain": [],
            "lineage_edges": [],
            "decisions": [],
            "drift_signals": [],
            "totals": {
                "temporal_facts": 0,
                "current_temporal_facts": 0,
                "supersession_chain": 0,
                "lineage_edges": 0,
                "decisions": 0,
                "native_decisions": 0,
                "query_traces": 0,
                "drift_signals": 0,
            },
            "samples": {
                "temporal_facts": 0,
                "supersession_chain": 0,
                "lineage_edges": 0,
                "decisions": 0,
                "drift_signals": 0,
            },
            "caps": {
                "temporal_facts": NATIVE_CURRENT_FACT_LIMIT,
                "supersession_chain": NATIVE_SUPERSESSION_LIMIT,
                "lineage_edges": NATIVE_LINEAGE_LIMIT,
                "decisions": NATIVE_DECISION_LIMIT + NATIVE_QUERY_TRACE_LIMIT,
                "drift_signals": NATIVE_DRIFT_LIMIT,
            },
            "feedback": {},
        }

    source_ref = f"source_entity:{node_id}"
    async with get_db_context() as db:
        temporal_match = or_(
            ContextTemporalFact.subject_node_id == node_id,
            ContextTemporalFact.primitive_ref == node_id,
            cast(ContextTemporalFact.object_value, String).contains(node_id),
        )
        temporal_base = (
            ContextTemporalFact.organization_id == organization_id,
            ContextTemporalFact.collection_readable_id == collection_id,
            temporal_match,
        )
        current_result = await db.execute(
            select(ContextTemporalFact)
            .where(*temporal_base)
            .where(ContextTemporalFact.status == "current")
            .order_by(ContextTemporalFact.transaction_created_at.desc())
            .limit(NATIVE_CURRENT_FACT_LIMIT)
        )
        current_facts = list(current_result.scalars().all())

        superseded_result = await db.execute(
            select(ContextTemporalFact)
            .where(*temporal_base)
            .where(ContextTemporalFact.status != "current")
            .order_by(ContextTemporalFact.transaction_created_at.desc())
            .limit(NATIVE_SUPERSESSION_LIMIT)
        )
        superseded_facts = list(superseded_result.scalars().all())

        temporal_total = await db.scalar(select(func.count()).select_from(ContextTemporalFact).where(*temporal_base))
        current_total = await db.scalar(
            select(func.count())
            .select_from(ContextTemporalFact)
            .where(*temporal_base)
            .where(ContextTemporalFact.status == "current")
        )
        superseded_total = await db.scalar(
            select(func.count())
            .select_from(ContextTemporalFact)
            .where(*temporal_base)
            .where(ContextTemporalFact.status != "current")
        )

        lineage_match = or_(
            ContextLineageEdge.from_ref == node_id,
            ContextLineageEdge.to_ref == node_id,
            ContextLineageEdge.from_ref == source_ref,
            ContextLineageEdge.to_ref == source_ref,
        )
        lineage_base = (
            ContextLineageEdge.organization_id == organization_id,
            ContextLineageEdge.collection_readable_id == collection_id,
            ContextLineageEdge.status == "current",
            lineage_match,
        )
        lineage_result = await db.execute(
            select(ContextLineageEdge)
            .where(*lineage_base)
            .order_by(ContextLineageEdge.transaction_created_at.desc())
            .limit(NATIVE_LINEAGE_LIMIT)
        )
        lineage_items = list(lineage_result.scalars().all())
        lineage_total = await db.scalar(select(func.count()).select_from(ContextLineageEdge).where(*lineage_base))

        decision_match = or_(
            ContextDecision.subject.contains(node_id),
            cast(ContextDecision.affected_refs, String).contains(node_id),
        )
        decision_base = (
            ContextDecision.organization_id == organization_id,
            ContextDecision.collection_readable_id == collection_id,
            ContextDecision.status == "current",
            decision_match,
        )
        decisions_result = await db.execute(
            select(ContextDecision)
            .where(*decision_base)
            .order_by(ContextDecision.decided_at.desc())
            .limit(NATIVE_DECISION_LIMIT)
        )
        decision_items = list(decisions_result.scalars().all())
        decision_total = await db.scalar(select(func.count()).select_from(ContextDecision).where(*decision_base))

        trace_match_clauses = [
            cast(ContextQueryDecisionTrace.retrieved_node_ids, String).contains(node_id),
            cast(ContextQueryDecisionTrace.decision_history, String).contains(node_id),
            cast(ContextQueryDecisionTrace.decision_tree, String).contains(node_id),
        ]
        for edge_id in edge_ids or []:
            if edge_id:
                trace_match_clauses.append(
                    cast(ContextQueryDecisionTrace.retrieved_edge_ids, String).contains(edge_id)
                )
        query_trace_match = or_(*trace_match_clauses)
        query_trace_base = (
            ContextQueryDecisionTrace.organization_id == organization_id,
            ContextQueryDecisionTrace.collection_readable_id == collection_id,
            query_trace_match,
        )
        query_trace_result = await db.execute(
            select(ContextQueryDecisionTrace)
            .where(*query_trace_base)
            .order_by(ContextQueryDecisionTrace.created_at.desc())
            .limit(NATIVE_QUERY_TRACE_LIMIT)
        )
        query_trace_items = list(query_trace_result.scalars().all())
        query_trace_total = await db.scalar(
            select(func.count()).select_from(ContextQueryDecisionTrace).where(*query_trace_base)
        )

        drift_base = (
            ContextDriftSignal.organization_id == organization_id,
            ContextDriftSignal.collection_readable_id == collection_id,
            ContextDriftSignal.status == "active",
            ContextDriftSignal.severity != "clean",
        )
        drift_result = await db.execute(
            select(ContextDriftSignal)
            .where(*drift_base)
            .order_by(ContextDriftSignal.detected_at.desc())
            .limit(NATIVE_DRIFT_LIMIT)
        )
        drift_items = list(drift_result.scalars().all())
        drift_total = await db.scalar(select(func.count()).select_from(ContextDriftSignal).where(*drift_base))

    decision_payloads = [
        *[_decision_payload(item) for item in decision_items],
        *[_query_trace_decision_payload(item) for item in query_trace_items],
    ]
    supersession_chain = [_temporal_fact_payload(item) for item in superseded_facts]
    return {
        "temporal_facts": [_temporal_fact_payload(item) for item in current_facts],
        "supersession_chain": supersession_chain,
        "lineage_edges": [_lineage_edge_payload(item) for item in lineage_items],
        "decisions": decision_payloads,
        "drift_signals": [_drift_payload(item) for item in drift_items],
        "totals": {
            "temporal_facts": int(temporal_total or 0),
            "current_temporal_facts": int(current_total or 0),
            "supersession_chain": int(superseded_total or 0),
            "lineage_edges": int(lineage_total or 0),
            "decisions": int((decision_total or 0) + (query_trace_total or 0)),
            "native_decisions": int(decision_total or 0),
            "query_traces": int(query_trace_total or 0),
            "drift_signals": int(drift_total or 0),
        },
        "samples": {
            "temporal_facts": len(current_facts),
            "supersession_chain": len(supersession_chain),
            "lineage_edges": len(lineage_items),
            "decisions": len(decision_payloads),
            "drift_signals": len(drift_items),
        },
        "caps": {
            "temporal_facts": NATIVE_CURRENT_FACT_LIMIT,
            "supersession_chain": NATIVE_SUPERSESSION_LIMIT,
            "lineage_edges": NATIVE_LINEAGE_LIMIT,
            "decisions": NATIVE_DECISION_LIMIT + NATIVE_QUERY_TRACE_LIMIT,
            "drift_signals": NATIVE_DRIFT_LIMIT,
        },
        "feedback": _score_feedback(current_facts, lineage_items),
    }


async def _fetch_edge_inspector(
    driver: Any,
    *,
    organization_id: UUID,
    edge_id: Optional[str],
    collection_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    if not edge_id:
        return None
    rows = await driver.execute_read(
        """
        MATCH (source:GraphNode {organization_id: $org_id})-[r:RELATES_TO]->(target:GraphNode {organization_id: $org_id})
        WHERE r.edge_id = $edge_id
          AND ($collection_id IS NULL OR (
            source.collection_id = $collection_id
            AND target.collection_id = $collection_id
            AND r.collection_id = $collection_id
          ))
        RETURN r.edge_id AS edge_id,
               coalesce(properties(r)['relationship_type'], type(r)) AS relationship_type,
               NULL AS fact,
               r.properties AS properties,
               r.created_at AS created_at,
               r.updated_at AS updated_at,
               source.node_id AS source_node_id,
               source.node_type AS source_node_type,
               source.properties AS source_properties,
               target.node_id AS target_node_id,
               target.node_type AS target_node_type,
               target.properties AS target_properties
        LIMIT 1
        """,
        {"org_id": str(organization_id), "edge_id": edge_id, "collection_id": collection_id},
    )
    if not rows:
        return None
    row = rows[0]
    edge = _edge_response(row)
    source_props = _json_loads(row.get("source_properties"))
    target_props = _json_loads(row.get("target_properties"))
    native_context = await _fetch_native_edge_context(
        organization_id=organization_id,
        collection_id=collection_id,
        edge=edge,
    )
    return {
        "edge": edge,
        "source": {
            "node_id": row.get("source_node_id"),
            "node_type": row.get("source_node_type"),
            "label": _display_label(
                str(row.get("source_node_id")),
                str(row.get("source_node_type") or "Unknown"),
                source_props,
            ),
            "properties": _json_safe(source_props),
        },
        "target": {
            "node_id": row.get("target_node_id"),
            "node_type": row.get("target_node_type"),
            "label": _display_label(
                str(row.get("target_node_id")),
                str(row.get("target_node_type") or "Unknown"),
                target_props,
            ),
            "properties": _json_safe(target_props),
        },
        "provenance": {
            "source": edge["properties"].get("source") or edge["properties"].get("source_type") or "graph",
            "collection_id": collection_id or edge["properties"].get("collection_id"),
            "extraction": edge["properties"].get("extraction_method") or edge["properties"].get("relation_type") or "graph commit",
        },
        "temporal": {
            "valid_at": edge.get("created_at"),
            "last_seen": edge.get("updated_at"),
            "current": True,
        },
        "native": native_context,
        "raw": {
            "edge": edge,
            "source": _json_safe(source_props),
            "target": _json_safe(target_props),
        },
    }


async def _fetch_native_edge_context(
    *,
    organization_id: UUID,
    collection_id: Optional[str],
    edge: Dict[str, Any],
) -> Dict[str, Any]:
    if not collection_id:
        return {"temporal_facts": [], "lineage_edges": [], "feedback": {}}
    edge_id = str(edge.get("edge_id") or "")
    source_node_id = str(edge.get("source_node_id") or "")
    target_node_id = str(edge.get("target_node_id") or "")
    relationship_type = str(edge.get("relationship_type") or "")
    edge_refs = list(
        dict.fromkeys(
            ref
            for ref in (
                edge_id,
                _stable_edge_ref(
                    source_node_id,
                    target_node_id,
                    relationship_type,
                    collection_id=collection_id,
                )
                if source_node_id and target_node_id and relationship_type
                else None,
                _stable_edge_ref(source_node_id, target_node_id, relationship_type)
                if source_node_id and target_node_id and relationship_type
                else None,
            )
            if ref
        )
    )
    lineage_relationship_types = [relationship_type]
    if relationship_type not in DECISION_EDGE_TYPES:
        lineage_relationship_types.append("DERIVED_RELATIONSHIP")

    async with get_db_context() as db:
        exact_temporal_result = await db.execute(
            select(ContextTemporalFact)
            .where(ContextTemporalFact.organization_id == organization_id)
            .where(ContextTemporalFact.collection_readable_id == collection_id)
            .where(ContextTemporalFact.primitive_ref.in_(edge_refs or [""]))
            .order_by(ContextTemporalFact.transaction_created_at.desc())
            .limit(8)
        )
        temporal_items = list(exact_temporal_result.scalars().all())
        if len(temporal_items) < 4 and source_node_id and target_node_id:
            contextual_temporal_result = await db.execute(
                select(ContextTemporalFact)
                .where(ContextTemporalFact.organization_id == organization_id)
                .where(ContextTemporalFact.collection_readable_id == collection_id)
                .where(ContextTemporalFact.subject_node_id == source_node_id)
                .where(ContextTemporalFact.predicate == relationship_type)
                .where(cast(ContextTemporalFact.object_value, String).contains(target_node_id))
                .order_by(ContextTemporalFact.transaction_created_at.desc())
                .limit(8)
            )
            seen_fact_ids = {item.id for item in temporal_items}
            temporal_items.extend(
                item
                for item in contextual_temporal_result.scalars().all()
                if item.id not in seen_fact_ids
            )

        lineage_result = await db.execute(
            select(ContextLineageEdge)
            .where(ContextLineageEdge.organization_id == organization_id)
            .where(ContextLineageEdge.collection_readable_id == collection_id)
            .where(ContextLineageEdge.status == "current")
            .where(
                or_(
                    *[
                        cast(ContextLineageEdge.evidence, String).contains(ref)
                        for ref in edge_refs
                    ],
                    (
                        (ContextLineageEdge.from_ref == source_node_id)
                        & (ContextLineageEdge.to_ref == target_node_id)
                        & (ContextLineageEdge.relationship_type.in_(lineage_relationship_types))
                    ),
                )
            )
            .order_by(ContextLineageEdge.transaction_created_at.desc())
            .limit(16)
        )
        lineage_items = list(lineage_result.scalars().all())
    return {
        "temporal_facts": [_temporal_fact_payload(item) for item in temporal_items],
        "lineage_edges": [_lineage_edge_payload(item) for item in lineage_items],
        "feedback": _score_feedback(temporal_items, lineage_items),
    }


# Response models
class GraphNodeResponse(BaseModel):
    """Graph node response."""

    node_id: str
    node_type: str
    properties: Dict
    labels: List[str]
    created_at: str
    updated_at: str


class GraphEdgeResponse(BaseModel):
    """Graph edge response."""

    edge_id: str
    relationship_type: str
    source_node_id: str
    target_node_id: str
    fact: str
    properties: Dict
    created_at: str
    updated_at: str


class GraphDataResponse(BaseModel):
    """Full graph data response."""

    nodes: List[Dict]
    edges: List[Dict]
    total_nodes: int
    total_edges: int


class GraphStatsResponse(BaseModel):
    """Graph statistics response."""

    total_nodes: int
    total_edges: int
    node_types: Dict[str, int]
    relationship_types: Dict[str, int]


@router.get(
    "/organizations/{organization_id}",
    response_model=GraphDataResponse,
    summary="Get organization knowledge graph",
    description="Retrieve the complete knowledge graph for an organization",
)
async def get_organization_graph(
    organization_id: UUID,
    ctx: ApiContext = Depends(get_context),
    limit: int = Query(default=10000, ge=1, le=50000, description="Maximum nodes/edges to return"),
) -> GraphDataResponse:
    """Get the complete knowledge graph for an organization.

    Returns all nodes and edges up to the specified limit.
    Useful for graph visualization in the UI.

    Args:
        organization_id: Organization ID
        limit: Maximum number of nodes/edges to return

    Returns:
        Graph data with nodes and edges
    """
    try:
        _authorize_organization_scope(organization_id, ctx)

        # Check if graph is enabled
        config = get_graph_config()
        if not config.enabled:
            raise HTTPException(
                status_code=503,
                detail="Knowledge graph is not enabled. Set GRAPH_ENABLED=true to enable.",
            )

        # Get graph constructor
        constructor = await get_graph_constructor(config)

        # Get graph data
        graph_data = await constructor.get_graph_for_organization(
            organization_id=organization_id,
            limit=limit,
        )

        return GraphDataResponse(
            nodes=graph_data["nodes"],
            edges=graph_data["edges"],
            total_nodes=len(graph_data["nodes"]),
            total_edges=len(graph_data["edges"]),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get graph for organization {organization_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve knowledge graph: {str(e)}")


@router.get(
    "/organizations/{organization_id}/node/{node_id}",
    response_model=Dict,
    summary="Get graph node by ID",
    description="Retrieve a specific node from the knowledge graph",
)
async def get_graph_node(
    organization_id: UUID,
    node_id: str,
    ctx: ApiContext = Depends(get_context),
) -> Dict:
    """Get a specific node from the knowledge graph.

    Args:
        node_id: Node ID
        organization_id: Organization ID

    Returns:
        Node data
    """
    try:
        _authorize_organization_scope(organization_id, ctx)

        config = get_graph_config()
        if not config.enabled:
            raise HTTPException(status_code=503, detail="Knowledge graph is not enabled")

        constructor = await get_graph_constructor(config)
        node = await constructor.node_ops.get_by_id(node_id, organization_id)

        if not node:
            raise HTTPException(status_code=404, detail=f"Node {node_id} not found")

        return node.model_dump()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get node {node_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve node: {str(e)}")


@router.get(
    "/organizations/{organization_id}/node/{node_id}/edges",
    response_model=List[Dict],
    summary="Get edges for a node",
    description="Retrieve all edges connected to a specific node",
)
async def get_node_edges(
    organization_id: UUID,
    node_id: str,
    ctx: ApiContext = Depends(get_context),
    limit: int = Query(default=100, ge=1, le=1000),
) -> List[Dict]:
    """Get all edges connected to a node.

    Args:
        node_id: Node ID
        organization_id: Organization ID
        limit: Maximum number of edges to return

    Returns:
        List of edges
    """
    try:
        _authorize_organization_scope(organization_id, ctx)

        config = get_graph_config()
        if not config.enabled:
            raise HTTPException(status_code=503, detail="Knowledge graph is not enabled")

        constructor = await get_graph_constructor(config)
        edges = await constructor.edge_ops.get_node_edges(
            node_id=node_id,
            organization_id=organization_id,
            limit=limit,
        )

        return [edge.model_dump() for edge in edges]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get edges for node {node_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve edges: {str(e)}")


@router.get(
    "/organizations/{organization_id}/stats",
    response_model=GraphStatsResponse,
    summary="Get graph statistics",
    description="Get statistics about the knowledge graph",
)
async def get_graph_stats(
    organization_id: UUID,
    ctx: ApiContext = Depends(get_context),
) -> GraphStatsResponse:
    """Get statistics about the knowledge graph.

    Args:
        organization_id: Organization ID

    Returns:
        Graph statistics
    """
    try:
        _authorize_organization_scope(organization_id, ctx)

        config = get_graph_config()
        if not config.enabled:
            raise HTTPException(status_code=503, detail="Knowledge graph is not enabled")

        constructor = await get_graph_constructor(config)

        # Get all nodes and edges
        graph_data = await constructor.get_graph_for_organization(
            organization_id=organization_id,
            limit=10000,  # Get enough for stats
        )

        # Calculate statistics
        nodes = graph_data["nodes"]
        edges = graph_data["edges"]

        # Count by type
        node_types: Dict[str, int] = {}
        for node in nodes:
            node_type = node.get("node_type", "Unknown")
            node_types[node_type] = node_types.get(node_type, 0) + 1

        relationship_types: Dict[str, int] = {}
        for edge in edges:
            rel_type = edge.get("relationship_type", "Unknown")
            relationship_types[rel_type] = relationship_types.get(rel_type, 0) + 1

        return GraphStatsResponse(
            total_nodes=len(nodes),
            total_edges=len(edges),
            node_types=node_types,
            relationship_types=relationship_types,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get graph stats for organization {organization_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve stats: {str(e)}")


@router.get(
    "/organizations/{organization_id}/explorer",
    response_model=Dict[str, Any],
    summary="Explore the organization knowledge graph",
    description=(
        "Neo4j-backed graph workbench data: fulltext search seeds, neighborhood "
        "expansion, facets, totals, and inspector payload."
    ),
)
async def explore_organization_graph(
    organization_id: UUID,
    ctx: ApiContext = Depends(get_context),
    q: Optional[str] = Query(default=None, description="Fulltext search query over graph nodes"),
    collection_id: Optional[str] = Query(default=None, description="Optional context database readable id"),
    selected_node_id: Optional[str] = Query(default=None, description="Node selected in the graph inspector"),
    selected_edge_id: Optional[str] = Query(default=None, description="Edge selected in the graph inspector"),
    node_type: Optional[str] = Query(default=None, description="Node type filter"),
    edge_type: Optional[str] = Query(default=None, description="Relationship type filter"),
    depth: int = Query(default=1, ge=1, le=3, description="Neighborhood depth from search seeds"),
    limit: int = Query(default=220, ge=25, le=600, description="Maximum visible nodes"),
) -> Dict[str, Any]:
    """Return a graph-explorer payload backed by Neo4j.

    The old graph endpoint returns raw nodes and edges. This endpoint is the
    workbench contract: it searches Neo4j fulltext first, falls back to Cypher
    property matching, expands the matching seeds, and returns a ready-to-render
    graph plus inspector/provenance data.
    """
    try:
        _authorize_organization_scope(organization_id, ctx)
        await _validate_collection_scope(collection_id, ctx)

        config = get_graph_config()
        if not config.enabled:
            raise HTTPException(
                status_code=503,
                detail="Knowledge graph is not enabled. Set GRAPH_ENABLED=true to enable.",
            )

        constructor = await get_graph_constructor(config)
        base_driver = constructor.driver
        await base_driver.connect()
        driver = base_driver
        if collection_id:
            target_database = await base_driver.ensure_context_database(
                organization_id,
                collection_id,
            )
            repaired = await _ensure_collection_graph_materialized(
                base_driver,
                organization_id=organization_id,
                collection_id=collection_id,
                target_database=target_database,
            )
            if repaired:
                logger.info(
                    "Graph explorer rehydrated collection %s before rendering.",
                    collection_id,
                )
            driver = base_driver.for_database(target_database)

        normalized_query = (q or "").strip()
        seed_limit = 36 if normalized_query else 28
        seeds: List[Dict[str, Any]] = []
        if selected_node_id:
            seeds.append(
                {
                    "node_id": selected_node_id,
                    "label": selected_node_id,
                    "node_type": None,
                    "score": 1,
                    "source": "selection",
                }
            )

        if normalized_query:
            try:
                seeds.extend(
                    await _fulltext_seed_ids(
                        organization_id=organization_id,
                        query=normalized_query,
                        limit=seed_limit,
                        collection_id=collection_id,
                    )
                )
            except Exception as search_error:
                logger.warning(
                    "Neo4j fulltext graph explorer search failed for org %s: %s",
                    organization_id,
                    search_error,
                )

        if len(seeds) < max(8, seed_limit // 3):
            existing = {seed.get("node_id") for seed in seeds}
            fallback = await _fallback_seed_ids(
                driver,
                organization_id=organization_id,
                query=normalized_query,
                collection_id=collection_id,
                node_type=node_type,
                limit=seed_limit,
            )
            seeds.extend(seed for seed in fallback if seed.get("node_id") not in existing)

        seed_ids = [
            str(seed.get("node_id"))
            for seed in seeds
            if seed.get("node_id")
        ]
        nodes, edges, degree_map = await _fetch_neighborhood(
            driver,
            organization_id=organization_id,
            seed_ids=seed_ids,
            focus_node_id=selected_node_id,
            depth=depth,
            limit=limit,
            collection_id=collection_id,
            node_type=node_type,
            edge_type=edge_type,
        )

        selected_id = selected_node_id
        if not selected_id and nodes:
            selected_id = nodes[0]["node_id"]
        elif not selected_id and seed_ids:
            selected_id = seed_ids[0]
        if selected_id:
            for node in nodes:
                node["is_selected"] = node["node_id"] == selected_id
                node["degree"] = degree_map.get(node["node_id"], node.get("degree", 0))

        facets = await _fetch_graph_facets(
            driver,
            organization_id=organization_id,
            collection_id=collection_id,
        )
        stats = await _fetch_graph_stats(
            driver,
            organization_id=organization_id,
            collection_id=collection_id,
        )
        inspector = await _fetch_inspector(
            driver,
            organization_id=organization_id,
            node_id=selected_id,
            collection_id=collection_id,
        )
        edge_inspector = await _fetch_edge_inspector(
            driver,
            organization_id=organization_id,
            edge_id=selected_edge_id,
            collection_id=collection_id,
        )

        return {
            "nodes": nodes,
            "edges": edges,
            "stats": {
                **stats,
                "visible_nodes": len(nodes),
                "visible_edges": len(edges),
                "seed_count": len(set(seed_ids)),
                "depth": depth,
            },
            "facets": facets,
            "search": {
                "query": normalized_query,
                "matched_nodes": seeds[:24],
                "mode": "fulltext_neighborhood" if normalized_query else "central_neighborhood",
            },
            "inspector": inspector,
            "edge_inspector": edge_inspector,
            "filters": {
                "collection_id": collection_id,
                "node_type": node_type,
                "edge_type": edge_type,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to explore graph for organization %s: %s",
            organization_id,
            e,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"Failed to explore knowledge graph: {str(e)}")


@router.get(
    "/health",
    summary="Check graph database health",
    description="Check if the Neo4j graph database is healthy and accessible",
)
async def check_graph_health() -> Dict[str, str]:
    """Check Neo4j graph database health.

    Returns:
        Health status
    """
    try:
        config = get_graph_config()
        if not config.enabled:
            return {"status": "disabled", "message": "Graph construction is disabled"}

        constructor = await get_graph_constructor(config)
        is_healthy = await constructor.driver.health_check()

        if is_healthy:
            return {"status": "healthy", "message": "Neo4j is connected and healthy"}
        else:
            return {"status": "unhealthy", "message": "Neo4j is not responding"}

    except Exception as e:
        logger.error(f"Graph health check failed: {e}")
        return {"status": "error", "message": str(e)}
