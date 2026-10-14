"""Graph retrieval and notebook-to-traversal conversion for GLM runtime."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select

from contextd.api.context import ApiContext
from contextd.core.logging import LoggerConfigurator
from contextd.db.session import get_db_context
from contextd.models.context_intelligence import ContextTemporalFact
from contextd.platform.agent_orchestration.tools import node_info
from contextd.platform.agent_orchestration.types import NotebookState

logger = LoggerConfigurator.configure_logger(__name__)


async def run_deterministic_graph_retrieval(
    query: str,
    organization_id: UUID,
    collection_id: UUID,
    readable_id: str,
    ctx: ApiContext,
    *,
    vector_size: int,
    search_limit: int = 10,
    max_depth: int = 2,
    node_limit: int = 100,
    source_type_filter: Optional[str] = None,
) -> Tuple[Any, List[Dict[str, Any]]]:
    """Run the deterministic path: seed search -> traversal."""
    from contextd.platform.graph.traversal import TraversalConfig, TraversalService
    from contextd.search.context import SearchContext
    from contextd.search.emitter import EventEmitter
    from contextd.search.operations.graph_search import GraphSearch

    search_results: List[Dict[str, Any]] = []
    node_ids: List[str] = []

    try:
        graph_search = GraphSearch(
            collection_id=collection_id,
            organization_id=organization_id,
            limit=search_limit,
            graph_depth=0,
            source_type_filter=source_type_filter,
        )
        emitter = EventEmitter(request_id=ctx.request_id, stream=False)
        search_context = SearchContext(
            request_id=ctx.request_id,
            collection_id=collection_id,
            readable_collection_id=readable_id,
            stream=False,
            vector_size=vector_size,
            offset=0,
            limit=search_limit,
            query=query,
            emitter=emitter,
            query_expansion=None,
            query_interpretation=None,
            embed_query=None,
            user_filter=None,
            temporal_relevance=None,
            retrieval=None,
            federated_search=None,
            reranking=None,
                generate_answer=None,
            )
        state: Dict[str, Any] = {}
        await graph_search.execute(context=search_context, state=state, ctx=ctx)
        search_results = state.get("graph_results", [])
        node_ids = [result["node_id"] for result in search_results if result.get("node_id")]
        search_results, node_ids = await _apply_feedback_ranking_prior(
            search_results,
            organization_id=organization_id,
            readable_id=readable_id,
        )

        if not node_ids:
            repaired = await _ensure_collection_graph_materialized_if_needed(
                organization_id=organization_id,
                readable_id=readable_id,
                ctx=ctx,
            )
            if repaired:
                state = {}
                await graph_search.execute(context=search_context, state=state, ctx=ctx)
                search_results = state.get("graph_results", [])
                node_ids = [
                    result["node_id"] for result in search_results if result.get("node_id")
                ]
                search_results, node_ids = await _apply_feedback_ranking_prior(
                    search_results,
                    organization_id=organization_id,
                    readable_id=readable_id,
                )

        if not node_ids:
            search_results = await _schema_or_relationship_seed_results(
                query=query,
                organization_id=organization_id,
                readable_id=readable_id,
                limit=search_limit,
                ctx=ctx,
            )
            node_ids = [result["node_id"] for result in search_results if result.get("node_id")]
            search_results, node_ids = await _apply_feedback_ranking_prior(
                search_results,
                organization_id=organization_id,
                readable_id=readable_id,
            )
        elif _query_requests_relationship_overview(query) and len(_seed_terms_from_query(query)) >= 2:
            schema_results = await _schema_or_relationship_seed_results(
                query=query,
                organization_id=organization_id,
                readable_id=readable_id,
                limit=search_limit,
                ctx=ctx,
            )
            if schema_results:
                schema_first = len(_matched_schema_seed_terms(schema_results)) >= 2
                search_results = _merge_seed_results(
                    schema_results if schema_first else search_results,
                    search_results if schema_first else schema_results,
                    limit=max(search_limit * 2, search_limit + len(schema_results)),
                )
                node_ids = [
                    result["node_id"] for result in search_results if result.get("node_id")
                ]
                search_results, node_ids = await _apply_feedback_ranking_prior(
                    search_results,
                    organization_id=organization_id,
                    readable_id=readable_id,
                    preserve_order=schema_first,
                )
    except Exception as e:
        logger.warning("Graph search failed: %s", e)
        return (None, search_results)

    if not node_ids:
        return (None, search_results)

    try:
        service = await TraversalService.create()
        try:
            config = TraversalConfig(
                max_depth=max_depth,
                node_limit=node_limit,
                include_properties=True,
            )
            traversal_result = await service.traverse(
                node_ids=node_ids,
                organization_id=organization_id,
                config=config,
                readable_collection_id=readable_id,
            )
            return (traversal_result, search_results)
        finally:
            await service.close()
    except Exception as e:
        logger.warning("Traversal failed: %s", e)
        return (None, search_results)


async def _apply_feedback_ranking_prior(
    search_results: List[Dict[str, Any]],
    *,
    organization_id: UUID,
    readable_id: str,
    preserve_order: bool = False,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Use native answer feedback as a small, bounded retrieval prior."""
    node_ids = [result["node_id"] for result in search_results if result.get("node_id")]
    if not node_ids:
        return search_results, []

    try:
        async with get_db_context() as db:
            result = await db.execute(
                select(
                    ContextTemporalFact.subject_node_id,
                    func.avg(ContextTemporalFact.feedback_weight).label("feedback_weight"),
                )
                .where(ContextTemporalFact.organization_id == organization_id)
                .where(ContextTemporalFact.collection_readable_id == readable_id)
                .where(ContextTemporalFact.status == "current")
                .where(ContextTemporalFact.subject_node_id.in_(node_ids[:250]))
                .group_by(ContextTemporalFact.subject_node_id)
            )
            weights = {
                str(row.subject_node_id): float(row.feedback_weight or 1.0)
                for row in result
                if row.subject_node_id
            }
    except Exception as exc:
        logger.debug("Feedback ranking prior skipped: %s", exc)
        return search_results, node_ids

    if not weights:
        return search_results, node_ids

    reranked: List[Dict[str, Any]] = []
    for item in search_results:
        node_id = item.get("node_id")
        weight = weights.get(str(node_id), 1.0)
        adjusted = dict(item)
        try:
            base_score = float(adjusted.get("score") or 0.0)
        except (TypeError, ValueError):
            base_score = 0.0
        # Keep lexical/vector relevance dominant while letting repeated feedback move ties.
        adjusted["feedback_weight"] = round(weight, 4)
        adjusted["score"] = round(base_score * (0.9 + (0.1 * weight)), 6)
        reranked.append(adjusted)

    if not preserve_order:
        reranked.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    reranked_node_ids = [result["node_id"] for result in reranked if result.get("node_id")]
    return reranked, reranked_node_ids


