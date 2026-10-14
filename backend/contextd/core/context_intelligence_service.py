"""ContextD native temporal, lineage, decision, and drift service."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any, Iterable, Mapping, Optional, Sequence
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud
from contextd.api.context import ApiContext
from contextd.core.datetime_utils import utc_now_naive
from contextd.core.logging import LoggerConfigurator
from contextd.models.collection import Collection
from contextd.models.context_forge_mapping import ContextForgeMappingArtifact
from contextd.models.context_intelligence import (
    ContextDecision,
    ContextDriftSignal,
    ContextLineageEdge,
    ContextQueryDecisionTrace,
    ContextTemporalFact,
)
from contextd.models.graph_event import GraphEvent
from contextd.models.source_connection import SourceConnection
from contextd.db.session import get_db_context

logger = LoggerConfigurator.configure_logger(__name__)

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

CONTEXT_TOOL_KEYS = ("search", "graph", "temporal", "core", "cohort", "decision")
CONTEXT_TOOL_PURPOSES = {
    "search": "Seed the packet with deterministic hybrid search and RRF.",
    "graph": "Expand seed matches into a linked ContextD neighborhood.",
    "temporal": "Attach current bitemporal facts and cursor-aware state.",
    "core": "Attach the selected database core summary and source shape.",
    "cohort": "Attach cohort scope; defaults to all entities when no cohort is selected.",
    "decision": "Attach query audit and first-class Decision lineage.",
}


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def _clean_text(value: Any, fallback: str = "") -> str:
    if value in (None, ""):
        return fallback
    return str(value)


def _lower_blob(*values: Any) -> str:
    return " ".join(str(value or "") for value in values).lower()


def _listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _source_config(source_connection: SourceConnection | None) -> dict[str, Any]:
    return dict(getattr(source_connection, "config_fields", None) or {})


def _cursor_field(source_connection: SourceConnection | None) -> Optional[str]:
    config = _source_config(source_connection)
    for key in ("cursor_field", "cursor", "incremental_cursor", "updated_at_field"):
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            return value
    schedule = config.get("schedule") if isinstance(config.get("schedule"), Mapping) else {}
    value = schedule.get("cursor_field") if schedule else None
    return value if isinstance(value, str) and value.strip() else None


class ContextIntelligenceService:
    """Projection and read service for ContextD inspection primitives."""

    async def project_committed_graph_events(
        self,
        *,
        sync_id: UUID,
        organization_id: UUID,
        readable_collection_id: Optional[str] = None,
        committed_event_ids: Optional[Sequence[UUID]] = None,
    ) -> dict[str, int]:
        """Project committed graph events into native temporal/lineage/decision rows."""
        if committed_event_ids is not None and not committed_event_ids:
            return {"events": 0, "facts": 0, "lineage": 0, "decisions": 0}

        async with get_db_context() as db:
            result = await self.project_committed_graph_events_in_session(
                db,
                sync_id=sync_id,
                organization_id=organization_id,
                readable_collection_id=readable_collection_id,
                committed_event_ids=committed_event_ids,
            )
            await db.commit()
            return result

    async def project_committed_graph_events_in_session(
        self,
        db: AsyncSession,
        *,
        sync_id: UUID,
        organization_id: UUID,
        readable_collection_id: Optional[str] = None,
        committed_event_ids: Optional[Sequence[UUID]] = None,
    ) -> dict[str, int]:
        """Session-bound variant used by endpoints and sync commit hooks."""
        source_connection = await self._get_source_by_sync(db, sync_id, organization_id)
        collection_id = readable_collection_id or getattr(source_connection, "readable_collection_id", None)
        if not collection_id:
            return {"events": 0, "facts": 0, "lineage": 0, "decisions": 0}

        stmt = (
            select(GraphEvent)
            .where(GraphEvent.organization_id == organization_id)
            .where(GraphEvent.sync_id == sync_id)
            .where(GraphEvent.commit_status == "committed")
            .order_by(GraphEvent.created_at.asc())
        )
        if committed_event_ids is not None:
            stmt = stmt.where(GraphEvent.id.in_(list(committed_event_ids)))
        result = await db.execute(stmt)
        events = list(result.scalars().all())
        if not events:
            return {"events": 0, "facts": 0, "lineage": 0, "decisions": 0}

        event_ids = [event.id for event in events]
        for model in (ContextTemporalFact, ContextLineageEdge, ContextDecision):
            await db.execute(delete(model).where(model.graph_event_id.in_(event_ids)))

        counters = {"events": len(events), "facts": 0, "lineage": 0, "decisions": 0}
        for event in events:
            result_counts = await self._project_graph_event(
                db,
                event=event,
                collection_id=collection_id,
                source_connection=source_connection,
            )
            for key, value in result_counts.items():
                counters[key] = counters.get(key, 0) + value

        if source_connection:
            await self._supersede_shadowed_generic_relationship_facts(
                db,
                organization_id=organization_id,
                collection_id=collection_id,
                source_connection_id=source_connection.id,
            )
            await self.sync_source_drift_signals(db, source_connection=source_connection)

        await db.flush()
        return counters

    async def ensure_collection_projection(
        self,
        db: AsyncSession,
        *,
        collection: Collection,
        ctx: ApiContext,
    ) -> None:
        """Backfill projection for existing committed graph events when a view first opens."""
        source_result = await db.execute(
            select(SourceConnection)
            .where(SourceConnection.organization_id == ctx.organization.id)
            .where(SourceConnection.readable_collection_id == collection.readable_id)
        )
        for source_connection in source_result.scalars().all():
            if not source_connection.sync_id:
                continue
            existing = await db.execute(
                select(func.count(ContextTemporalFact.id))
                .where(ContextTemporalFact.organization_id == ctx.organization.id)
                .where(ContextTemporalFact.collection_readable_id == collection.readable_id)
                .where(ContextTemporalFact.source_connection_id == source_connection.id)
            )
            if int(existing.scalar() or 0) > 0:
                await self._supersede_shadowed_generic_relationship_facts(
                    db,
                    organization_id=ctx.organization.id,
                    collection_id=collection.readable_id,
                    source_connection_id=source_connection.id,
                )
                await self.sync_source_drift_signals(db, source_connection=source_connection)
                continue
            await self.project_committed_graph_events_in_session(
                db,
                sync_id=source_connection.sync_id,
                organization_id=ctx.organization.id,
                readable_collection_id=collection.readable_id,
            )

    async def _supersede_shadowed_generic_relationship_facts(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        collection_id: str,
        source_connection_id: UUID | None,
    ) -> int:
        """Retire generic relationship facts once Forge emits typed edges.

        Database connectors first emitted broad ``RELATED_TO`` edges as a safe
        relationship fallback. Forge now materializes typed ``RELATES_TO_*``
        edges for the same node pairs, and the live ContextD graph prunes the
        generic aliases. Temporal facts should follow that contract so current
        counts do not double-count a relationship that no longer exists in the
        graph.
        """
        now = utc_now_naive()
        result = await db.execute(
            text(
                """
                UPDATE context_temporal_fact AS generic
                SET status = 'superseded',
                    invalid_at = :now,
                    transaction_expired_at = :now
                WHERE generic.organization_id = :organization_id
                  AND generic.collection_readable_id = :collection_id
                  AND generic.primitive_type = 'relationship'
                  AND generic.predicate = 'RELATED_TO'
                  AND generic.status = 'current'
                  AND (
                    CAST(:source_connection_id AS uuid) IS NULL
                    OR generic.source_connection_id = CAST(:source_connection_id AS uuid)
                  )
                  AND EXISTS (
                    SELECT 1
                    FROM context_temporal_fact AS typed
                    WHERE typed.organization_id = generic.organization_id
                      AND typed.collection_readable_id = generic.collection_readable_id
                      AND typed.source_connection_id IS NOT DISTINCT FROM generic.source_connection_id
                      AND typed.primitive_type = 'relationship'
                      AND typed.status = 'current'
                      AND typed.predicate <> 'RELATED_TO'
                      AND typed.subject_node_id = generic.subject_node_id
                      AND typed.object_value->>'target_node_id' = generic.object_value->>'target_node_id'
                  )
                """
            ),
            {
                "now": now,
                "organization_id": str(organization_id),
                "collection_id": collection_id,
                "source_connection_id": str(source_connection_id) if source_connection_id else None,
            },
        )
        return int(result.rowcount or 0)

    async def get_database_summary(
        self,
        db: AsyncSession,
        *,
        readable_id: str,
        ctx: ApiContext,
        ensure_projection: bool = True,
    ) -> dict[str, Any]:
        """Return database-scoped temporal, lineage, decision, and drift summary."""
        collection = await crud.collection.get_by_readable_id(db, readable_id=readable_id, ctx=ctx)
        if not collection:
            raise HTTPException(status_code=404, detail="Context database not found")

        if ensure_projection:
            await self.ensure_collection_projection(db, collection=collection, ctx=ctx)

        sources_result = await db.execute(
            select(SourceConnection)
            .where(SourceConnection.organization_id == ctx.organization.id)
            .where(SourceConnection.readable_collection_id == collection.readable_id)
            .order_by(SourceConnection.created_at.desc())
        )
        sources = list(sources_result.scalars().all())
        for source in sources:
            await self.sync_source_drift_signals(db, source_connection=source)
        await db.flush()

        temporal_current = await self._count(
            db,
            ContextTemporalFact,
            ctx.organization.id,
            collection.readable_id,
            ContextTemporalFact.status == "current",
        )
        temporal_superseded = await self._count(
            db,
            ContextTemporalFact,
            ctx.organization.id,
            collection.readable_id,
            ContextTemporalFact.status == "superseded",
        )
        lineage_count = await self._count(
            db,
            ContextLineageEdge,
            ctx.organization.id,
            collection.readable_id,
            ContextLineageEdge.status == "current",
        )
        decision_count = await self._count(
            db, ContextDecision, ctx.organization.id, collection.readable_id
        )
        active_drift_count = await self._count(
            db,
            ContextDriftSignal,
            ctx.organization.id,
            collection.readable_id,
            ContextDriftSignal.status == "active",
            ContextDriftSignal.severity != "clean",
        )
        query_trace_count = await self._count(
            db, ContextQueryDecisionTrace, ctx.organization.id, collection.readable_id
        )

        latest_facts = await self._latest_temporal_facts(
            db, ctx.organization.id, collection.readable_id
        )
        latest_lineage = await self._latest_lineage_edges(
            db, ctx.organization.id, collection.readable_id
        )
        latest_decisions = await self._latest_decisions(
            db, ctx.organization.id, collection.readable_id
        )
        latest_drifts = await self._latest_drift_signals(
            db, ctx.organization.id, collection.readable_id
        )
        latest_traces = await self._latest_query_traces(
            db, ctx.organization.id, collection.readable_id
        )

        source_payloads = [self._source_summary(source) for source in sources]
        worst_drift = self._worst_drift(latest_drifts, source_payloads)

        return {
            "collection_id": str(collection.id),
            "readable_id": collection.readable_id,
            "name": collection.name,
            "generated_at": utc_now_naive().isoformat(),
            "totals": {
                "temporal_facts": temporal_current,
                "superseded_facts": temporal_superseded,
                "lineage_edges": lineage_count,
                "decisions": decision_count,
                "active_drift": active_drift_count,
                "query_traces": query_trace_count,
            },
            "temporal": {
                "status": "current" if temporal_current else "not_indexed",
                "current_facts": temporal_current,
                "superseded_facts": temporal_superseded,
                "coverage": self._temporal_coverage_label(temporal_current, temporal_superseded),
                "recent_changes": latest_facts,
                "as_of": utc_now_naive().isoformat(),
            },
            "lineage": {
                "status": "available" if lineage_count else "empty",
                "edge_count": lineage_count,
                "recent_edges": latest_lineage,
            },
            "decisions": {
                "status": "available" if decision_count else "empty",
                "count": decision_count,
                "recent": latest_decisions,
            },
            "drift": {
                "status": worst_drift["status"],
                "severity": worst_drift["severity"],
                "active_count": active_drift_count,
                "signals": latest_drifts,
            },
            "query_traces": latest_traces,
            "sources": source_payloads,
        }

    async def detect_database_drift(
        self,
        db: AsyncSession,
        *,
        readable_id: str,
        ctx: ApiContext,
    ) -> dict[str, Any]:
        """Evaluate and persist native drift signals for a database."""
        collection = await crud.collection.get_by_readable_id(db, readable_id=readable_id, ctx=ctx)
        if not collection:
            raise HTTPException(status_code=404, detail="Context database not found")

        sources_result = await db.execute(
            select(SourceConnection)
            .where(SourceConnection.organization_id == ctx.organization.id)
            .where(SourceConnection.readable_collection_id == collection.readable_id)
        )
        for source in sources_result.scalars().all():
            await self.sync_source_drift_signals(db, source_connection=source)
        await db.flush()
        return await self.get_database_summary(
            db, readable_id=readable_id, ctx=ctx, ensure_projection=False
        )

    async def record_query_feedback(
        self,
        db: AsyncSession,
        *,
        readable_id: str,
        ctx: ApiContext,
        rating: int,
        query_id: Optional[str] = None,
        comment: Optional[str] = None,
        retrieved_node_ids: Optional[Sequence[str]] = None,
        retrieved_edge_ids: Optional[Sequence[str]] = None,
    ) -> dict[str, Any]:
        """Persist user feedback as native ranking memory for retrieved ContextD facts."""
        collection = await crud.collection.get_by_readable_id(db, readable_id=readable_id, ctx=ctx)
        if not collection:
            raise HTTPException(status_code=404, detail="Context database not found")

        clean_query_id = _clean_text(query_id).strip() or None
        trace = await self._query_trace(
            db,
            organization_id=ctx.organization.id,
            collection_id=collection.readable_id,
            query_id=clean_query_id,
        )
        if clean_query_id and trace is None:
            raise HTTPException(status_code=404, detail="Query trace not found")

        node_ids = self._unique_strings(retrieved_node_ids)
        edge_ids = self._unique_strings(retrieved_edge_ids)
        if trace:
            node_ids = node_ids or self._unique_strings(trace.retrieved_node_ids)
            edge_ids = edge_ids or self._unique_strings(trace.retrieved_edge_ids)

        target_weight = self._feedback_target_weight(rating)
        alpha = 0.10
        facts = await self._feedback_facts(
            db,
            organization_id=ctx.organization.id,
            collection_id=collection.readable_id,
            node_ids=node_ids,
            edge_ids=edge_ids,
        )
        previous_weights = [float(item.feedback_weight or 1.0) for item in facts]
        now = utc_now_naive()
        for fact in facts:
            fact.feedback_weight = self._feedback_ema_weight(
                fact.feedback_weight,
                target_weight=target_weight,
                alpha=alpha,
            )
            fact.modified_at = now
            if ctx.has_user_context:
                fact.modified_by_email = ctx.tracking_email
            fact.provenance = {
                **(fact.provenance or {}),
                "feedback": {
                    "query_id": clean_query_id,
                    "last_rating": rating,
                    "target_weight": target_weight,
                    "alpha": alpha,
                    "updated_at": now.isoformat(),
                },
            }

        trace_updated = False
        if trace:
            trace.decision_tree = self._decision_tree_with_feedback(
                trace.decision_tree or {},
                rating=rating,
                target_weight=target_weight,
                alpha=alpha,
                updated_fact_count=len(facts),
                comment=comment,
                updated_at=now,
            )
            trace.modified_at = now
            if ctx.has_user_context:
                trace.modified_by_email = ctx.tracking_email
            trace_updated = True

        await db.flush()
        new_weights = [float(item.feedback_weight or 1.0) for item in facts]
        return {
            "query_id": clean_query_id or getattr(trace, "query_id", None),
            "rating": rating,
            "target_weight": target_weight,
            "alpha": alpha,
            "updated_facts": len(facts),
            "previous_average_weight": round(sum(previous_weights) / len(previous_weights), 4)
            if previous_weights
            else None,
            "new_average_weight": round(sum(new_weights) / len(new_weights), 4)
            if new_weights
            else None,
            "trace_updated": trace_updated,
        }

    async def assemble_query_intelligence(
        self,
        db: AsyncSession,
        *,
        collection: Collection,
        request_message: str,
        recipe: str,
        path_used: str,
        traversal_result: Any,
        search_results: list[dict[str, Any]],
        context_metadata: dict[str, Any],
        ctx: ApiContext,
        latency_ms: Optional[int] = None,
        context_tools: Optional[Sequence[str]] = None,
    ) -> dict[str, Any]:
        """Build and persist the context assembly audit fields for a query response."""
        await self.ensure_collection_projection(db, collection=collection, ctx=ctx)

        active_context_tools = self._normalize_context_tools(context_tools)
        retrieved_node_ids = self._retrieved_node_ids(traversal_result, search_results)
        retrieved_edge_ids = self._retrieved_edge_ids(traversal_result)
        query_id = f"qry_{uuid4().hex[:12]}"
        temporal_context = await self._query_temporal_context(
            db,
            organization_id=ctx.organization.id,
            collection_id=collection.readable_id,
            node_ids=retrieved_node_ids,
        )
        lineage_context = await self._query_lineage_context(
            db,
            organization_id=ctx.organization.id,
            collection_id=collection.readable_id,
            node_ids=retrieved_node_ids,
        )
        decision_history = await self._query_decision_history(
            db,
            organization_id=ctx.organization.id,
            collection_id=collection.readable_id,
            node_ids=retrieved_node_ids,
            query=request_message,
        )
        summary = await self.detect_database_drift(
            db, readable_id=collection.readable_id, ctx=ctx
        )
        drift_context = summary["drift"]
        tool_context = self._build_tool_context(
            collection=collection,
            context_tools=active_context_tools,
            recipe=recipe,
            path_used=path_used,
            metadata=context_metadata,
            temporal_context=temporal_context,
            lineage_context=lineage_context,
            decision_history=decision_history,
            drift_context=drift_context,
            retrieved_node_ids=retrieved_node_ids,
            retrieved_edge_ids=retrieved_edge_ids,
        )
        decision_tree = self._build_decision_tree(
            query=request_message,
            recipe=recipe,
            path_used=path_used,
            metadata=context_metadata,
            temporal_context=temporal_context,
            lineage_context=lineage_context,
            decision_history=decision_history,
            drift_context=drift_context,
            tool_context=tool_context,
            context_tools=active_context_tools,
            retrieved_node_ids=retrieved_node_ids,
            retrieved_edge_ids=retrieved_edge_ids,
            query_id=query_id,
            latency_ms=latency_ms,
        )
        trace = ContextQueryDecisionTrace(
            organization_id=ctx.organization.id,
            collection_readable_id=collection.readable_id,
            query_id=query_id,
            query_text=request_message,
            recipe=recipe,
            path_used=path_used,
            temporal_context=temporal_context,
            lineage_context=lineage_context,
            decision_history=decision_history,
            drift_context=drift_context,
            decision_tree=decision_tree,
            retrieved_node_ids=retrieved_node_ids[:250],
            retrieved_edge_ids=retrieved_edge_ids[:250],
            token_estimate=int(context_metadata.get("token_estimate") or 0),
            latency_ms=latency_ms,
        )
        if ctx.has_user_context:
            trace.created_by_email = ctx.tracking_email
            trace.modified_by_email = ctx.tracking_email
        db.add(trace)
        await db.flush()

        metrics = decision_tree.get("metrics") or {}
        return {
            "query_id": query_id,
            "temporal_context": temporal_context,
            "lineage_context": lineage_context,
            "decision_history": decision_history,
            "drift_context": drift_context,
            "tool_context": tool_context,
            "decision_tree": decision_tree,
            "latency_ms": latency_ms,
            "decision_audit_count": int(metrics.get("decisions") or len(decision_history) + 1),
            "native_decision_count": int(metrics.get("native_decisions") or len(decision_history)),
            "query_trace_count": int(metrics.get("query_traces") or 1),
        }

    async def sync_source_drift_signals(
        self,
        db: AsyncSession,
        *,
        source_connection: SourceConnection,
    ) -> None:
        """Mirror source config/Forge drift metadata into native drift-signal rows."""
        if not source_connection.readable_collection_id:
            return
        config = _source_config(source_connection)
        drift = dict(config.get("drift") or {})
        active_artifact = await self._latest_mapping_artifact(db, source_connection)

        if drift:
            config_changed = bool((drift.get("config") or {}).get("changed"))
            schema = drift.get("schema") or {}
            schema_changed = bool(schema.get("changed"))
            severity = _clean_text(drift.get("severity"), "clean")
            await self._upsert_or_resolve_drift_signal(
                db,
                source_connection=source_connection,
                mapping_artifact=active_artifact,
                drift_type="config",
                severity=severity if config_changed else "clean",
                summary="Source connection configuration changed"
                if config_changed
                else "Source connection configuration matches baseline",
                expected={"hash": (drift.get("config") or {}).get("baseline_hash")},
                actual={"hash": (drift.get("config") or {}).get("current_hash")},
                details=drift,
                before=(drift.get("config") or {}).get("baseline_hash"),
                after=(drift.get("config") or {}).get("current_hash"),
            )
            await self._upsert_or_resolve_drift_signal(
                db,
                source_connection=source_connection,
                mapping_artifact=active_artifact,
                drift_type="schema",
                severity=severity if schema_changed else "clean",
                summary=self._schema_drift_summary(schema)
                if schema_changed
                else "Source schema matches active baseline",
                expected={"hash": schema.get("baseline_hash"), "source": schema.get("baseline_source")},
                actual={"hash": schema.get("current_hash"), "source": schema.get("current_source")},
                details=schema,
                before=schema.get("baseline_hash"),
                after=schema.get("current_hash"),
            )

        cursor = _cursor_field(source_connection)
        sync_checkpoint = (drift.get("sync_checkpoint") or {}) if drift else {}
        cursor_saved = bool(sync_checkpoint.get("cursor_saved"))
        cursor_severity = "clean" if (cursor and cursor_saved) or not cursor else "warning"
        await self._upsert_or_resolve_drift_signal(
            db,
            source_connection=source_connection,
            mapping_artifact=active_artifact,
            drift_type="cursor",
            severity=cursor_severity,
            summary="Temporal cursor checkpoint has not been observed yet"
            if cursor_severity != "clean"
            else "Temporal cursor checkpoint is present",
            expected={"cursor_field": cursor},
            actual={"cursor_saved": cursor_saved, "checkpoint": sync_checkpoint},
            details=sync_checkpoint,
            before=cursor or None,
            after=str(cursor_saved),
        )

        if active_artifact:
            artifact_hash = ((active_artifact.schema_fingerprint or {}).get("hash"))
            current_hash = (((drift.get("current") or {}).get("schema") or {}).get("hash"))
            mapping_changed = bool(artifact_hash and current_hash and artifact_hash != current_hash)
            await self._upsert_or_resolve_drift_signal(
                db,
                source_connection=source_connection,
                mapping_artifact=active_artifact,
                drift_type="mapping",
                severity="warning" if mapping_changed else "clean",
                summary="Active Forge mapping fingerprint differs from source schema"
                if mapping_changed
                else "Active Forge mapping matches source schema fingerprint",
                expected={"forge_schema_hash": artifact_hash, "version": active_artifact.version},
                actual={"current_schema_hash": current_hash},
                details={
                    "artifact_status": active_artifact.status,
                    "generated_by": active_artifact.generated_by,
                },
                before=artifact_hash,
                after=current_hash,
            )
        else:
            await self._upsert_or_resolve_drift_signal(
                db,
                source_connection=source_connection,
                mapping_artifact=None,
                drift_type="mapping",
                severity="info",
                summary="No active Forge mapping artifact is attached to this source",
                expected={"mapping_artifact": "active"},
                actual={"mapping_artifact": None},
                details={},
                before=None,
                after=None,
            )

    async def _project_graph_event(
        self,
        db: AsyncSession,
        *,
        event: GraphEvent,
        collection_id: str,
        source_connection: SourceConnection | None,
    ) -> dict[str, int]:
        event_type = event.event_type or ""
        payload = (event.event_data or {}).get("payload") or {}
        counts = {"facts": 0, "lineage": 0, "decisions": 0}
        if event_type.startswith("NODE"):
            node_id = _clean_text(payload.get("node_id"), event.node_id or event.entity_id)
            node_type = _clean_text(payload.get("node_type") or event.entity_type, "Entity")
            props = dict(payload.get("node_properties") or {})
            object_value = {
                "node_type": node_type,
                "properties": _jsonable(props),
                "entity_id": event.entity_id,
                "entity_type": event.entity_type,
            }
            created_fact = await self._create_temporal_fact(
                db,
                event=event,
                collection_id=collection_id,
                source_connection=source_connection,
                primitive_ref=node_id,
                primitive_type="node",
                subject_node_id=node_id,
                predicate="current_state",
                object_value=object_value,
                provenance={
                    "source": getattr(source_connection, "short_name", None) or props.get("source_type"),
                    "pipeline": "graph_commit",
                    "graph_event_id": str(event.id),
                },
            )
            counts["facts"] += int(created_fact)
            created_lineage = await self._create_lineage_edge(
                db,
                event=event,
                collection_id=collection_id,
                source_connection=source_connection,
                from_ref=f"source_entity:{event.entity_id or node_id}",
                from_type="source_entity",
                to_ref=node_id,
                to_type="node",
                relationship_type="COMMITTED_AS",
                evidence={
                    "event_type": event_type,
                    "node_type": node_type,
                    "graph_event_id": str(event.id),
                },
            )
            counts["lineage"] += int(created_lineage)
            decision = await self._maybe_create_decision(
                db,
                event=event,
                collection_id=collection_id,
                source_connection=source_connection,
                node_id=node_id,
                node_type=node_type,
                properties=props,
            )
            counts["decisions"] += int(decision)
        elif event_type.startswith("EDGE"):
            from_node = payload.get("from_node") or {}
            to_node = payload.get("to_node") or {}
            source_node_id = _clean_text(from_node.get("node_id"))
            target_node_id = _clean_text(to_node.get("node_id"))
            edge_type = _clean_text(payload.get("edge_type"), "RELATED_TO")
            edge_ref = self._edge_ref(
                source_node_id,
                target_node_id,
                edge_type,
                collection_id=collection_id,
            )
            edge_props = dict(payload.get("edge_properties") or {})
            created_fact = await self._create_temporal_fact(
                db,
                event=event,
                collection_id=collection_id,
                source_connection=source_connection,
                primitive_ref=edge_ref,
                primitive_type="relationship",
                subject_node_id=source_node_id,
                predicate=edge_type,
                object_value={
                    "target_node_id": target_node_id,
                    "relationship_type": edge_type,
                    "properties": _jsonable(edge_props),
                },
                provenance={
                    "source": getattr(source_connection, "short_name", None),
                    "pipeline": "graph_commit",
                    "graph_event_id": str(event.id),
                },
            )
            counts["facts"] += int(created_fact)
            created_lineage = await self._create_lineage_edge(
                db,
                event=event,
                collection_id=collection_id,
                source_connection=source_connection,
                from_ref=source_node_id,
                from_type="node",
                to_ref=target_node_id,
                to_type="node",
                relationship_type=edge_type
                if edge_type in DECISION_EDGE_TYPES
                else "DERIVED_RELATIONSHIP",
                evidence={
                    "edge_type": edge_type,
                    "edge_ref": edge_ref,
                    "properties": _jsonable(edge_props),
                },
            )
            counts["lineage"] += int(created_lineage)
        return counts

    async def _create_temporal_fact(
        self,
        db: AsyncSession,
        *,
        event: GraphEvent,
        collection_id: str,
        source_connection: SourceConnection | None,
        primitive_ref: str,
        primitive_type: str,
        subject_node_id: Optional[str],
        predicate: str,
        object_value: dict[str, Any],
        provenance: dict[str, Any],
    ) -> bool:
        now = event.committed_at or utc_now_naive()
        existing_result = await db.execute(
            select(ContextTemporalFact)
            .where(ContextTemporalFact.organization_id == event.organization_id)
            .where(ContextTemporalFact.collection_readable_id == collection_id)
            .where(ContextTemporalFact.primitive_ref == primitive_ref)
            .where(ContextTemporalFact.primitive_type == primitive_type)
            .where(ContextTemporalFact.predicate == predicate)
            .where(ContextTemporalFact.status == "current")
            .order_by(ContextTemporalFact.transaction_created_at.desc())
            .limit(1)
        )
        existing = existing_result.scalar_one_or_none()
        if existing and _stable_hash(existing.object_value) == _stable_hash(object_value):
            return False
        if existing:
            existing.status = "superseded"
            existing.invalid_at = now
            existing.transaction_expired_at = now

        fact = ContextTemporalFact(
            organization_id=event.organization_id,
            collection_readable_id=collection_id,
            source_connection_id=getattr(source_connection, "id", None),
            sync_id=event.sync_id,
            sync_job_id=event.sync_job_id,
            graph_event_id=event.id,
            primitive_ref=primitive_ref,
            primitive_type=primitive_type,
            subject_node_id=subject_node_id,
            predicate=predicate,
            object_value=_jsonable(object_value),
            provenance=_jsonable(provenance),
            valid_at=now,
            transaction_created_at=now,
            supersedes_id=getattr(existing, "id", None),
            status="current",
            confidence=float((object_value.get("properties") or {}).get("confidence") or 1.0)
            if isinstance(object_value.get("properties"), Mapping)
            else 1.0,
            feedback_weight=float((object_value.get("properties") or {}).get("feedback_weight") or 1.0)
            if isinstance(object_value.get("properties"), Mapping)
            else 1.0,
        )
        db.add(fact)
        return True

    async def _create_lineage_edge(
        self,
        db: AsyncSession,
        *,
        event: GraphEvent,
        collection_id: str,
        source_connection: SourceConnection | None,
        from_ref: str,
        from_type: str,
        to_ref: str,
        to_type: str,
        relationship_type: str,
        evidence: dict[str, Any],
    ) -> bool:
        if not from_ref or not to_ref:
            return False
        now = event.committed_at or utc_now_naive()
        if relationship_type == "COMMITTED_AS" and to_type == "node":
            legacy_result = await db.execute(
                select(ContextLineageEdge)
                .where(ContextLineageEdge.organization_id == event.organization_id)
                .where(ContextLineageEdge.collection_readable_id == collection_id)
                .where(ContextLineageEdge.to_ref == to_ref)
                .where(ContextLineageEdge.to_type == to_type)
                .where(ContextLineageEdge.relationship_type == relationship_type)
                .where(ContextLineageEdge.from_type == "graph_event")
                .where(ContextLineageEdge.status == "current")
            )
            for legacy in legacy_result.scalars().all():
                legacy.status = "superseded"
                legacy.invalid_at = now
                legacy.transaction_expired_at = now

        existing_result = await db.execute(
            select(ContextLineageEdge)
            .where(ContextLineageEdge.organization_id == event.organization_id)
            .where(ContextLineageEdge.collection_readable_id == collection_id)
            .where(ContextLineageEdge.from_ref == from_ref)
            .where(ContextLineageEdge.from_type == from_type)
            .where(ContextLineageEdge.to_ref == to_ref)
            .where(ContextLineageEdge.to_type == to_type)
            .where(ContextLineageEdge.relationship_type == relationship_type)
            .where(ContextLineageEdge.status == "current")
            .order_by(ContextLineageEdge.transaction_created_at.desc())
        )
        existing_lineages = list(existing_result.scalars().all())
        existing = existing_lineages[0] if existing_lineages else None
        for stale in existing_lineages[1:]:
            stale.status = "superseded"
            stale.invalid_at = now
            stale.transaction_expired_at = now
        if existing and _stable_hash(existing.evidence) == _stable_hash(evidence):
            return False
        if existing:
            existing.status = "superseded"
            existing.invalid_at = now
            existing.transaction_expired_at = now

        lineage = ContextLineageEdge(
            organization_id=event.organization_id,
            collection_readable_id=collection_id,
            source_connection_id=getattr(source_connection, "id", None),
            sync_id=event.sync_id,
            sync_job_id=event.sync_job_id,
            graph_event_id=event.id,
            from_ref=from_ref,
            from_type=from_type,
            to_ref=to_ref,
            to_type=to_type,
            relationship_type=relationship_type,
            evidence=_jsonable(evidence),
            valid_at=now,
            transaction_created_at=now,
            confidence=float(evidence.get("confidence") or 1.0),
        )
        db.add(lineage)
        return True

    async def _maybe_create_decision(
        self,
        db: AsyncSession,
        *,
        event: GraphEvent,
        collection_id: str,
        source_connection: SourceConnection | None,
        node_id: str,
        node_type: str,
        properties: Mapping[str, Any],
    ) -> bool:
        blob = _lower_blob(node_type, properties.get("entity_type"), properties.get("subtype"), properties.get("type"))
        if "decision" not in blob and "approval" not in blob and "exception" not in blob:
            return False

        decision_type = _clean_text(
            properties.get("decision_type") or properties.get("subtype") or properties.get("type"),
            "approval" if "approval" in blob else "selection",
        )
        subject = _clean_text(
            properties.get("subject")
            or properties.get("title")
            or properties.get("name")
            or properties.get("label"),
            node_id,
        )
        outcome = _clean_text(
            properties.get("outcome") or properties.get("status") or properties.get("decision"),
            "recorded",
        )
        decision_key = _clean_text(properties.get("decision_id") or properties.get("id"), node_id)
        now = event.committed_at or utc_now_naive()

        existing_result = await db.execute(
            select(ContextDecision)
            .where(ContextDecision.organization_id == event.organization_id)
            .where(ContextDecision.collection_readable_id == collection_id)
            .where(ContextDecision.decision_key == decision_key)
            .where(ContextDecision.status == "current")
            .limit(1)
        )
        existing = existing_result.scalar_one_or_none()
        if existing and existing.outcome == outcome and existing.subject == subject:
            return False
        if existing:
            existing.status = "superseded"
            existing.invalid_at = now
            existing.transaction_expired_at = now

        decision = ContextDecision(
            organization_id=event.organization_id,
            collection_readable_id=collection_id,
            source_connection_id=getattr(source_connection, "id", None),
            sync_id=event.sync_id,
            graph_event_id=event.id,
            decision_key=decision_key,
            decision_type=decision_type,
            subject=subject,
            outcome=outcome,
            decided_by_ref=properties.get("decided_by_id") or properties.get("owner_id"),
            decided_by_name=properties.get("decided_by") or properties.get("owner") or properties.get("author"),
            decided_at=self._parse_date(properties.get("decided_at") or properties.get("created_at")) or now,
            inputs=_listify(properties.get("inputs") or properties.get("evidence") or properties.get("sources")),
            policy_ref=properties.get("policy") or properties.get("policy_ref"),
            exception=bool(properties.get("exception") or properties.get("is_exception") or False),
            justification=properties.get("justification") or properties.get("reason") or properties.get("description"),
            affected_refs=[str(item) for item in _listify(properties.get("affected_entities") or properties.get("affected") or node_id)],
            valid_at=now,
            transaction_created_at=now,
            superseded_by_id=None,
            status="current",
            confidence=float(properties.get("confidence") or 0.84),
        )
        db.add(decision)
        return True

    async def _upsert_or_resolve_drift_signal(
        self,
        db: AsyncSession,
        *,
        source_connection: SourceConnection,
        mapping_artifact: ContextForgeMappingArtifact | None,
        drift_type: str,
        severity: str,
        summary: str,
        expected: Mapping[str, Any],
        actual: Mapping[str, Any],
        details: Mapping[str, Any],
        before: Optional[str],
        after: Optional[str],
    ) -> None:
        latest_result = await db.execute(
            select(ContextDriftSignal)
            .where(ContextDriftSignal.organization_id == source_connection.organization_id)
            .where(ContextDriftSignal.collection_readable_id == source_connection.readable_collection_id)
            .where(ContextDriftSignal.source_connection_id == source_connection.id)
            .where(ContextDriftSignal.drift_type == drift_type)
            .where(ContextDriftSignal.status == "active")
            .order_by(ContextDriftSignal.detected_at.desc())
            .limit(1)
        )
        latest = latest_result.scalar_one_or_none()
        now = utc_now_naive()
        if severity == "clean":
            if latest:
                latest.status = "resolved"
                latest.severity = "clean"
                latest.summary = summary
                latest.resolved_at = now
            return

        before_hash = str(before) if before else None
        after_hash = str(after) if after else _stable_hash(actual)
        if latest and latest.fingerprint_before == before_hash and latest.fingerprint_after == after_hash:
            latest.severity = severity
            latest.summary = summary
            latest.expected = _jsonable(expected)
            latest.actual = _jsonable(actual)
            latest.details = _jsonable(details)
            return
        if latest:
            latest.status = "resolved"
            latest.resolved_at = now

        signal = ContextDriftSignal(
            organization_id=source_connection.organization_id,
            collection_readable_id=source_connection.readable_collection_id,
            source_connection_id=source_connection.id,
            mapping_artifact_id=getattr(mapping_artifact, "id", None),
            sync_id=source_connection.sync_id,
            drift_type=drift_type,
            severity=severity,
            status="active",
            summary=summary,
            expected=_jsonable(expected),
            actual=_jsonable(actual),
            details=_jsonable(details),
            fingerprint_before=before_hash,
            fingerprint_after=after_hash,
            detected_at=now,
        )
        db.add(signal)

    async def _latest_mapping_artifact(
        self, db: AsyncSession, source_connection: SourceConnection
    ) -> ContextForgeMappingArtifact | None:
        result = await db.execute(
            select(ContextForgeMappingArtifact)
            .where(ContextForgeMappingArtifact.organization_id == source_connection.organization_id)
            .where(ContextForgeMappingArtifact.source_connection_id == source_connection.id)
            .order_by(ContextForgeMappingArtifact.version.desc(), ContextForgeMappingArtifact.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _get_source_by_sync(
        self, db: AsyncSession, sync_id: UUID, organization_id: UUID
    ) -> SourceConnection | None:
        result = await db.execute(
            select(SourceConnection)
            .where(SourceConnection.organization_id == organization_id)
            .where(SourceConnection.sync_id == sync_id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _count(
        self,
        db: AsyncSession,
        model: Any,
        organization_id: UUID,
        collection_id: str,
        *conditions: Any,
    ) -> int:
        stmt = (
            select(func.count(model.id))
            .where(model.organization_id == organization_id)
            .where(model.collection_readable_id == collection_id)
        )
        for condition in conditions:
            stmt = stmt.where(condition)
        result = await db.execute(stmt)
        return int(result.scalar() or 0)

    async def _latest_temporal_facts(
        self, db: AsyncSession, organization_id: UUID, collection_id: str, limit: int = 8
    ) -> list[dict[str, Any]]:
        result = await db.execute(
            select(ContextTemporalFact)
            .where(ContextTemporalFact.organization_id == organization_id)
            .where(ContextTemporalFact.collection_readable_id == collection_id)
            .order_by(ContextTemporalFact.transaction_created_at.desc())
            .limit(limit)
        )
        return [self._fact_payload(item) for item in result.scalars().all()]

    async def _latest_lineage_edges(
        self, db: AsyncSession, organization_id: UUID, collection_id: str, limit: int = 8
    ) -> list[dict[str, Any]]:
        result = await db.execute(
            select(ContextLineageEdge)
            .where(ContextLineageEdge.organization_id == organization_id)
            .where(ContextLineageEdge.collection_readable_id == collection_id)
            .where(ContextLineageEdge.status == "current")
            .order_by(ContextLineageEdge.created_at.desc())
            .limit(limit)
        )
        return [self._lineage_payload(item) for item in result.scalars().all()]

    async def _latest_decisions(
        self, db: AsyncSession, organization_id: UUID, collection_id: str, limit: int = 8
    ) -> list[dict[str, Any]]:
        result = await db.execute(
            select(ContextDecision)
            .where(ContextDecision.organization_id == organization_id)
            .where(ContextDecision.collection_readable_id == collection_id)
            .order_by(ContextDecision.decided_at.desc())
            .limit(limit)
        )
        return [self._decision_payload(item) for item in result.scalars().all()]

    async def _latest_drift_signals(
        self, db: AsyncSession, organization_id: UUID, collection_id: str, limit: int = 8
    ) -> list[dict[str, Any]]:
        result = await db.execute(
            select(ContextDriftSignal)
            .where(ContextDriftSignal.organization_id == organization_id)
            .where(ContextDriftSignal.collection_readable_id == collection_id)
            .where(ContextDriftSignal.status == "active")
            .order_by(ContextDriftSignal.detected_at.desc())
            .limit(limit)
        )
        return [self._drift_payload(item) for item in result.scalars().all()]

    async def _latest_query_traces(
        self, db: AsyncSession, organization_id: UUID, collection_id: str, limit: int = 6
    ) -> list[dict[str, Any]]:
        result = await db.execute(
            select(ContextQueryDecisionTrace)
            .where(ContextQueryDecisionTrace.organization_id == organization_id)
            .where(ContextQueryDecisionTrace.collection_readable_id == collection_id)
            .order_by(ContextQueryDecisionTrace.created_at.desc())
            .limit(limit)
        )
        traces = []
        for item in result.scalars().all():
            feedback = (item.decision_tree or {}).get("feedback") or {}
            traces.append(
                {
                    "query_id": item.query_id,
                    "query": item.query_text,
                    "recipe": item.recipe,
                    "status": item.status,
                    "created_at": item.created_at.isoformat(),
                    "decision_steps": len((item.decision_tree or {}).get("steps") or []),
                    "tokens": item.token_estimate,
                    "feedback_rating": feedback.get("rating"),
                    "feedback_weight": feedback.get("target_weight"),
                }
            )
        return traces

    async def _query_temporal_context(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        collection_id: str,
        node_ids: list[str],
    ) -> dict[str, Any]:
        conditions = [
            ContextTemporalFact.organization_id == organization_id,
            ContextTemporalFact.collection_readable_id == collection_id,
            ContextTemporalFact.status == "current",
        ]
        if node_ids:
            conditions.append(
                or_(
                    ContextTemporalFact.subject_node_id.in_(node_ids[:250]),
                    ContextTemporalFact.primitive_ref.in_(node_ids[:250]),
                )
            )
        count_result = await db.execute(select(func.count(ContextTemporalFact.id)).where(*conditions))
        recent_result = await db.execute(
            select(ContextTemporalFact)
            .where(*conditions)
            .order_by(ContextTemporalFact.transaction_created_at.desc())
            .limit(5)
        )
        superseded_result = await db.execute(
            select(func.count(ContextTemporalFact.id))
            .where(ContextTemporalFact.organization_id == organization_id)
            .where(ContextTemporalFact.collection_readable_id == collection_id)
            .where(ContextTemporalFact.status == "superseded")
        )
        return {
            "mode": "current_state",
            "as_of": utc_now_naive().isoformat(),
            "current_facts": int(count_result.scalar() or 0),
            "superseded_facts": int(superseded_result.scalar() or 0),
            "recent_changes": [self._fact_payload(item) for item in recent_result.scalars().all()],
        }

    async def _query_lineage_context(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        collection_id: str,
        node_ids: list[str],
    ) -> dict[str, Any]:
        conditions = [
            ContextLineageEdge.organization_id == organization_id,
            ContextLineageEdge.collection_readable_id == collection_id,
            ContextLineageEdge.status == "current",
        ]
        if node_ids:
            conditions.append(
                or_(
                    ContextLineageEdge.from_ref.in_(node_ids[:250]),
                    ContextLineageEdge.to_ref.in_(node_ids[:250]),
                )
            )
        count_result = await db.execute(select(func.count(ContextLineageEdge.id)).where(*conditions))
        recent_result = await db.execute(
            select(ContextLineageEdge)
            .where(*conditions)
            .order_by(ContextLineageEdge.created_at.desc())
            .limit(8)
        )
        return {
            "edge_count": int(count_result.scalar() or 0),
            "edges": [self._lineage_payload(item) for item in recent_result.scalars().all()],
        }

    async def _query_decision_history(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        collection_id: str,
        node_ids: list[str],
        query: str,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(ContextDecision)
            .where(ContextDecision.organization_id == organization_id)
            .where(ContextDecision.collection_readable_id == collection_id)
            .where(ContextDecision.status == "current")
            .order_by(ContextDecision.decided_at.desc())
            .limit(8)
        )
        result = await db.execute(stmt)
        decisions = [self._decision_payload(item) for item in result.scalars().all()]
        if "decision" in query.lower():
            return decisions
        affected_nodes = set(node_ids)
        scoped = [
            item
            for item in decisions
            if affected_nodes.intersection(set(str(ref) for ref in item.get("affected_refs") or []))
        ]
        return scoped or decisions[:3]

    def _build_decision_tree(
        self,
        *,
        query: str,
        recipe: str,
        path_used: str,
        metadata: Mapping[str, Any],
        temporal_context: Mapping[str, Any],
        lineage_context: Mapping[str, Any],
        decision_history: list[Mapping[str, Any]],
        drift_context: Mapping[str, Any],
        tool_context: Mapping[str, Any],
        context_tools: Sequence[str],
        retrieved_node_ids: list[str],
        retrieved_edge_ids: list[str],
        query_id: str,
        latency_ms: Optional[int] = None,
    ) -> dict[str, Any]:
        drift_severity = _clean_text(drift_context.get("severity"), "clean")
        search_result_count = int(metadata.get("search_result_count") or 0)
        node_count = int(metadata.get("node_count") or len(retrieved_node_ids))
        edge_count = int(metadata.get("edge_count") or len(retrieved_edge_ids))
        token_estimate = int(metadata.get("token_estimate") or 0)
        native_decision_count = len(decision_history)
        # The query trace being built here is itself a persisted ContextD decision audit row.
        # Count it alongside any source-level Decision primitives so the UI never shows
        # a successful response trace as "0 decisions".
        query_trace_count = 1
        decision_audit_count = native_decision_count + query_trace_count
        steps = [
            {
                "key": "parse_intent",
                "label": "Parse intent",
                "detail": "mentions, temporal scope, filters",
                "status": "done",
                "input": {"query": query},
                "output": {
                    "recipe": recipe,
                    "path": path_used,
                    "temporal_mode": metadata.get("temporal_mode") or "current",
                    "context_tools": list(context_tools),
                },
            },
            {
                "key": "seed_selection",
                "label": "Seed search",
                "detail": "semantic + full-text seed candidates",
                "status": "done",
                "input_count": search_result_count,
                "output_count": search_result_count,
                "output": {
                    "seed_count": search_result_count,
                    "source_types": _jsonable(metadata.get("source_types") or []),
                },
            },
            {
                "key": "graph_expand",
                "label": "Graph expand",
                "detail": "Neo4j neighborhood traversal",
                "status": "done",
                "input_count": search_result_count,
                "output_count": node_count,
                "output": {
                    "node_count": node_count,
                    "edge_count": edge_count,
                    "sample_nodes": retrieved_node_ids[:8],
                },
            },
            {
                "key": "feedback_prior",
                "label": "Feedback prior",
                "detail": "workspace memory weights for retrieved facts",
                "status": "done",
                "input_count": len(retrieved_node_ids) + len(retrieved_edge_ids),
                "output": {"mode": "feedback_weight", "weighted_items": len(retrieved_node_ids) + len(retrieved_edge_ids)},
            },
            {
                "key": "core_context",
                "label": "Core context",
                "detail": "database shape, source, and packet lane summary",
                "status": "done" if "core" in context_tools else "available",
                "output": _jsonable((tool_context.get("tools") or {}).get("core") or {}),
            },
            {
                "key": "cohort_scope",
                "label": "Cohort scope",
                "detail": "selected cohort filter or all-entity scope",
                "status": "done" if "cohort" in context_tools else "available",
                "output": _jsonable((tool_context.get("tools") or {}).get("cohort") or {}),
            },
            {
                "key": "temporal_prune",
                "label": "Temporal prune",
                "detail": "current-state bitemporal filter",
                "status": "done" if "temporal" in context_tools else "available",
                "output_count": int(temporal_context.get("current_facts") or 0),
                "output": {
                    "current_facts": temporal_context.get("current_facts", 0),
                    "superseded_facts": temporal_context.get("superseded_facts", 0),
                    "mode": "current",
                },
            },
            {
                "key": "lineage_attach",
                "label": "Lineage attach",
                "detail": "source, Forge, and graph-event provenance",
                "status": "done",
                "output_count": int(lineage_context.get("edge_count") or 0),
                "output": {
                    "edge_count": lineage_context.get("edge_count", 0),
                    "sample_edges": _jsonable((lineage_context.get("edges") or [])[:3]),
                },
            },
            {
                "key": "decision_lineage",
                "label": "Decision lineage",
                "detail": "query audit plus first-class Decision vertices",
                "status": "done" if "decision" in context_tools else "available",
                "output_count": decision_audit_count,
                "output": {
                    "decision_count": decision_audit_count,
                    "native_decisions": native_decision_count,
                    "query_traces": query_trace_count,
                    "decisions": _jsonable(decision_history[:3]),
                },
            },
            {
                "key": "drift_guard",
                "label": "Drift guard",
                "detail": "config, schema, cursor, and Forge baseline check",
                "status": "warn" if drift_severity in {"warning", "critical"} else "done",
                "output": {
                    "severity": drift_severity,
                    "active_count": drift_context.get("active_count", 0),
                },
            },
            {
                "key": "assemble_packet",
                "label": "Assemble packet",
                "detail": "budgeted context JSON for answer synthesis",
                "status": "done",
                "output": {
                    "token_estimate": token_estimate,
                    "max_depth": metadata.get("max_depth"),
                    "query_id": query_id,
                },
            },
        ]
        return {
            "version": 1,
            "status": "completed",
            "query_id": query_id,
            "query": query,
            "recipe": recipe,
            "path_used": path_used,
            "latency_ms": latency_ms,
            "metrics": {
                "node_count": node_count,
                "edge_count": edge_count,
                "search_result_count": search_result_count,
                "token_estimate": token_estimate,
                "temporal_facts": temporal_context.get("current_facts", 0),
                "lineage_edges": lineage_context.get("edge_count", 0),
                "decisions": decision_audit_count,
                "native_decisions": native_decision_count,
                "query_traces": query_trace_count,
                "drift_severity": drift_severity,
                "context_tools": list(context_tools),
            },
            "tool_context": _jsonable(tool_context),
            "steps": steps,
        }

    def _build_tool_context(
        self,
        *,
        collection: Collection,
        context_tools: Sequence[str],
        recipe: str,
        path_used: str,
        metadata: Mapping[str, Any],
        temporal_context: Mapping[str, Any],
        lineage_context: Mapping[str, Any],
        decision_history: list[Mapping[str, Any]],
        drift_context: Mapping[str, Any],
        retrieved_node_ids: list[str],
        retrieved_edge_ids: list[str],
    ) -> dict[str, Any]:
        requested = self._normalize_context_tools(context_tools)

        def tool_status(tool: str, has_evidence: bool = True) -> str:
            if tool not in requested:
                return "available" if has_evidence else "idle"
            return "applied" if has_evidence else "empty"

        search_count = int(metadata.get("search_result_count") or 0)
        node_count = int(metadata.get("node_count") or len(retrieved_node_ids))
        edge_count = int(metadata.get("edge_count") or len(retrieved_edge_ids))
        temporal_count = int(temporal_context.get("current_facts") or 0)
        lineage_count = int(lineage_context.get("edge_count") or 0)
        drift_severity = _clean_text(drift_context.get("severity"), "clean")
        native_decision_count = len(decision_history)
        query_trace_count = 1
        decision_count = native_decision_count + query_trace_count
        tools = {
            "search": {
                "purpose": CONTEXT_TOOL_PURPOSES["search"],
                "status": tool_status("search", search_count > 0),
                "recipe": recipe,
                "path": path_used,
                "seed_count": search_count,
            },
            "graph": {
                "purpose": CONTEXT_TOOL_PURPOSES["graph"],
                "status": tool_status("graph", node_count > 0),
                "node_count": node_count,
                "edge_count": edge_count,
                "max_depth": metadata.get("max_depth"),
            },
            "temporal": {
                "purpose": CONTEXT_TOOL_PURPOSES["temporal"],
                "status": tool_status("temporal", temporal_count > 0),
                "current_facts": temporal_count,
                "superseded_facts": temporal_context.get("superseded_facts", 0),
                "mode": metadata.get("temporal_mode") or "current",
            },
            "core": {
                "purpose": CONTEXT_TOOL_PURPOSES["core"],
                "status": tool_status("core", True),
                "database": collection.readable_id,
                "name": collection.name,
                "vector_size": collection.vector_size,
                "source_types": _jsonable(metadata.get("source_types") or []),
                "entities": node_count,
                "relationships": edge_count,
            },
            "cohort": {
                "purpose": CONTEXT_TOOL_PURPOSES["cohort"],
                "status": tool_status("cohort", True),
                "scope": "all",
                "matched_entities": node_count,
                "note": "No saved cohort filter selected; packet uses the all-entity cohort.",
            },
            "decision": {
                "purpose": CONTEXT_TOOL_PURPOSES["decision"],
                "status": tool_status("decision", decision_count > 0),
                "decision_count": decision_count,
                "native_decisions": native_decision_count,
                "query_traces": query_trace_count,
                "drift_severity": drift_severity,
                "lineage_edges": lineage_count,
            },
        }
        applied = [tool for tool in requested if (tools.get(tool) or {}).get("status") == "applied"]
        return {
            "requested": list(requested),
            "applied": applied,
            "available": list(CONTEXT_TOOL_KEYS),
            "tools": _jsonable(tools),
        }

    @staticmethod
    def _normalize_context_tools(values: Optional[Sequence[str]]) -> list[str]:
        cleaned: list[str] = []
        for raw in values or []:
            value = str(raw or "").strip().lower().removeprefix("@")
            if value in CONTEXT_TOOL_KEYS and value not in cleaned:
                cleaned.append(value)
        return cleaned

    async def _query_trace(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        collection_id: str,
        query_id: Optional[str],
    ) -> Optional[ContextQueryDecisionTrace]:
        stmt = (
            select(ContextQueryDecisionTrace)
            .where(ContextQueryDecisionTrace.organization_id == organization_id)
            .where(ContextQueryDecisionTrace.collection_readable_id == collection_id)
            .order_by(ContextQueryDecisionTrace.created_at.desc())
            .limit(1)
        )
        if query_id:
            stmt = stmt.where(ContextQueryDecisionTrace.query_id == query_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def _feedback_facts(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        collection_id: str,
        node_ids: list[str],
        edge_ids: list[str],
    ) -> list[ContextTemporalFact]:
        selectors = []
        if node_ids:
            bounded_nodes = node_ids[:250]
            selectors.extend(
                [
                    ContextTemporalFact.subject_node_id.in_(bounded_nodes),
                    ContextTemporalFact.primitive_ref.in_(bounded_nodes),
                ]
            )
        if edge_ids:
            selectors.append(ContextTemporalFact.primitive_ref.in_(edge_ids[:250]))
        if not selectors:
            return []
        result = await db.execute(
            select(ContextTemporalFact)
            .where(ContextTemporalFact.organization_id == organization_id)
            .where(ContextTemporalFact.collection_readable_id == collection_id)
            .where(ContextTemporalFact.status == "current")
            .where(or_(*selectors))
            .limit(1000)
        )
        return list(result.scalars().all())

    @staticmethod
    def _unique_strings(values: Optional[Sequence[Any]]) -> list[str]:
        cleaned = [str(value).strip() for value in values or [] if str(value).strip()]
        return list(dict.fromkeys(cleaned))

    @staticmethod
    def _feedback_target_weight(rating: int) -> float:
        bounded = max(1, min(5, int(rating)))
        return round(0.5 + ((bounded - 1) / 4.0), 4)

    @staticmethod
    def _feedback_ema_weight(
        current_weight: Optional[float],
        *,
        target_weight: float,
        alpha: float = 0.10,
    ) -> float:
        baseline = 1.0 if current_weight is None else float(current_weight)
        return round((baseline * (1.0 - alpha)) + (target_weight * alpha), 4)

    def _decision_tree_with_feedback(
        self,
        decision_tree: Mapping[str, Any],
        *,
        rating: int,
        target_weight: float,
        alpha: float,
        updated_fact_count: int,
        comment: Optional[str],
        updated_at: datetime,
    ) -> dict[str, Any]:
        updated = dict(decision_tree or {})
        feedback = {
            "rating": rating,
            "target_weight": target_weight,
            "alpha": alpha,
            "updated_fact_count": updated_fact_count,
            "comment": comment,
            "updated_at": updated_at.isoformat(),
        }
        updated["feedback"] = feedback
        steps = []
        saw_feedback_step = False
        for raw_step in _listify(updated.get("steps")):
            if not isinstance(raw_step, Mapping):
                continue
            step = dict(raw_step)
            if step.get("key") == "feedback_prior":
                saw_feedback_step = True
                step["status"] = "done"
                step["output"] = {
                    **(step.get("output") or {}),
                    "last_rating": rating,
                    "target_weight": target_weight,
                    "updated_fact_count": updated_fact_count,
                }
            steps.append(step)
        if not saw_feedback_step:
            steps.insert(
                min(3, len(steps)),
                {
                    "key": "feedback_prior",
                    "label": "Feedback prior",
                    "detail": "workspace memory weights for retrieved facts",
                    "status": "done",
                    "output": {
                        "last_rating": rating,
                        "target_weight": target_weight,
                        "updated_fact_count": updated_fact_count,
                    },
                },
            )
        updated["steps"] = steps
        return updated

    def _retrieved_node_ids(self, traversal_result: Any, search_results: list[dict[str, Any]]) -> list[str]:
        node_ids: list[str] = []
        for node in getattr(traversal_result, "nodes", None) or []:
            node_id = getattr(node, "node_id", None) or (node.get("node_id") if isinstance(node, Mapping) else None)
            if node_id:
                node_ids.append(str(node_id))
        for result in search_results or []:
            node_id = result.get("node_id")
            if node_id:
                node_ids.append(str(node_id))
        return list(dict.fromkeys(node_ids))

    def _retrieved_edge_ids(self, traversal_result: Any) -> list[str]:
        edge_ids: list[str] = []
        for edge in getattr(traversal_result, "edges", None) or []:
            edge_id = getattr(edge, "edge_id", None) or (
                edge.get("edge_id") if isinstance(edge, Mapping) else None
            )
            if not edge_id:
                if isinstance(edge, Mapping):
                    from_node_id = edge.get("from_node_id")
                    to_node_id = edge.get("to_node_id")
                    relationship_type = edge.get("relationship_type")
                else:
                    from_node_id = getattr(edge, "from_node_id", None)
                    to_node_id = getattr(edge, "to_node_id", None)
                    relationship_type = getattr(edge, "relationship_type", None)
                if from_node_id and to_node_id and relationship_type:
                    edge_id = f"{from_node_id}|{relationship_type}|{to_node_id}"
            if edge_id:
                edge_ids.append(str(edge_id))
        return list(dict.fromkeys(edge_ids))

    def _fact_payload(self, item: ContextTemporalFact) -> dict[str, Any]:
        return {
            "id": str(item.id),
            "primitive_ref": item.primitive_ref,
            "primitive_type": item.primitive_type,
            "subject_node_id": item.subject_node_id,
            "predicate": item.predicate,
            "status": item.status,
            "valid_at": item.valid_at.isoformat() if item.valid_at else None,
            "invalid_at": item.invalid_at.isoformat() if item.invalid_at else None,
            "created_at": item.transaction_created_at.isoformat()
            if item.transaction_created_at
            else None,
            "expired_at": item.transaction_expired_at.isoformat()
            if item.transaction_expired_at
            else None,
            "provenance": item.provenance or {},
            "object_value": item.object_value or {},
        }

    def _lineage_payload(self, item: ContextLineageEdge) -> dict[str, Any]:
        return {
            "id": str(item.id),
            "from_ref": item.from_ref,
            "from_type": item.from_type,
            "to_ref": item.to_ref,
            "to_type": item.to_type,
            "relationship_type": item.relationship_type,
            "confidence": item.confidence,
            "evidence": item.evidence or {},
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }

    def _decision_payload(self, item: ContextDecision) -> dict[str, Any]:
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

    def _drift_payload(self, item: ContextDriftSignal) -> dict[str, Any]:
        return {
            "id": str(item.id),
            "drift_type": item.drift_type,
            "severity": item.severity,
            "status": item.status,
            "summary": item.summary,
            "expected": item.expected or {},
            "actual": item.actual or {},
            "details": item.details or {},
            "detected_at": item.detected_at.isoformat() if item.detected_at else None,
            "resolved_at": item.resolved_at.isoformat() if item.resolved_at else None,
        }

    def _source_summary(self, source: SourceConnection) -> dict[str, Any]:
        config = _source_config(source)
        drift = dict(config.get("drift") or {})
        return {
            "source_connection_id": str(source.id),
            "source_name": source.name,
            "provider": source.short_name,
            "sync_id": str(source.sync_id) if source.sync_id else None,
            "cursor_field": _cursor_field(source),
            "drift": {
                "status": drift.get("status") or "unknown",
                "severity": drift.get("severity") or "clean",
                "summary": drift.get("summary") or {},
                "last_checked_at": drift.get("last_checked_at"),
            },
        }

    def _worst_drift(
        self, signals: list[dict[str, Any]], sources: list[dict[str, Any]]
    ) -> dict[str, str]:
        order = {"clean": 0, "info": 1, "warning": 2, "critical": 3}
        worst = "clean"
        for signal in signals:
            severity = _clean_text(signal.get("severity"), "clean")
            if order.get(severity, 0) > order.get(worst, 0):
                worst = severity
        for source in sources:
            severity = _clean_text((source.get("drift") or {}).get("severity"), "clean")
            if order.get(severity, 0) > order.get(worst, 0):
                worst = severity
        return {"status": "clean" if worst == "clean" else "changed", "severity": worst}

    def _temporal_coverage_label(self, current: int, superseded: int) -> str:
        if current and superseded:
            return "bitemporal"
        if current:
            return "current"
        return "empty"

    def _schema_drift_summary(self, schema: Mapping[str, Any]) -> str:
        changes = schema.get("changes") or {}
        parts = []
        for key, label in (
            ("added_objects", "added objects"),
            ("removed_objects", "removed objects"),
            ("changed_objects", "changed objects"),
        ):
            count = len(changes.get(key) or [])
            if count:
                parts.append(f"{count} {label}")
        field_removed = sum(len(items) for items in (changes.get("removed_fields") or {}).values())
        field_changed = sum(len(items) for items in (changes.get("changed_fields") or {}).values())
        if field_removed:
            parts.append(f"{field_removed} removed fields")
        if field_changed:
            parts.append(f"{field_changed} changed fields")
        return "Schema drift detected: " + ", ".join(parts) if parts else "Schema drift detected"

    def _edge_ref(
        self,
        source_node_id: str,
        target_node_id: str,
        edge_type: str,
        *,
        collection_id: Optional[str] = None,
    ) -> str:
        parts = [source_node_id, edge_type, target_node_id]
        if collection_id:
            parts.insert(0, collection_id)
        digest = hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
        return f"edge_{digest}"

    def _parse_date(self, value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value.replace(tzinfo=None)
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None


context_intelligence_service = ContextIntelligenceService()
