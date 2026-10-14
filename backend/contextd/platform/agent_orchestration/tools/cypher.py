"""Read-only Cypher execution helpers for GLM tools."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from contextd.api.context import ApiContext

logger = logging.getLogger(__name__)

_GRAPH_SQL_FORBIDDEN = re.compile(
    r"\b(CREATE|MERGE|SET|DELETE|DETACH|REMOVE|DROP)\b",
    re.IGNORECASE,
)
_CALL_DB_FORBIDDEN_UNLESS_FULLTEXT = re.compile(
    r"CALL\s+db\.(?!index\.fulltext\.(queryNodes|queryLinks)\s*\()",
    re.IGNORECASE,
)
_GRAPH_SQL_MAX_RESULTS = 500

_CYPHER_STRIP_LITERALS = re.compile(
    r"""
        '(?:\\.|[^'\\])*'           # single-quoted string literal
        | "(?:\\.|[^"\\])*"         # double-quoted string literal
        | `(?:\\.|[^`\\])*`         # backtick-quoted identifier
        | /\*[\s\S]*?\*/            # block comment
        | //[^\n]*                  # line comment
    """,
    re.VERBOSE,
)


def _strip_cypher_literals(query: str) -> str:
    """Blank string, identifier, and comment spans before keyword checks."""
    return _CYPHER_STRIP_LITERALS.sub(" ", query)


def _validate_read_only_cypher(query: str) -> None:
    """Raise ValueError if query contains writes or disallowed procedures."""
    scrubbed = _strip_cypher_literals(query)
    if _GRAPH_SQL_FORBIDDEN.search(scrubbed):
        raise ValueError("Only read-only Cypher is allowed (no CREATE/MERGE/SET/DELETE/DETACH)")
    if _CALL_DB_FORBIDDEN_UNLESS_FULLTEXT.search(scrubbed):
        raise ValueError(
            "Only read-only Cypher is allowed (no CREATE/MERGE/SET/DETACH). "
            "CALL db.* is allowed only for fulltext: db.index.fulltext.queryNodes / queryLinks."
        )


def _normalize_cypher_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Parse JSON strings in node-property columns so rows expose property dicts."""
    if not isinstance(row, dict):
        return row
    out = dict(row)
    for key in list(out.keys()):
        value = out[key]
        if not isinstance(value, str):
            continue
        if key in ("details", "attributes") or key.endswith("_details"):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    out[key] = parsed
            except (json.JSONDecodeError, TypeError):
                pass
    return out


async def graph_sql(
    query: str,
    organization_id: UUID,
    ctx: ApiContext,
    *,
    params: Optional[Dict[str, Any]] = None,
    max_results: int = _GRAPH_SQL_MAX_RESULTS,
    readable_collection_id: str = "",
) -> List[Dict[str, Any]]:
    """Execute read-only Cypher scoped by organization_id."""
    _validate_read_only_cypher(query)

    from contextd.platform.graph.driver.neo4j_driver import convert_neo4j_types
    from contextd.platform.graph.factory import get_graph_driver

    driver = await get_graph_driver()
    neo4j_database = None
    if readable_collection_id:
        neo4j_database = await driver.ensure_context_database(
            organization_id,
            readable_collection_id,
        )
    query_params: Dict[str, Any] = {
        "organization_id": str(organization_id),
        **(params or {}),
    }

    logger.info("run_cypher (Cypher) executing full query:\n%s", query)
    try:
        records = await driver.execute_read(query, query_params, database=neo4j_database)
    except Exception as e:
        logger.warning(
            "run_cypher (Cypher) execution failed: %s. Full query:\n%s",
            e,
            query,
        )
        raise

    records = [convert_neo4j_types(record) for record in records]
    records = [_normalize_cypher_row(record) for record in records]
    return records[:max_results]


async def get_cypher_vocabulary(
    organization_id: UUID,
    ctx: ApiContext,
    readable_collection_id: str = "",
) -> Tuple[List[str], List[str]]:
    """Fetch distinct node_type and relationship_type values for prompt injection."""
    node_query = (
        "MATCH (n:GraphNode) WHERE n.organization_id = $organization_id "
        "RETURN DISTINCT n.node_type AS type"
    )
    rel_query = (
        "MATCH (a:GraphNode)-[r:RELATES_TO]->(b:GraphNode) "
        "WHERE a.organization_id = $organization_id "
        "RETURN DISTINCT r.relationship_type AS type"
    )
    try:
        node_records = await graph_sql(
            node_query,
            organization_id,
            ctx,
            max_results=500,
            readable_collection_id=readable_collection_id,
        )
        rel_records = await graph_sql(
            rel_query,
            organization_id,
            ctx,
            max_results=500,
            readable_collection_id=readable_collection_id,
        )
    except Exception as e:
        logger.warning("get_cypher_vocabulary failed: %s", e)
        return ([], [])
    node_types = [
        str(record["type"]).strip()
        for record in node_records
        if record.get("type") is not None
    ]
    rel_types = [
        str(record["type"]).strip()
        for record in rel_records
        if record.get("type") is not None
    ]
    return (node_types, rel_types)