async def _ensure_collection_graph_materialized_if_needed(
    *,
    organization_id: UUID,
    readable_id: str,
    ctx: ApiContext,
) -> bool:
    """Repair an empty collection-scoped Neo4j database from committed events.

    The graph event log in Postgres is the durable source of truth. During the
    collection-per-Neo4j-database migration an existing collection can have
    committed events but an empty scoped Neo4j database; query retrieval should
    repair that once instead of returning an empty success.
    """
    try:
        from contextd.models.source_connection import SourceConnection
        from contextd.platform.graph.factory import get_graph_driver
        from contextd.platform.sync.graph.commit_service import GraphCommitService

        driver = await get_graph_driver()
        target_database = await driver.ensure_context_database(organization_id, readable_id)
        node_rows = await driver.execute_read(
            """
            MATCH (n:GraphNode {organization_id: $organization_id, collection_id: $collection_id})
            RETURN count(n) AS nodes
            """,
            {
                "organization_id": str(organization_id),
                "collection_id": readable_id,
            },
            database=target_database,
        )
        existing_nodes = int((node_rows[0] if node_rows else {}).get("nodes") or 0)
        if existing_nodes > 0:
            return False

        async with get_db_context() as db:
            sync_rows = await db.execute(
                select(SourceConnection.sync_id)
                .where(SourceConnection.organization_id == organization_id)
                .where(SourceConnection.readable_collection_id == readable_id)
                .where(SourceConnection.sync_id.is_not(None))
            )
            sync_ids = [row.sync_id for row in sync_rows if row.sync_id]

        if not sync_ids:
            return False

        commit_service = GraphCommitService(driver)
        total_nodes = 0
        total_edges = 0
        for sync_id in sync_ids:
            result = await commit_service.rehydrate_committed_sync_events(
                sync_id=sync_id,
                organization_id=organization_id,
                readable_collection_id=readable_id,
            )
            if result.success:
                total_nodes += result.nodes_committed
                total_edges += result.edges_committed
            else:
                ctx.logger.warning(
                    "[GraphSearch] Neo4j rehydrate failed for sync %s: %s",
                    sync_id,
                    result.error,
                )

        if total_nodes or total_edges:
            ctx.logger.info(
                "[GraphSearch] Rehydrated Neo4j collection %s from committed events: "
                "%s nodes, %s edges",
                readable_id,
                total_nodes,
                total_edges,
            )
            return True
    except Exception as exc:
        ctx.logger.warning(
            "[GraphSearch] Skipped Neo4j collection repair for %s: %s",
            readable_id,
            exc,
        )

    return False


