"""Two-Phase Graph Commit Service.

Handles Phase 2 of the two-phase graph construction pipeline:
- Loads deduplicated events from PostgreSQL
- Executes Neo4j transactions in batches (nodes first, then edges) to stay under
  dbms.memory.transaction.total.max and avoid MemoryPoolOutOfMemoryError
- Updates event status in PostgreSQL only after all batches succeed

This service is called after ALL sync batches complete, ensuring:
- No race conditions (sequential execution)
- Proper ordering (nodes before edges)
- Per-batch commit (each batch is atomic; full run is all-or-nothing for PG marking)
- Idempotent operations (safe to retry)
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

from neo4j.exceptions import ServiceUnavailable
from sqlalchemy import bindparam, text

from contextd.core.datetime_utils import utc_now_naive
from contextd.db.session import get_db_context
from contextd.platform.graph.config import get_graph_config
from contextd.platform.graph.driver.neo4j_driver import Neo4jDriver
from contextd.platform.graph.queries.node_queries import NodeQueryBuilder

logger = logging.getLogger(__name__)

# Batch sizes to keep each Neo4j transaction under transaction memory limit (~1.4 GiB default)
NODE_BATCH_SIZE = 5000
EDGE_BATCH_SIZE = 5000


@dataclass
class CommitResult:
    """Result of a graph commit operation."""

    success: bool
    nodes_committed: int = 0
    edges_committed: int = 0
    nodes_skipped: int = 0
    edges_skipped: int = 0
    metadata_skipped: int = 0
    error: Optional[str] = None
    duration_ms: int = 0


class GraphCommitService:
    """Service for committing graph events to Neo4j in batches.

    Implements Phase 2 of the two-phase commit pattern:
    1. Query PostgreSQL for deduplicated pending events
    2. Execute Neo4j in batches (nodes first, then edges) to stay under transaction memory limit
    3. Update event status in PostgreSQL only after all batches succeed

    Key guarantees:
    - Nodes are created before edges (proper ordering)
    - Each batch is one Neo4j transaction (rollback on batch failure)
    - PG events are marked committed only after every batch succeeds
    - Deduplication via SQL DISTINCT ON; idempotent MERGE (safe to retry)
    """

    def __init__(self, neo4j_driver: Neo4jDriver):
        """Initialize the commit service.

        Args:
            neo4j_driver: Neo4j driver instance for graph operations
        """
        self.driver = neo4j_driver

    async def commit_sync_events(
        self,
        sync_id: UUID,
        organization_id: UUID,
        *,
        readable_collection_id: Optional[str] = None,
        prune_stale_graph: bool = False,
        current_state_entity_count: Optional[int] = None,
        current_state_node_ids: Optional[Sequence[str]] = None,
    ) -> CommitResult:
        """Commit all pending events for a sync to Neo4j atomically.

        This is the main entry point for Phase 2 of the two-phase commit.
        Called by SyncOrchestrator after all batches complete.

        Args:
            sync_id: Sync ID to commit events for
            organization_id: Organization ID for graph scoping
            readable_collection_id: Collection readable_id; stored on nodes for schema scoping

        Returns:
            CommitResult with statistics and status
        """
        start_time = utc_now_naive()

        try:
            logger.info(f"[GraphCommit] Starting Phase 2 commit for sync {sync_id}")

            # Step 1: Get deduplicated nodes from PostgreSQL
            nodes = await self._get_deduplicated_nodes(sync_id)
            logger.info(f"[GraphCommit] Found {len(nodes)} unique nodes to commit")

            # Step 2: Get deduplicated edges from PostgreSQL
            edges = await self._get_deduplicated_edges(sync_id)
            logger.info(f"[GraphCommit] Found {len(edges)} unique edges to commit")

            if not nodes and not edges:
                metadata_skipped = await self._mark_metadata_skipped(sync_id)
                logger.info(f"[GraphCommit] No events to commit for sync {sync_id}")
                return CommitResult(
                    success=True,
                    metadata_skipped=metadata_skipped,
                    duration_ms=0,
                )

            committed_event_ids = self._collect_event_ids(nodes, edges)
            if not readable_collection_id:
                try:
                    readable_collection_id = await self._resolve_readable_collection_id(
                        sync_id,
                        organization_id,
                    )
                except Exception as collection_error:
                    logger.warning(
                        "[GraphCommit] Could not resolve collection scope for sync %s; "
                        "continuing with legacy graph identity: %s",
                        sync_id,
                        collection_error,
                    )

            target_database = await self.driver.ensure_context_database(
                organization_id,
                readable_collection_id,
            )

            # Step 3: Execute Neo4j in batches to avoid transaction memory limit (MemoryPoolOutOfMemoryError)
            nodes_committed = 0
            edges_committed = 0
            num_node_batches = (len(nodes) + NODE_BATCH_SIZE - 1) // NODE_BATCH_SIZE if nodes else 0
            num_edge_batches = (len(edges) + EDGE_BATCH_SIZE - 1) // EDGE_BATCH_SIZE if edges else 0

            for i in range(0, len(nodes), NODE_BATCH_SIZE):
                node_batch = nodes[i : i + NODE_BATCH_SIZE]
                batch_num = (i // NODE_BATCH_SIZE) + 1
                for tx_attempt in range(2):
                    try:
                        nc, _ = await self._execute_neo4j_transaction(
                            node_batch,
                            [],
                            organization_id,
                            readable_collection_id=readable_collection_id,
                            neo4j_database=target_database,
                        )
                        nodes_committed += nc
                        if num_node_batches > 1:
                            logger.info(
                                "[GraphCommit] Node batch %s/%s committed (%s nodes)",
                                batch_num,
                                num_node_batches,
                                nc,
                            )
                        break
                    except ServiceUnavailable as e:
                        if tx_attempt == 0:
                            logger.warning(
                                "[GraphCommit] Neo4j connection defunct/stale, retrying node batch %s: %s",
                                batch_num,
                                e,
                            )
                        else:
                            raise

            for i in range(0, len(edges), EDGE_BATCH_SIZE):
                edge_batch = edges[i : i + EDGE_BATCH_SIZE]
                batch_num = (i // EDGE_BATCH_SIZE) + 1
                for tx_attempt in range(2):
                    try:
                        _, ec = await self._execute_neo4j_transaction(
                            [],
                            edge_batch,
                            organization_id,
                            readable_collection_id=readable_collection_id,
                            neo4j_database=target_database,
                        )
                        edges_committed += ec
                        if num_edge_batches > 1:
                            logger.info(
                                "[GraphCommit] Edge batch %s/%s committed (%s edges)",
                                batch_num,
                                num_edge_batches,
                                ec,
                            )
                        break
                    except ServiceUnavailable as e:
                        if tx_attempt == 0:
                            logger.warning(
                                "[GraphCommit] Neo4j connection defunct/stale, retrying edge batch %s: %s",
                                batch_num,
                                e,
                            )
                        else:
                            raise

            artifact_nodes, artifact_edges = await self._prune_collection_graph_artifacts(
                organization_id=organization_id,
                readable_collection_id=readable_collection_id,
                neo4j_database=target_database,
            )
            if artifact_nodes or artifact_edges:
                logger.info(
                    "[GraphCommit] Removed graph artifacts for sync %s: %s stub nodes, %s attached edges",
                    sync_id,
                    artifact_nodes,
                    artifact_edges,
                )

            snapshot_complete = await self._event_snapshot_matches_sync_state(
                sync_id=sync_id,
                events=[*nodes, *edges],
                live_node_ids=self._collect_live_node_ids(nodes),
                current_state_entity_count=current_state_entity_count,
            )
            if prune_stale_graph or snapshot_complete:
                prune_node_ids = self._collect_live_node_ids(nodes) if snapshot_complete else None
                if prune_node_ids is None and current_state_node_ids is not None:
                    prune_node_ids = sorted({str(node_id) for node_id in current_state_node_ids if node_id})
                pruned_nodes, pruned_edges = await self._prune_collection_graph_to_entity_state(
                    sync_id=sync_id,
                    organization_id=organization_id,
                    readable_collection_id=readable_collection_id,
                    neo4j_database=target_database,
                    live_node_ids_override=prune_node_ids,
                    live_relation_edge_ids_override=(
                        self._collect_live_edge_ids(
                            edges,
                            readable_collection_id=readable_collection_id,
                        )
                        if snapshot_complete
                        else None
                    ),
                )
                if pruned_nodes or pruned_edges:
                    logger.info(
                        "[GraphCommit] Reconciled stale graph state for sync %s: %s nodes, %s edges",
                        sync_id,
                        pruned_nodes,
                        pruned_edges,
                    )
            else:
                logger.info(
                    "[GraphCommit] Incremental graph commit for sync %s; latest event set "
                    "is not a complete sync-state snapshot, so live graph rows were preserved.",
                    sync_id,
                )

            # Step 4: Mark PostgreSQL events only after Neo4j batches succeed.
            # Deduplication means only selected events were written; older pending
            # duplicates are marked skipped so retry/reporting stays honest.
            await self._mark_committed(sync_id, committed_event_ids)
            nodes_skipped, edges_skipped = await self._mark_skipped(sync_id, committed_event_ids)
            metadata_skipped = await self._mark_metadata_skipped(sync_id)
            try:
                from contextd.core.context_intelligence_service import (
                    context_intelligence_service,
                )

                projection = await context_intelligence_service.project_committed_graph_events(
                    sync_id=sync_id,
                    organization_id=organization_id,
                    readable_collection_id=readable_collection_id,
                    committed_event_ids=committed_event_ids,
                )
                logger.info(
                    "[GraphCommit] Context intelligence projection complete for sync %s: %s",
                    sync_id,
                    projection,
                )
            except Exception as projection_error:
                logger.error(
                    "[GraphCommit] Context intelligence projection failed for sync %s: %s",
                    sync_id,
                    projection_error,
                    exc_info=True,
                )

            duration_ms = int((utc_now_naive() - start_time).total_seconds() * 1000)

            logger.info(
                f"[GraphCommit] Phase 2 complete for sync {sync_id}: "
                f"{nodes_committed} nodes, {edges_committed} edges in {duration_ms}ms"
            )

            return CommitResult(
                success=True,
                nodes_committed=nodes_committed,
                edges_committed=edges_committed,
                nodes_skipped=nodes_skipped,
                edges_skipped=edges_skipped,
                metadata_skipped=metadata_skipped,
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = int((utc_now_naive() - start_time).total_seconds() * 1000)
            error_msg = str(e)

            logger.error(
                f"[GraphCommit] Phase 2 failed for sync {sync_id}: {error_msg}", exc_info=True
            )

            # Mark events as failed
            await self._mark_failed(sync_id, error_msg)

            return CommitResult(
                success=False,
                error=error_msg,
                duration_ms=duration_ms,
            )

    async def _get_deduplicated_nodes(self, sync_id: UUID) -> List[Dict[str, Any]]:
        """Get unique pending nodes using SQL DISTINCT ON.

        Deduplication logic:
        - Same node_id from multiple batches → keep latest (by created_at)
        - Returns only NODE events with pending status

        Args:
            sync_id: Sync ID to query

        Returns:
            List of unique node event data dictionaries
        """
        return await self._get_deduplicated_nodes_by_status(sync_id, ["pending"])

    async def _get_deduplicated_nodes_by_status(
        self,
        sync_id: UUID,
        commit_statuses: Sequence[str],
    ) -> List[Dict[str, Any]]:
        """Get unique nodes for a sync filtered by one or more commit statuses.

        This powers both the normal pending-event commit and the idempotent
        rehydration path used when a collection-scoped Neo4j database needs to
        be rebuilt from already-committed graph events.
        """
        query = text("""
            SELECT DISTINCT ON (node_id)
                id,
                sync_job_id,
                node_id,
                entity_id,
                entity_type,
                event_type,
                event_data,
                organization_id
            FROM graph_events
            WHERE sync_id = :sync_id
              AND event_type LIKE 'NODE%'
              AND commit_status IN :commit_statuses
              AND node_id IS NOT NULL
            ORDER BY node_id, created_at DESC
        """).bindparams(bindparam("commit_statuses", expanding=True))

        async with get_db_context() as db:
            result = await db.execute(
                query,
                {
                    "sync_id": str(sync_id),
                    "commit_statuses": list(commit_statuses),
                },
            )
            rows = result.fetchall()

        nodes = []
        for row in rows:
            nodes.append(
                {
                    "id": row.id,
                    "sync_job_id": row.sync_job_id,
                    "node_id": row.node_id,
                    "entity_id": row.entity_id,
                    "entity_type": row.entity_type,
                    "event_type": row.event_type,
                    "event_data": row.event_data,
                    "organization_id": row.organization_id,
                }
            )

        return nodes

    async def _get_deduplicated_edges(self, sync_id: UUID) -> List[Dict[str, Any]]:
        """Get unique pending edges using SQL DISTINCT ON.

        Deduplication logic:
        - Same (from_node, to_node, edge_type) → keep latest (by created_at)
        - Extracts values from JSONB event_data->payload

        Args:
            sync_id: Sync ID to query

        Returns:
            List of unique edge event data dictionaries
        """
        return await self._get_deduplicated_edges_by_status(sync_id, ["pending"])

    async def _get_deduplicated_edges_by_status(
        self,
        sync_id: UUID,
        commit_statuses: Sequence[str],
    ) -> List[Dict[str, Any]]:
        """Get unique edges for a sync filtered by one or more commit statuses."""
        query = text("""
            SELECT DISTINCT ON (
                event_data->'payload'->'from_node'->>'node_id',
                event_data->'payload'->'to_node'->>'node_id',
                event_data->'payload'->>'edge_type'
            )
                id,
                sync_job_id,
                entity_id,
                entity_type,
                event_type,
                event_data,
                organization_id
            FROM graph_events
            WHERE sync_id = :sync_id
              AND event_type LIKE 'EDGE%'
              AND commit_status IN :commit_statuses
            ORDER BY
                event_data->'payload'->'from_node'->>'node_id',
                event_data->'payload'->'to_node'->>'node_id',
                event_data->'payload'->>'edge_type',
                created_at DESC
        """).bindparams(bindparam("commit_statuses", expanding=True))

        async with get_db_context() as db:
            result = await db.execute(
                query,
                {
                    "sync_id": str(sync_id),
                    "commit_statuses": list(commit_statuses),
                },
            )
            rows = result.fetchall()

        edges = []
        for row in rows:
            edges.append(
                {
                    "id": row.id,
                    "sync_job_id": row.sync_job_id,
                    "entity_id": row.entity_id,
                    "entity_type": row.entity_type,
                    "event_type": row.event_type,
                    "event_data": row.event_data,
                    "organization_id": row.organization_id,
                }
            )

        return edges

    async def rehydrate_committed_sync_events(
        self,
        sync_id: UUID,
        organization_id: UUID,
        *,
        readable_collection_id: Optional[str],
    ) -> CommitResult:
        """Replay committed graph events into the collection-scoped Neo4j database.

        This does not mutate PostgreSQL graph event state. It is intentionally
        idempotent and exists for operational repair/migration cases where the
        durable event log says events were committed but the scoped Neo4j
        database is empty or missing indexes.
        """
        start_time = utc_now_naive()
        try:
            nodes = await self._get_deduplicated_nodes_by_status(sync_id, ["committed"])
            edges = await self._get_deduplicated_edges_by_status(sync_id, ["committed"])

            if not nodes and not edges:
                return CommitResult(success=True, duration_ms=0)

            target_database = await self.driver.ensure_context_database(
                organization_id,
                readable_collection_id,
            )

            nodes_committed = 0
            edges_committed = 0
            for i in range(0, len(nodes), NODE_BATCH_SIZE):
                node_batch = nodes[i : i + NODE_BATCH_SIZE]
                nc, _ = await self._execute_neo4j_transaction(
                    node_batch,
                    [],
                    organization_id,
                    readable_collection_id=readable_collection_id,
                    neo4j_database=target_database,
                )
                nodes_committed += nc

            for i in range(0, len(edges), EDGE_BATCH_SIZE):
                edge_batch = edges[i : i + EDGE_BATCH_SIZE]
                _, ec = await self._execute_neo4j_transaction(
                    [],
                    edge_batch,
                    organization_id,
                    readable_collection_id=readable_collection_id,
                    neo4j_database=target_database,
                )
                edges_committed += ec

            artifact_nodes, artifact_edges = await self._prune_collection_graph_artifacts(
                organization_id=organization_id,
                readable_collection_id=readable_collection_id,
                neo4j_database=target_database,
            )
            if artifact_nodes or artifact_edges:
                logger.info(
                    "[GraphCommit] Rehydration removed graph artifacts for sync %s: "
                    "%s stub nodes, %s attached edges",
                    sync_id,
                    artifact_nodes,
                    artifact_edges,
                )

            pruned_nodes, pruned_edges = await self._prune_collection_graph_to_entity_state(
                sync_id=sync_id,
                organization_id=organization_id,
                readable_collection_id=readable_collection_id,
                neo4j_database=target_database,
            )
            if pruned_nodes or pruned_edges:
                logger.info(
                    "[GraphCommit] Rehydration pruned stale graph state for sync %s: "
                    "%s nodes, %s edges",
                    sync_id,
                    pruned_nodes,
                    pruned_edges,
                )

            try:
                from contextd.platform.graph.fulltext_service import FulltextService

                fulltext = await FulltextService.create(
                    organization_id=organization_id,
                    readable_collection_id=readable_collection_id,
                )
                try:
                    await fulltext.ensure_fulltext_index(
                        "GraphNode",
                        [],
                        analyzer=get_graph_config().fulltext_analyzer,
                    )
                finally:
                    await fulltext.close()
            except Exception as index_error:
                logger.warning(
                    "[GraphCommit] Rehydrated Neo4j graph but could not ensure fulltext index "
                    "for %s: %s",
                    readable_collection_id,
                    index_error,
                )

            duration_ms = int((utc_now_naive() - start_time).total_seconds() * 1000)
            logger.info(
                "[GraphCommit] Rehydrated committed graph events for sync %s into %s: "
                "%s nodes, %s edges in %sms",
                sync_id,
                readable_collection_id,
                nodes_committed,
                edges_committed,
                duration_ms,
            )
            return CommitResult(
                success=True,
                nodes_committed=nodes_committed,
                edges_committed=edges_committed,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = int((utc_now_naive() - start_time).total_seconds() * 1000)
            logger.error(
                "[GraphCommit] Failed to rehydrate committed graph events for sync %s: %s",
                sync_id,
                exc,
                exc_info=True,
            )
            return CommitResult(success=False, error=str(exc), duration_ms=duration_ms)

    async def _execute_neo4j_transaction(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        organization_id: UUID,
        *,
        readable_collection_id: Optional[str] = None,
        neo4j_database: Optional[str] = None,
    ) -> Tuple[int, int]:
        """Execute one Neo4j transaction for a batch of nodes and/or edges.

        Order within transaction: nodes first, then edges.
        Full rollback on any error. Used by commit_sync_events in a loop for batching.

        Args:
            nodes: List of node event data (may be empty for edge-only batch)
            edges: List of edge event data (may be empty for node-only batch)
            organization_id: Organization ID for graph scoping
            readable_collection_id: Collection readable_id to store on nodes for schema scoping

        Returns:
            Tuple of (nodes_committed, edges_committed)
        """
        nodes_committed = 0
        edges_committed = 0

        async with self.driver.session(database=neo4j_database) as session:
            async with await session.begin_transaction() as tx:
                try:
                    # Step 1: Process ALL nodes first
                    for node_data in nodes:
                        event_data = node_data["event_data"]
                        payload = event_data.get("payload", {})
                        event_type = node_data["event_type"]

                        if event_type == "NODE_DELETE":
                            await self._delete_node(
                                tx,
                                payload,
                                organization_id,
                                readable_collection_id=readable_collection_id,
                            )
                        else:
                            await self._merge_node(
                                tx,
                                payload,
                                organization_id,
                                readable_collection_id=readable_collection_id,
                            )
                        nodes_committed += 1

                    # Step 2: Process ALL edges (nodes now guaranteed to exist)
                    for edge_data in edges:
                        event_data = edge_data["event_data"]
                        payload = event_data.get("payload", {})
                        event_type = edge_data["event_type"]

                        if event_type == "EDGE_DELETE":
                            await self._delete_edge(
                                tx,
                                payload,
                                organization_id,
                                readable_collection_id=readable_collection_id,
                            )
                            edges_committed += 1
                        else:
                            edge_written = await self._merge_edge(
                                tx,
                                payload,
                                organization_id,
                                readable_collection_id=readable_collection_id,
                            )
                            if edge_written:
                                edges_committed += 1
                            else:
                                logger.warning(
                                    "[GraphCommit] Skipped edge because one or both endpoints "
                                    "were outside the collection graph: %s -> %s (%s)",
                                    (payload.get("from_node") or {}).get("node_id"),
                                    (payload.get("to_node") or {}).get("node_id"),
                                    payload.get("edge_type"),
                                )

                    # Step 3: Commit transaction
                    await tx.commit()

                    logger.info(
                        f"[GraphCommit] Neo4j transaction committed: "
                        f"{nodes_committed} nodes, {edges_committed} edges"
                    )

                except Exception as e:
                    # Transaction auto-rolls back on exception
                    logger.error(
                        f"[GraphCommit] Neo4j transaction failed, rolling back: {e}", exc_info=True
                    )
                    raise

        return nodes_committed, edges_committed

    @staticmethod
    def _collect_event_ids(*event_groups: List[Dict[str, Any]]) -> List[UUID]:
        """Collect database event IDs selected for the Neo4j commit."""
        event_ids: List[UUID] = []
        for events in event_groups:
            for event in events:
                event_id = event.get("id")
                if event_id:
                    event_ids.append(event_id)
        return event_ids

    @staticmethod
    def _event_payload(event: Dict[str, Any]) -> Dict[str, Any]:
        """Extract a JSON event payload defensively."""
        event_data = event.get("event_data") or {}
        if isinstance(event_data, str):
            try:
                event_data = json.loads(event_data)
            except json.JSONDecodeError:
                return {}
        if not isinstance(event_data, dict):
            return {}
        payload = event_data.get("payload") or {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _collect_live_node_ids(nodes: Sequence[Dict[str, Any]]) -> List[str]:
        """Collect the live node IDs represented by a commit event set."""
        node_ids: set[str] = set()
        for node in nodes:
            payload = GraphCommitService._event_payload(node)
            node_id = payload.get("node_id") or node.get("node_id")
            if node_id:
                node_ids.add(str(node_id))
        return sorted(node_ids)

    def _collect_live_edge_ids(
        self,
        edges: Sequence[Dict[str, Any]],
        *,
        readable_collection_id: Optional[str],
    ) -> List[str]:
        """Collect stable live edge IDs represented by a commit event set."""
        edge_ids: set[str] = set()
        for edge in edges:
            payload = self._event_payload(edge)
            from_node = payload.get("from_node") or {}
            to_node = payload.get("to_node") or {}
            if not isinstance(from_node, dict) or not isinstance(to_node, dict):
                continue

            source_node_id = from_node.get("node_id")
            target_node_id = to_node.get("node_id")
            edge_type = payload.get("edge_type")
            if not source_node_id or not target_node_id or not edge_type:
                continue

            edge_ids.add(
                self._generate_edge_id(
                    str(source_node_id),
                    str(target_node_id),
                    str(edge_type),
                    readable_collection_id=readable_collection_id,
                )
            )
        return sorted(edge_ids)

    @staticmethod
    def _collect_sync_job_ids(events: Sequence[Dict[str, Any]]) -> List[UUID]:
        """Collect unique sync job IDs represented by a graph event set."""
        job_ids: set[UUID] = set()
        for event in events:
            sync_job_id = event.get("sync_job_id")
            if not sync_job_id:
                continue
            try:
                job_ids.add(sync_job_id if isinstance(sync_job_id, UUID) else UUID(str(sync_job_id)))
            except (TypeError, ValueError):
                logger.warning("[GraphCommit] Ignoring malformed sync_job_id on graph event: %s", sync_job_id)
        return sorted(job_ids, key=str)

    async def _fetch_sync_state_snapshot(
        self,
        *,
        sync_id: UUID,
        sync_job_id: Optional[UUID] = None,
    ) -> Tuple[int, List[str]]:
        """Return authoritative entity count and node IDs from sync_state."""
        if sync_job_id:
            query = text("""
                SELECT entity_count, state_data
                FROM sync_state
                WHERE sync_job_id = :sync_job_id
                ORDER BY created_at DESC
                LIMIT 1
            """)
            params = {"sync_job_id": str(sync_job_id)}
        else:
            query = text("""
                SELECT entity_count, state_data
                FROM sync_state
                WHERE sync_id = :sync_id
                ORDER BY created_at DESC
                LIMIT 1
            """)
            params = {"sync_id": str(sync_id)}

        async with get_db_context() as db:
            row = (await db.execute(query, params)).first()

        if not row:
            return 0, []

        state_data = row.state_data if isinstance(row.state_data, dict) else {}
        entity_states = state_data.get("entity_states") if isinstance(state_data, dict) else {}
        node_ids: set[str] = set()
        if isinstance(entity_states, dict):
            for type_state in entity_states.values():
                if not isinstance(type_state, dict):
                    continue
                entities = type_state.get("entities") or {}
                if isinstance(entities, dict):
                    node_ids.update(str(node_id) for node_id in entities.keys() if node_id)

        stats = state_data.get("statistics") if isinstance(state_data, dict) else {}
        stats_total = int((stats or {}).get("total_entities") or 0) if isinstance(stats, dict) else 0
        entity_count = len(node_ids) if node_ids else int(stats_total or row.entity_count or 0)
        return entity_count, sorted(node_ids)

    async def _event_snapshot_matches_sync_state(
        self,
        *,
        sync_id: UUID,
        events: Sequence[Dict[str, Any]],
        live_node_ids: Sequence[str],
        current_state_entity_count: Optional[int] = None,
    ) -> bool:
        """Return True when pending events represent the current sync-state snapshot.

        Cursor/incremental syncs may emit only changed graph events. Pruning those
        would delete healthy live graph rows. A graph event set is only safe for
        reconciliation when all events belong to one sync job and its node set
        matches that job's authoritative sync_state entity count.
        """
        job_ids = self._collect_sync_job_ids(events)
        if len(job_ids) != 1:
            return False

        if current_state_entity_count is not None:
            state_count = int(current_state_entity_count or 0)
        else:
            state_count, _ = await self._fetch_sync_state_snapshot(
                sync_id=sync_id,
                sync_job_id=job_ids[0],
            )
        live_count = len({str(node_id) for node_id in live_node_ids if node_id})
        if state_count <= 0 or live_count <= 0:
            return False
        if state_count == live_count:
            return True

        logger.info(
            "[GraphCommit] Event set for sync %s is partial: %s live node events, "
            "%s sync-state entities. Skipping graph prune.",
            sync_id,
            live_count,
            state_count,
        )
        return False

    async def _fetch_current_entity_node_ids(self, sync_id: UUID) -> List[str]:
        """Return the normalized entity IDs that currently belong to this sync."""
        query = text("""
            SELECT entity_id
            FROM entity
            WHERE sync_id = :sync_id
        """)
        async with get_db_context() as db:
            result = await db.execute(query, {"sync_id": str(sync_id)})
            return [str(row.entity_id) for row in result if row.entity_id]

    async def _fetch_current_relation_edge_ids(
        self,
        sync_id: UUID,
        *,
        readable_collection_id: str,
    ) -> List[str]:
        """Return authoritative Forge relation edge IDs from the current entity snapshot.

        Database connectors store foreign-key relationships in ``entity.relations``
        with Forge edge labels. Those relations are the current topology contract;
        older committed graph events can remain durable audit history, but their
        legacy edges should not continue to appear in the live collection graph.
        """
        query = text("""
            SELECT entity_id, relations
            FROM entity
            WHERE sync_id = :sync_id
              AND relations IS NOT NULL
              AND jsonb_typeof(relations) = 'array'
              AND jsonb_array_length(relations) > 0
        """)
        edge_ids: set[str] = set()

        async with get_db_context() as db:
            result = await db.execute(query, {"sync_id": str(sync_id)})
            rows = result.fetchall()

        for row in rows:
            source_node_id = str(row.entity_id)
            for relation in row.relations or []:
                if not isinstance(relation, dict):
                    continue
                target_node_id = relation.get("entity_id")
                relation_properties = relation.get("properties") or {}
                if not target_node_id or not isinstance(relation_properties, dict):
                    continue

                edge_type = relation_properties.get("edge_type")
                if not edge_type:
                    continue
                reverse_edge_type = relation_properties.get("reverse_edge_type") or edge_type

                edge_ids.add(
                    self._generate_edge_id(
                        source_node_id,
                        str(target_node_id),
                        str(edge_type),
                        readable_collection_id=readable_collection_id,
                    )
                )
                edge_ids.add(
                    self._generate_edge_id(
                        str(target_node_id),
                        source_node_id,
                        str(reverse_edge_type),
                        readable_collection_id=readable_collection_id,
                    )
                )

        return sorted(edge_ids)

    async def _fetch_latest_sync_job_graph_state(
        self,
        sync_id: UUID,
        *,
        readable_collection_id: Optional[str],
    ) -> Tuple[Optional[UUID], List[str], List[str]]:
        """Return live node/edge IDs from the latest completed sync job event set.

        The graph event stream is the materialization contract for ContextD graph.
        It is more reliable than the legacy normalized ``entity`` table for current
        connector runs because structured connectors now write full graph snapshots
        directly as events.
        """
        query = text("""
            WITH latest_job AS (
                SELECT id
                FROM sync_job
                WHERE sync_id = :sync_id
                  AND status = 'completed'
                ORDER BY completed_at DESC NULLS LAST, started_at DESC NULLS LAST
                LIMIT 1
            )
            SELECT latest_job.id AS sync_job_id,
                   ge.id,
                   ge.node_id,
                   ge.event_type,
                   ge.event_data
            FROM latest_job
            LEFT JOIN graph_events ge
              ON ge.sync_job_id = latest_job.id
             AND ge.commit_status IN ('pending', 'committed')
             AND ge.event_type IN ('NODE_CREATE', 'NODE_UPDATE', 'EDGE_CREATE', 'EDGE_UPDATE')
        """)

        async with get_db_context() as db:
            result = await db.execute(query, {"sync_id": str(sync_id)})
            rows = result.fetchall()

        node_events: List[Dict[str, Any]] = []
        edge_events: List[Dict[str, Any]] = []
        latest_sync_job_id: Optional[UUID] = None
        for row in rows:
            if row.sync_job_id and latest_sync_job_id is None:
                latest_sync_job_id = UUID(str(row.sync_job_id))
            if not row.id:
                continue
            event = {
                "id": row.id,
                "sync_job_id": row.sync_job_id,
                "node_id": row.node_id,
                "event_type": row.event_type,
                "event_data": row.event_data,
            }
            if str(row.event_type).startswith("NODE"):
                node_events.append(event)
            elif str(row.event_type).startswith("EDGE"):
                edge_events.append(event)

        return (
            latest_sync_job_id,
            self._collect_live_node_ids(node_events),
            self._collect_live_edge_ids(
                edge_events,
                readable_collection_id=readable_collection_id,
            ),
        )

    async def _prune_collection_graph_artifacts(
        self,
        *,
        organization_id: UUID,
        readable_collection_id: Optional[str],
        neo4j_database: Optional[str],
    ) -> Tuple[int, int]:
        """Delete invalid graph artifacts from one isolated collection graph.

        Older graph commits created placeholder endpoint nodes when an edge
        referenced a row that was outside the current source snapshot. Those
        placeholders are not valid ContextD entities, and keeping them makes
        database graph counts drift from the authoritative snapshot. This repair
        is safe for incremental syncs because it only removes nodes explicitly
        marked as stubs or nodes that never had a resolved node type.
        """
        if not readable_collection_id:
            return 0, 0

        params = {
            "organization_id": str(organization_id),
            "collection_id": readable_collection_id,
            "batch_size": 5000,
        }
        deleted_nodes = 0
        deleted_edges = 0

        while True:
            rows = await self.driver.execute_write(
                """
                MATCH (n:GraphNode {
                  organization_id: $organization_id,
                  collection_id: $collection_id
                })
                WHERE coalesce(n._stub, false) = true OR n.node_type IS NULL
                WITH n
                LIMIT $batch_size
                OPTIONAL MATCH (n)-[r:RELATES_TO]-(:GraphNode {
                  organization_id: $organization_id,
                  collection_id: $collection_id
                })
                WITH collect(DISTINCT n) AS nodes, count(DISTINCT r) AS edge_count
                UNWIND nodes AS node
                DETACH DELETE node
                RETURN count(node) AS node_count, edge_count
                """,
                params,
                database=neo4j_database,
            )
            if not rows:
                break
            row = rows[0]
            node_count = int(row.get("node_count") or 0)
            edge_count = int(row.get("edge_count") or 0)
            deleted_nodes += node_count
            deleted_edges += edge_count
            if node_count == 0:
                break

        return deleted_nodes, deleted_edges

    async def _prune_collection_graph_to_entity_state(
        self,
        *,
        sync_id: UUID,
        organization_id: UUID,
        readable_collection_id: Optional[str],
        neo4j_database: Optional[str],
        live_node_ids_override: Optional[Sequence[str]] = None,
        live_relation_edge_ids_override: Optional[Sequence[str]] = None,
    ) -> Tuple[int, int]:
        """Remove graph rows that no longer exist in the normalized source snapshot.

        Graph events are append-friendly and idempotent, but current product views
        must reflect the current source boundary. The latest sync job event set is
        the primary source of truth; the legacy normalized ``entity`` table remains
        a fallback for older connectors. This reconciliation prevents old nodes and
        links from lingering when rows disappear, source scopes narrow, or Forge
        changes generated entity and relationship labels.
        """
        if not readable_collection_id:
            return 0, 0

        artifact_nodes, artifact_edges = await self._prune_collection_graph_artifacts(
            organization_id=organization_id,
            readable_collection_id=readable_collection_id,
            neo4j_database=neo4j_database,
        )

        latest_sync_job_id: Optional[UUID] = None
        latest_node_ids: List[str] = []
        latest_relation_edge_ids: List[str] = []
        latest_snapshot_complete = False
        if live_node_ids_override is None or live_relation_edge_ids_override is None:
            latest_sync_job_id, latest_node_ids, latest_relation_edge_ids = await self._fetch_latest_sync_job_graph_state(
                sync_id,
                readable_collection_id=readable_collection_id,
            )
            if latest_sync_job_id and latest_node_ids:
                state_count, _ = await self._fetch_sync_state_snapshot(
                    sync_id=sync_id,
                    sync_job_id=latest_sync_job_id,
                )
                latest_snapshot_complete = state_count == len(set(latest_node_ids))
                if not latest_snapshot_complete:
                    logger.info(
                        "[GraphCommit] Latest graph event job for sync %s is partial: "
                        "%s node events, %s sync-state entities. Reconcile will use "
                        "sync_state entity IDs instead of pruning to the event subset.",
                        sync_id,
                        len(set(latest_node_ids)),
                        state_count,
                    )

        if live_node_ids_override is not None:
            live_node_ids = sorted({str(value) for value in live_node_ids_override if value})
        elif latest_snapshot_complete:
            live_node_ids = latest_node_ids
        else:
            _, live_node_ids = await self._fetch_sync_state_snapshot(sync_id=sync_id)
            if not live_node_ids:
                live_node_ids = await self._fetch_current_entity_node_ids(sync_id)

        if not live_node_ids:
            logger.warning(
                "[GraphCommit] Skipping graph prune for sync %s because no current "
                "graph snapshot was found.",
                sync_id,
            )
            return artifact_nodes, artifact_edges

        if live_relation_edge_ids_override is not None:
            live_relation_edge_ids = sorted({str(value) for value in live_relation_edge_ids_override if value})
            relation_snapshot_known = True
        elif latest_snapshot_complete:
            live_relation_edge_ids = latest_relation_edge_ids
            relation_snapshot_known = True
        else:
            # Without a complete graph-event snapshot we only prune nodes that
            # sync_state proves are stale. The legacy entity.relations table can
            # lag modern graph snapshots, so it must not be used to delete live
            # relationships inside the current node set.
            live_relation_edge_ids = []
            relation_snapshot_known = False

        params = {
            "organization_id": str(organization_id),
            "collection_id": readable_collection_id,
            "live_node_ids": live_node_ids,
            "live_relation_edge_ids": live_relation_edge_ids,
            "batch_size": 5000,
        }
        pruned_edges = artifact_edges
        pruned_nodes = artifact_nodes

        while True:
            edge_rows = await self.driver.execute_write(
                """
                MATCH (source:GraphNode {organization_id: $organization_id})
                      -[r:RELATES_TO]->
                      (target:GraphNode {organization_id: $organization_id})
                WHERE r.collection_id = $collection_id
                  AND source.collection_id = $collection_id
                  AND target.collection_id = $collection_id
                  AND (
                    NOT (source.node_id IN $live_node_ids)
                    OR NOT (target.node_id IN $live_node_ids)
                  )
                WITH r
                LIMIT $batch_size
                DELETE r
                RETURN count(*) AS deleted
                """,
                params,
                database=neo4j_database,
            )
            deleted = int((edge_rows[0] if edge_rows else {}).get("deleted") or 0)
            pruned_edges += deleted
            if deleted == 0:
                break

        while True:
            legacy_duplicate_rows = await self.driver.execute_write(
                """
                MATCH (source:GraphNode {
                  organization_id: $organization_id,
                  collection_id: $collection_id
                })-[r:RELATES_TO]->(target:GraphNode {
                  organization_id: $organization_id,
                  collection_id: $collection_id
                })
                WHERE r.collection_id = $collection_id
                WITH source, target, r,
                     coalesce(properties(r)['relationship_type'], r.relationship_type, type(r)) AS rel_type
                WHERE rel_type = 'RELATED_TO'
                MATCH (source)-[modern:RELATES_TO]-(target)
                WHERE elementId(modern) <> elementId(r)
                  AND modern.collection_id = $collection_id
                WITH r,
                     coalesce(properties(modern)['relationship_type'], modern.relationship_type, type(modern)) AS modern_type
                WHERE modern_type STARTS WITH 'RELATES_TO_'
                WITH DISTINCT r
                LIMIT $batch_size
                DELETE r
                RETURN count(*) AS deleted
                """,
                params,
                database=neo4j_database,
            )
            deleted = int((legacy_duplicate_rows[0] if legacy_duplicate_rows else {}).get("deleted") or 0)
            pruned_edges += deleted
            if deleted == 0:
                break

        if relation_snapshot_known:
            while True:
                relation_edge_rows = await self.driver.execute_write(
                    """
                    MATCH (source:GraphNode {organization_id: $organization_id})
                          -[r:RELATES_TO]->
                          (target:GraphNode {organization_id: $organization_id})
                    WHERE r.collection_id = $collection_id
                      AND source.collection_id = $collection_id
                      AND target.collection_id = $collection_id
                      AND source.node_id IN $live_node_ids
                      AND target.node_id IN $live_node_ids
                    WITH r, coalesce(properties(r)['relationship_type'], type(r)) AS rel_type
                    WHERE (rel_type = 'RELATED_TO' OR rel_type STARTS WITH 'RELATES_TO_')
                      AND NOT (coalesce(r.edge_id, '') IN $live_relation_edge_ids)
                    WITH r
                    LIMIT $batch_size
                    DELETE r
                    RETURN count(*) AS deleted
                    """,
                    params,
                    database=neo4j_database,
                )
                deleted = int((relation_edge_rows[0] if relation_edge_rows else {}).get("deleted") or 0)
                pruned_edges += deleted
                if deleted == 0:
                    break

        while True:
            node_rows = await self.driver.execute_write(
                """
                MATCH (n:GraphNode {
                  organization_id: $organization_id,
                  collection_id: $collection_id
                })
                WHERE NOT (n.node_id IN $live_node_ids)
                WITH n
                LIMIT $batch_size
                DETACH DELETE n
                RETURN count(*) AS deleted
                """,
                params,
                database=neo4j_database,
            )
            deleted = int((node_rows[0] if node_rows else {}).get("deleted") or 0)
            pruned_nodes += deleted
            if deleted == 0:
                break

        return pruned_nodes, pruned_edges

    async def _merge_node(
        self,
        tx,
        payload: Dict[str, Any],
        organization_id: UUID,
        *,
        readable_collection_id: Optional[str] = None,
    ) -> None:
        """MERGE node - idempotent create or update operation.

        Uses Neo4j MERGE to ensure idempotency:
        - If node exists: updates properties
        - If node doesn't exist: creates it

        Args:
            tx: Neo4j transaction
            payload: Node event payload
            organization_id: Organization ID
            readable_collection_id: Collection readable_id; stored in properties for schema scoping
        """
        node_id = payload.get("node_id")
        node_type = payload.get("node_type")
        properties = dict(payload.get("node_properties", {}))

        # Store collection on node so schema RAG can scope by collection (not connector)
        if readable_collection_id:
            properties["collection_id"] = readable_collection_id

        # Ensure node_type is never None (fallback to "Unknown" or infer from properties)
        if not node_type:
            node_type = properties.get("entity_type") or "Unknown"

        fulltext_properties = NodeQueryBuilder.extract_fulltext_properties(properties)

        identity = "{node_id: $node_id, organization_id: $organization_id}"
        if readable_collection_id:
            identity = "{node_id: $node_id, organization_id: $organization_id, collection_id: $collection_id}"

        query = f"""
            MERGE (n:GraphNode {identity})
            ON CREATE SET
                n.node_type = $node_type,
                n.properties = $properties,
                n.collection_id = $collection_id,
                n.created_at = datetime(),
                n.updated_at = datetime(),
                n._stub = false
            ON MATCH SET
                n.node_type = $node_type,
                n.properties = $properties,
                n.collection_id = $collection_id,
                n.updated_at = datetime(),
                n._stub = false
            WITH n
            SET n += $fulltext_properties
        """

        await tx.run(
            query,
            {
                "node_id": node_id,
                "node_type": node_type,
                "properties": json.dumps(properties, default=str),
                "fulltext_properties": fulltext_properties,
                "organization_id": str(organization_id),
                "collection_id": readable_collection_id,
            },
        )

    async def _delete_node(
        self,
        tx,
        payload: Dict[str, Any],
        organization_id: UUID,
        *,
        readable_collection_id: Optional[str] = None,
    ) -> None:
        """Delete node from graph.

        Args:
            tx: Neo4j transaction
            payload: Node event payload
            organization_id: Organization ID
        """
        node_id = payload.get("node_id")

        if readable_collection_id:
            query = """
                MATCH (n:GraphNode {
                  node_id: $node_id,
                  organization_id: $organization_id,
                  collection_id: $collection_id
                })
                DETACH DELETE n
            """
        else:
            query = """
                MATCH (n:GraphNode {node_id: $node_id, organization_id: $organization_id})
                DETACH DELETE n
            """

        await tx.run(
            query,
            {
                "node_id": node_id,
                "organization_id": str(organization_id),
                "collection_id": readable_collection_id,
            },
        )

    async def _merge_edge(
        self,
        tx,
        payload: Dict[str, Any],
        organization_id: UUID,
        *,
        readable_collection_id: Optional[str] = None,
    ) -> bool:
        """MERGE edge - idempotent create or update operation.

        Uses Neo4j MERGE to ensure idempotency:
        - If edge exists: updates properties
        - If edge doesn't exist: creates it

        Source and target nodes must already exist in the same collection graph.
        Missing endpoints are skipped instead of creating stub nodes, because
        stubs make graph counts diverge from the authoritative sync snapshot.

        Args:
            tx: Neo4j transaction
            payload: Edge event payload
            organization_id: Organization ID

        Returns:
            True when a relationship was written, False when either endpoint was
            absent from the scoped graph.
        """
        from_node = payload.get("from_node", {})
        to_node = payload.get("to_node", {})
        edge_type = payload.get("edge_type")
        properties = dict(payload.get("edge_properties", {}) or {})
        if readable_collection_id:
            properties["collection_id"] = readable_collection_id

        source_node_id = from_node.get("node_id")
        target_node_id = to_node.get("node_id")

        # Generate stable edge ID
        edge_id = self._generate_edge_id(
            source_node_id,
            target_node_id,
            edge_type,
            readable_collection_id=readable_collection_id,
        )

        if readable_collection_id:
            source_identity = (
                "{node_id: $source_node_id, organization_id: $organization_id, "
                "collection_id: $collection_id}"
            )
            target_identity = (
                "{node_id: $target_node_id, organization_id: $organization_id, "
                "collection_id: $collection_id}"
            )
        else:
            source_identity = "{node_id: $source_node_id, organization_id: $organization_id}"
            target_identity = "{node_id: $target_node_id, organization_id: $organization_id}"

        query = f"""
            MATCH (source:GraphNode {source_identity})
            MATCH (target:GraphNode {target_identity})
            MERGE (source)-[r:RELATES_TO {{edge_id: $edge_id}}]->(target)
            ON CREATE SET
                r.relationship_type = $relationship_type,
                r.properties = $properties,
                r.organization_id = $organization_id,
                r.collection_id = $collection_id,
                r.created_at = datetime(),
                r.updated_at = datetime()
            ON MATCH SET
                r.relationship_type = $relationship_type,
                r.properties = $properties,
                r.collection_id = $collection_id,
                r.updated_at = datetime()
            RETURN count(r) AS committed
        """

        result = await tx.run(
            query,
            {
                "source_node_id": source_node_id,
                "target_node_id": target_node_id,
                "edge_id": edge_id,
                "relationship_type": edge_type,
                "properties": json.dumps(properties, default=str),
                "organization_id": str(organization_id),
                "collection_id": readable_collection_id,
            },
        )
        rows = await result.data()
        return bool(rows and int(rows[0].get("committed") or 0) > 0)

    async def _delete_edge(
        self,
        tx,
        payload: Dict[str, Any],
        organization_id: UUID,
        *,
        readable_collection_id: Optional[str] = None,
    ) -> None:
        """Delete edge from graph.

        Args:
            tx: Neo4j transaction
            payload: Edge event payload
            organization_id: Organization ID
        """
        from_node = payload.get("from_node", {})
        to_node = payload.get("to_node", {})
        edge_type = payload.get("edge_type")

        source_node_id = from_node.get("node_id")
        target_node_id = to_node.get("node_id")
        edge_id = self._generate_edge_id(
            source_node_id,
            target_node_id,
            edge_type,
            readable_collection_id=readable_collection_id,
        )

        if readable_collection_id:
            query = """
                MATCH (source:GraphNode {
                  node_id: $source_node_id,
                  organization_id: $organization_id,
                  collection_id: $collection_id
                })-[r:RELATES_TO {edge_id: $edge_id}]->
                (target:GraphNode {
                  node_id: $target_node_id,
                  organization_id: $organization_id,
                  collection_id: $collection_id
                })
                DELETE r
            """
        else:
            query = """
                MATCH (source:GraphNode {node_id: $source_node_id, organization_id: $organization_id})
                      -[r:RELATES_TO {edge_id: $edge_id}]->
                      (target:GraphNode {node_id: $target_node_id, organization_id: $organization_id})
                DELETE r
            """

        await tx.run(
            query,
            {
                "source_node_id": source_node_id,
                "target_node_id": target_node_id,
                "edge_id": edge_id,
                "organization_id": str(organization_id),
                "collection_id": readable_collection_id,
            },
        )

    def _generate_edge_id(
        self,
        source_node_id: str,
        target_node_id: str,
        relationship_type: str,
        *,
        readable_collection_id: Optional[str] = None,
    ) -> str:
        """Generate a stable edge ID.

        Uses a deterministic hash of the nodes and relationship type.

        Args:
            source_node_id: Source node ID
            target_node_id: Target node ID
            relationship_type: Relationship type

        Returns:
            Edge ID string
        """
        import hashlib

        if readable_collection_id:
            hash_input = (
                f"{readable_collection_id}|{source_node_id}|{relationship_type}|{target_node_id}"
            )
        else:
            hash_input = f"{source_node_id}|{relationship_type}|{target_node_id}"
        edge_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16]
        return f"edge_{edge_hash}"

    async def _resolve_readable_collection_id(
        self,
        sync_id: UUID,
        organization_id: UUID,
    ) -> Optional[str]:
        """Resolve collection scope from the source connection when callers omit it."""
        query = text("""
            SELECT readable_collection_id
            FROM source_connection
            WHERE sync_id = :sync_id
              AND organization_id = :organization_id
              AND readable_collection_id IS NOT NULL
            LIMIT 1
        """)
        async with get_db_context() as db:
            result = await db.execute(
                query,
                {
                    "sync_id": str(sync_id),
                    "organization_id": str(organization_id),
                },
            )
            value = result.scalar_one_or_none()
            return str(value) if value else None

    async def _mark_committed(
        self,
        sync_id: UUID,
        event_ids: Optional[Sequence[UUID]] = None,
    ) -> int:
        """Mark committed events in PostgreSQL.

        Args:
            sync_id: Sync ID
            event_ids: Specific event IDs written to Neo4j. When omitted, all pending
                events are marked committed for compatibility with existing admin callers.

        Returns:
            Number of events marked as committed
        """
        if event_ids is not None and not event_ids:
            return 0

        if event_ids is None:
            query = text("""
                UPDATE graph_events
                SET commit_status = 'committed',
                    committed_at = NOW()
                WHERE sync_id = :sync_id
                  AND commit_status = 'pending'
            """)
            params = {"sync_id": str(sync_id)}
        else:
            query = text("""
                UPDATE graph_events
                SET commit_status = 'committed',
                    committed_at = NOW()
                WHERE sync_id = :sync_id
                  AND commit_status = 'pending'
                  AND id IN :event_ids
            """).bindparams(bindparam("event_ids", expanding=True))
            params = {"sync_id": str(sync_id), "event_ids": tuple(event_ids)}

        async with get_db_context() as db:
            result = await db.execute(query, params)
            await db.commit()
            return result.rowcount

    async def _mark_skipped(
        self,
        sync_id: UUID,
        committed_event_ids: Sequence[UUID],
    ) -> Tuple[int, int]:
        """Mark deduplicated-away pending events as skipped.

        Args:
            sync_id: Sync ID
            committed_event_ids: Event IDs that were selected and written to Neo4j

        Returns:
            Tuple of skipped node count and skipped edge count
        """
        if not committed_event_ids:
            return 0, 0

        base_params = {
            "sync_id": str(sync_id),
            "event_ids": tuple(committed_event_ids),
            "error": "Superseded by a newer graph event in the same sync",
        }
        query_template = """
            UPDATE graph_events
            SET commit_status = 'skipped',
                commit_error = :error
            WHERE sync_id = :sync_id
              AND commit_status = 'pending'
              AND event_type LIKE :event_type
              AND id NOT IN :event_ids
        """
        query = text(query_template).bindparams(bindparam("event_ids", expanding=True))

        async with get_db_context() as db:
            node_result = await db.execute(query, {**base_params, "event_type": "NODE%"})
            edge_result = await db.execute(query, {**base_params, "event_type": "EDGE%"})
            await db.commit()
            return node_result.rowcount, edge_result.rowcount

    async def _mark_metadata_skipped(self, sync_id: UUID) -> int:
        """Mark metadata events skipped because they have no Neo4j write step.

        Metadata events are retained in PostgreSQL for UI/debug context. The
        graph commit service writes only node and edge mutations to Neo4j.
        """
        query = text("""
            UPDATE graph_events
            SET commit_status = 'skipped',
                commit_error = :error
            WHERE sync_id = :sync_id
              AND commit_status = 'pending'
              AND event_type = 'METADATA_UPDATE'
        """)

        async with get_db_context() as db:
            result = await db.execute(
                query,
                {
                    "sync_id": str(sync_id),
                    "error": "Metadata events are retained in Postgres and do not require Neo4j commit",
                },
            )
            await db.commit()
            return result.rowcount

    async def _mark_failed(self, sync_id: UUID, error: str) -> int:
        """Mark all pending events as failed in PostgreSQL.

        Args:
            sync_id: Sync ID
            error: Error message

        Returns:
            Number of events marked as failed
        """
        query = text("""
            UPDATE graph_events
            SET commit_status = 'failed',
                commit_error = :error
            WHERE sync_id = :sync_id
              AND commit_status = 'pending'
        """)

        async with get_db_context() as db:
            result = await db.execute(
                query,
                {
                    "sync_id": str(sync_id),
                    "error": error[:1000] if error else None,  # Truncate long errors
                },
            )
            await db.commit()
            return result.rowcount

    async def retry_failed_sync(self, sync_id: UUID, organization_id: UUID) -> CommitResult:
        """Retry committing failed events for a sync.

        Resets failed events to pending and attempts commit again.

        Args:
            sync_id: Sync ID
            organization_id: Organization ID

        Returns:
            CommitResult with retry outcome
        """
        # Reset failed events to pending
        reset_query = text("""
            UPDATE graph_events
            SET commit_status = 'pending',
                commit_error = NULL
            WHERE sync_id = :sync_id
              AND commit_status = 'failed'
        """)

        async with get_db_context() as db:
            await db.execute(reset_query, {"sync_id": str(sync_id)})
            await db.commit()

        # Attempt commit again
        return await self.commit_sync_events(sync_id, organization_id)