_SEED_STOPWORDS = {
    "about",
    "across",
    "after",
    "all",
    "and",
    "are",
    "between",
    "connected",
    "connection",
    "connections",
    "for",
    "find",
    "from",
    "graph",
    "hop",
    "hops",
    "into",
    "neighborhood",
    "network",
    "one",
    "relationship",
    "relationships",
    "search",
    "show",
    "strong",
    "strongest",
    "the",
    "their",
    "three",
    "this",
    "that",
    "two",
    "with",
}


def _seed_terms_from_query(query: str) -> List[str]:
    terms: List[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        if term and term not in seen:
            seen.add(term)
            terms.append(term)

    for raw in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", query or ""):
        token = raw.lower().strip("_")
        if token in _SEED_STOPWORDS:
            continue
        add(token)
        if token.endswith("ies") and len(token) > 4:
            add(f"{token[:-3]}y")
        if token.endswith("es") and len(token) > 4:
            add(token[:-2])
        if token.endswith("s") and len(token) > 4:
            add(token[:-1])
    return terms


def _merge_seed_results(
    primary: List[Dict[str, Any]],
    secondary: List[Dict[str, Any]],
    *,
    limit: int,
) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in primary + secondary:
        node_id = item.get("node_id")
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)
        merged.append(item)
        if len(merged) >= limit:
            break
    return merged


def _matched_schema_seed_terms(results: List[Dict[str, Any]]) -> set[str]:
    """Return the query schema/table terms represented in schema seed rows."""
    matched: set[str] = set()
    for item in results:
        graph_context = item.get("graph_context") or {}
        for key in ("matched_seed_term",):
            value = graph_context.get(key)
            if value:
                matched.add(str(value))
        for value in graph_context.get("matched_seed_terms") or []:
            if value:
                matched.add(str(value))
    return matched


async def _schema_or_relationship_seed_results(
    *,
    query: str,
    organization_id: UUID,
    readable_id: str,
    limit: int,
    ctx: ApiContext,
) -> List[Dict[str, Any]]:
    """Seed graph traversal from mentioned table/entity types or high-degree nodes.

    Fulltext is great when the user names a concrete entity. Queries such as
    "show studios, trainers, classes..." name schema/table concepts, so we seed
    by node_type/node_id vocabulary and fall back to relationship-dense nodes.
    """
    from contextd.platform.graph.driver.neo4j_driver import convert_neo4j_types
    from contextd.platform.graph.factory import get_graph_driver

    terms = _seed_terms_from_query(query)
    if not terms and not _query_requests_relationship_overview(query):
        return []

    driver = await get_graph_driver()
    target_database = await driver.ensure_context_database(organization_id, readable_id)
    params = {
        "organization_id": str(organization_id),
        "collection_id": readable_id,
        "terms": terms,
        "limit": max(1, limit),
    }

    records: List[Dict[str, Any]] = []
    seen_node_ids: set[str] = set()
    per_term_limit = 2 if len(terms) >= 4 else 3

    for term in terms[:24]:
        property_terms = [candidate for candidate in terms if candidate != term]
        term_records = await driver.execute_read(
            """
            MATCH (n:GraphNode {organization_id: $organization_id, collection_id: $collection_id})
            WITH n,
                 toLower(coalesce(n.node_type, "")) AS node_type,
                 toLower(coalesce(n.node_id, "")) AS node_id,
                 toLower(coalesce(n.properties, "")) AS property_blob
            WHERE node_type CONTAINS $term OR node_id CONTAINS $term
            OPTIONAL MATCH (n)-[r:RELATES_TO]-(:GraphNode {
                organization_id: $organization_id,
                collection_id: $collection_id
            })
            WITH n, property_blob, count(r) AS degree,
                 reduce(
                    score = 0,
                    candidate IN $property_terms |
                    score + CASE WHEN property_blob CONTAINS candidate THEN 1 ELSE 0 END
                 ) AS property_match_count
            RETURN n.node_id AS node_id,
                   n.node_type AS node_type,
                   n.properties AS properties,
                   n.ft_name AS ft_name,
                   degree,
                   property_match_count,
                   $term AS matched_seed_term
            ORDER BY property_match_count DESC, degree DESC, node_id ASC
            LIMIT $per_term_limit
            """,
            {
                **params,
                "term": term,
                "property_terms": property_terms,
                "per_term_limit": per_term_limit,
            },
            database=target_database,
        )
        for record in term_records:
            node_id = str(record.get("node_id") or "")
            if node_id and node_id not in seen_node_ids:
                seen_node_ids.add(node_id)
                records.append(record)
            if len(records) >= limit:
                break
        if len(records) >= limit:
            break

    if len(records) < limit and terms:
        fill_records = await driver.execute_read(
            """
            MATCH (n:GraphNode {organization_id: $organization_id, collection_id: $collection_id})
            WITH n,
                 toLower(coalesce(n.node_type, "")) AS node_type,
                 toLower(coalesce(n.node_id, "")) AS node_id,
                 toLower(coalesce(n.properties, "")) AS property_blob
            WHERE any(term IN $terms WHERE node_type CONTAINS term OR node_id CONTAINS term)
            OPTIONAL MATCH (n)-[r:RELATES_TO]-(:GraphNode {
                organization_id: $organization_id,
                collection_id: $collection_id
            })
            WITH n, node_type, node_id, property_blob, count(r) AS degree,
                 [term IN $terms WHERE node_type CONTAINS term OR node_id CONTAINS term] AS matched_seed_terms,
                 reduce(
                    score = 0,
                    candidate IN $terms |
                    score + CASE WHEN property_blob CONTAINS candidate THEN 1 ELSE 0 END
                 ) AS property_match_count
            RETURN n.node_id AS node_id,
                   n.node_type AS node_type,
                   n.properties AS properties,
                   n.ft_name AS ft_name,
                   degree,
                   property_match_count,
                   matched_seed_terms
            ORDER BY size(matched_seed_terms) DESC, property_match_count DESC, degree DESC, node_id ASC
            LIMIT $limit
            """,
            params,
            database=target_database,
        )
        for record in fill_records:
            node_id = str(record.get("node_id") or "")
            if node_id and node_id not in seen_node_ids:
                seen_node_ids.add(node_id)
                records.append(record)
            if len(records) >= limit:
                break

    if not records and _query_requests_relationship_overview(query):
        records = await driver.execute_read(
            """
            MATCH (n:GraphNode {organization_id: $organization_id, collection_id: $collection_id})
            OPTIONAL MATCH (n)-[r:RELATES_TO]-(:GraphNode {
                organization_id: $organization_id,
                collection_id: $collection_id
            })
            WITH n, count(r) AS degree
            RETURN n.node_id AS node_id,
                   n.node_type AS node_type,
                   n.properties AS properties,
                   n.ft_name AS ft_name,
                   degree,
                   0 AS property_match_count,
                   [] AS matched_seed_terms
            ORDER BY degree DESC, node_id ASC
            LIMIT $limit
            """,
            params,
            database=target_database,
        )

    search_results: List[Dict[str, Any]] = []
    for idx, record in enumerate(convert_neo4j_types(records)):
        props = _parse_neo4j_properties(record.get("properties"))
        node_id = str(record.get("node_id") or "")
        if not node_id:
            continue
        degree = int(record.get("degree") or 0)
        matched_seed_terms = [
            str(term)
            for term in (record.get("matched_seed_terms") or [])
            if term
        ]
        matched_seed_term = record.get("matched_seed_term")
        if matched_seed_term and str(matched_seed_term) not in matched_seed_terms:
            matched_seed_terms.append(str(matched_seed_term))
        property_match_count = int(record.get("property_match_count") or 0)
        name = _display_name_for_seed(record, props, node_id)
        search_results.append(
            {
                "id": node_id,
                "node_id": node_id,
                "node_type": record.get("node_type"),
                "name": name,
                "score": max(0.01, 1.0 - (idx * 0.025)) + min(degree, 1000) / 10000,
                "payload": props,
                "source": "schema_relationship_seed",
                "graph_context": {
                    "degree": degree,
                    "seed_terms": terms,
                    "matched_seed_terms": matched_seed_terms,
                    "matched_seed_term": matched_seed_terms[0] if matched_seed_terms else None,
                    "property_match_count": property_match_count,
                },
                "relationships": [],
            }
        )

    if search_results:
        ctx.logger.info(
            "[GraphSearch] Seeded traversal from schema/relationship fallback for %s: "
            "%s seeds from terms=%s",
            readable_id,
            len(search_results),
            terms,
        )
    return search_results


def _query_requests_relationship_overview(query: str) -> bool:
    text = (query or "").lower()
    return any(
        token in text
        for token in (
            "graph",
            "relationship",
            "relationships",
            "connected",
            "strongest",
            "network",
        )
    )


def _parse_neo4j_properties(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}
    return {}


def _display_name_for_seed(record: Dict[str, Any], props: Dict[str, Any], node_id: str) -> str:
    name = record.get("ft_name") or props.get("name") or props.get("title")
    if name:
        return str(name)
    first_name = props.get("first_name")
    last_name = props.get("last_name")
    if first_name or last_name:
        return " ".join(str(part) for part in (first_name, last_name) if part)
    return node_id.split(":")[-1] if ":" in node_id else node_id


def _expand_cypher_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Merge node property bag columns into the flat row properties."""
    property_bag_keys = ("details", "attributes", "person_details", "user_details", "properties")
    out = dict(row)
    for key in list(out.keys()):
        if key in property_bag_keys and isinstance(out[key], dict):
            for nested_key, value in out[key].items():
                if nested_key not in out:
                    out[nested_key] = value
            del out[key]
    return out


_NODE_ID_TABLE_TO_TYPE: Dict[str, str] = {
    "persons": "PersonNode",
    "orders": "OrdersTableEntity",
    "leads": "LeadsTableEntity",
    "products": "ProductsTableEntity",
    "support_tickets": "SupportTicketsTableEntity",
}


def _node_type_from_node_id(node_id: str) -> Optional[str]:
    """Derive node_type from node_id when format is public.<table>:<id>."""
    if not node_id or not isinstance(node_id, str):
        return None
    if not node_id.startswith("public.") or ":" not in node_id:
        return None
    table = node_id[7:].split(":")[0].strip()
    return _NODE_ID_TABLE_TO_TYPE.get(table)


def _get_row_node_id(row: Dict[str, Any]) -> Optional[str]:
    """Extract node_id from a Cypher row using common aliases."""
    for key in ("node_id", "node_Id", "Node_Id", "id", "node_id"):
        value = row.get(key)
        if value is not None and isinstance(value, str) and (":" in value or value.startswith("public.")):
            return value
    for key, value in row.items():
        if isinstance(value, str) and (":" in value or value.startswith("public.")):
            if "node" in key.lower() or key.lower() in ("id", "node_id"):
                return value
    return None


def _row_display_name(row: Dict[str, Any], node_id: str, node_type: str) -> str:
    """Build a readable display name for a Cypher row."""
    if node_id and not node_id.startswith("row_"):
        if node_id.startswith("public.") and ":" in node_id:
            return node_id[7:].replace(":", ".")
        return node_id

    props = _expand_cypher_row(row)
    label_cols = [
        "name",
        "title",
        "label",
        "subject",
        "category",
        "status",
        "specialty",
        "kind",
        "type",
        "role",
        "plan",
        "plan_name",
        "bucket",
        "group",
        "dimension",
    ]
    for col in label_cols:
        value = props.get(col)
        if isinstance(value, str) and value.strip():
            return value
        if value is not None and value != "" and not isinstance(value, (int, float, bool)):
            return str(value)

    skip_keys = {"node_id", "nodeId", "id", "node_type", "entity_type", "source_type"}
    for key, value in props.items():
        if key in skip_keys or str(key).endswith("_id") or str(key).endswith("Id"):
            continue
        if isinstance(value, str) and value.strip():
            return value

    return node_id or "entity"


def notebook_to_traversal_result(
    notebook: NotebookState,
    large_data_by_ref: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Any:
    """Convert notebook knowledge into a TraversalResult for GraphContextFormatter."""
    from contextd.platform.graph.traversal._base import (
        TraversalResult,
        TraversedEdge,
        TraversedNode,
    )

    sidecar: Dict[str, List[Dict[str, Any]]] = large_data_by_ref or {}
    nodes: List[TraversedNode] = []
    edges: List[TraversedEdge] = []
    seen_node_ids: set = set()
    node_id_to_index: Dict[str, int] = {}
    seen_edges: set = set()

    def _props(item: dict) -> dict:
        payload = item.get("properties") or item.get("payload")
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, str):
            try:
                return json.loads(payload)
            except json.JSONDecodeError:
                return {}
        return {}

    for item_idx, item in enumerate(notebook.current_knowledge):
        if not isinstance(item, dict):
            continue

        rows_list: Optional[List[Dict[str, Any]]] = None
        if "rows" in item and isinstance(item["rows"], list):
            rows_list = item["rows"]
        else:
            ref_id = item.get("large_data_ref")
            if ref_id and ref_id in sidecar:
                rows_list = sidecar[ref_id]

        if rows_list is not None:
            first_row = next((row for row in rows_list if isinstance(row, dict)), None)
            inferred_type: Optional[str] = None
            if first_row:
                first_nid = _get_row_node_id(first_row) or first_row.get("node_id")
                inferred_type = (
                    first_row.get("node_type")
                    or first_row.get("entity_type")
                    or (_node_type_from_node_id(first_nid) if first_nid else None)
                )
            for index, row in enumerate(rows_list):
                if not isinstance(row, dict):
                    continue
                node_id = _get_row_node_id(row)
                if node_id is None:
                    node_id = (
                        row.get("id")
                        or row.get("customer_id")
                        or row.get("support_ticket_id")
                        or row.get("lead_id")
                        or row.get("person_id")
                        or row.get("order_id")
                    )
                if node_id is None:
                    for value in row.values():
                        if isinstance(value, str) and (":" in value or value.startswith("public.")):
                            node_id = value
                            break
                if node_id is None:
                    node_id = f"row_{item_idx}_{index}"
                if not isinstance(node_id, str):
                    node_id = str(node_id)
                if node_id not in seen_node_ids:
                    seen_node_ids.add(node_id)
                    node_type = (
                        row.get("node_type")
                        or row.get("entity_type")
                        or _node_type_from_node_id(node_id)
                        or inferred_type
                        or "Row"
                    )
                    props = _expand_cypher_row(row)
                    display_name = (
                        props.get("name")
                        or props.get("person_name")
                        or row.get("subject")
                        or row.get("title")
                        or _row_display_name(row, node_id, node_type)
                    )
                    nodes.append(
                        TraversedNode(
                            node_id=node_id,
                            node_type=node_type,
                            name=display_name if isinstance(display_name, str) else _row_display_name(row, node_id, node_type),
                            properties=props,
                            depth=0,
                        )
                    )
                    node_id_to_index[node_id] = len(nodes) - 1
            continue

        node_id = item.get("node_id")
        if node_id:
            item_props = _props(item)
            if node_id in seen_node_ids:
                idx = node_id_to_index.get(node_id)
                if idx is not None and isinstance(item_props, dict):
                    existing = nodes[idx].properties or {}
                    has_full = any(
                        item_props.get(key)
                        for key in ("first_name", "last_name", "primary_email", "primary_phone", "city")
                    )
                    existing_aggregate = "total_order_value" in existing or (len(existing) <= 3 and "name" in existing)
                    if has_full and existing_aggregate or len(item_props) > len(existing):
                        nodes[idx].properties = item_props
                        nodes[idx].name = item.get("name")
                        nodes[idx].node_type = item.get("node_type", "Unknown")
            else:
                seen_node_ids.add(node_id)
                nodes.append(
                    TraversedNode(
                        node_id=node_id,
                        node_type=item.get("node_type", "Unknown"),
                        name=item.get("name"),
                        properties=item_props,
                        depth=0,
                    )
                )
                node_id_to_index[node_id] = len(nodes) - 1

        for neighbor in item.get("neighbors", []):
            nid = neighbor.get("neighbor_node_id")
            if nid and nid not in seen_node_ids:
                seen_node_ids.add(nid)
                nprops = neighbor.get("neighbor_properties") or neighbor.get("properties") or {}
                node_type = (
                    neighbor.get("neighbor_node_type")
                    or _node_type_from_node_id(nid)
                    or "Unknown"
                )
                nodes.append(
                    TraversedNode(
                        node_id=nid,
                        node_type=node_type,
                        name=neighbor.get("neighbor_name") or (nprops.get("name") if isinstance(nprops, dict) else None),
                        properties=nprops if isinstance(nprops, dict) else {},
                        depth=1,
                    )
                )
            rel = neighbor.get("relationship_type", "RELATES_TO")
            if isinstance(rel, type):
                rel = rel.__name__ if hasattr(rel, "__name__") else str(rel)
            from_id = item.get("node_id") or node_id
            if from_id and nid:
                edge_key = (from_id, nid)
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    edges.append(
                        TraversedEdge(
                            from_node_id=from_id,
                            to_node_id=nid,
                            relationship_type=rel,
                            direction=neighbor.get("direction", "outgoing"),
                        )
                    )

        for key, value in item.items():
            if key in ("node_id", "node_type", "name", "properties", "neighbors"):
                continue
            if key.endswith("_id") and isinstance(value, str) and value not in seen_node_ids:
                seen_node_ids.add(value)
                nodes.append(
                    TraversedNode(
                        node_id=value,
                        node_type=_node_type_from_node_id(value) or key.replace("_id", ""),
                        name=None,
                        properties=item,
                        depth=0,
                    )
                )
                node_id_to_index[value] = len(nodes) - 1
                break

    return TraversalResult(
        nodes=nodes,
        edges=edges,
        start_node_ids=[],
        config=None,
        stats={"source": "notebook", "node_count": len(nodes), "edge_count": len(edges)},
    )


def _looks_like_node_id(value: Any) -> bool:
    """True if value looks like a graph node_id."""
    if not isinstance(value, str) or len(value) < 5:
        return False
    if ":" in value and ("public." in value or value.replace(".", "").replace(":", "").replace("_", "").isalnum()):
        return True
    return False


async def enrich_traversal_result_with_referenced_nodes(
    traversal_result: Any,
    organization_id: UUID,
    ctx: ApiContext,
    readable_collection_id: str = "",
) -> Any:
    """Resolve node_id references in node properties to full node data."""
    if not traversal_result or not traversal_result.nodes:
        return traversal_result

    ref_keys_and_ids: List[Tuple[str, str]] = []
    for node in traversal_result.nodes:
        props = node.properties or {}
        for key, value in list(props.items()):
            if key in ("node_id", "organization_id", "sync_id"):
                continue
            if _looks_like_node_id(value):
                ref_keys_and_ids.append((key, value))
    if not ref_keys_and_ids:
        return traversal_result

    unique_ids = list(dict.fromkeys(value for _, value in ref_keys_and_ids))
    try:
        resolved = await node_info(
            unique_ids,
            organization_id,
            ctx,
            readable_collection_id=readable_collection_id,
        )
    except Exception as e:
        logger.warning("Enrich referenced nodes failed: %s", e)
        return traversal_result

    id_to_data: Dict[str, Dict[str, Any]] = {}
    for row in resolved:
        node_id = row.get("node_id")
        if node_id:
            id_to_data[node_id] = dict(row.get("properties") or {})
            if row.get("name") is not None:
                id_to_data[node_id]["name"] = row.get("name")

    for node in traversal_result.nodes:
        props = node.properties or {}
        to_merge: Dict[str, Any] = {}
        for key, value in list(props.items()):
            if not _looks_like_node_id(value):
                continue
            data = id_to_data.get(value)
            if not data:
                continue
            prefix = (key.replace("_id", "") or key).strip("_")
            prefix = (prefix + "_") if prefix else "ref_"
            for nested_key, nested_value in list(data.items()):
                if nested_key in ("node_id", "organization_id", "sync_id"):
                    continue
                to_merge[prefix + nested_key] = nested_value
        if to_merge:
            new_props = dict(props)
            new_props.update(to_merge)
            node.properties = new_props
    return traversal_result
