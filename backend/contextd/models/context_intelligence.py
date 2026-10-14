"""Native ContextD temporal, lineage, decision, and drift primitives."""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column

from contextd.core.datetime_utils import utc_now_naive
from contextd.models._base import OrganizationBase, UserMixin


class ContextTemporalFact(OrganizationBase, UserMixin):
    """Bitemporal fact/state row projected from the graph ingestion pipeline."""

    __tablename__ = "context_temporal_fact"

    collection_readable_id: Mapped[str] = mapped_column(
        ForeignKey("collection.readable_id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_connection_id: Mapped[Optional[UUID]] = mapped_column(
        SAUUID, ForeignKey("source_connection.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sync_id: Mapped[Optional[UUID]] = mapped_column(
        SAUUID, ForeignKey("sync.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sync_job_id: Mapped[Optional[UUID]] = mapped_column(
        SAUUID, ForeignKey("sync_job.id", ondelete="SET NULL"), nullable=True, index=True
    )
    graph_event_id: Mapped[Optional[UUID]] = mapped_column(
        SAUUID, ForeignKey("graph_events.id", ondelete="SET NULL"), nullable=True, index=True
    )

    primitive_ref: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    primitive_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    subject_node_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True, index=True)
    predicate: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    object_value: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    valid_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    invalid_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    transaction_created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive
    )
    transaction_expired_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True
    )
    supersedes_id: Mapped[Optional[UUID]] = mapped_column(
        SAUUID, ForeignKey("context_temporal_fact.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="current", index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    feedback_weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    __table_args__ = (
        Index(
            "ix_context_temporal_fact_current",
            "organization_id",
            "collection_readable_id",
            "subject_node_id",
            "predicate",
            "status",
        ),
        Index(
            "ix_context_temporal_fact_knowledge_time",
            "organization_id",
            "collection_readable_id",
            "transaction_created_at",
            "transaction_expired_at",
        ),
        Index(
            "ix_context_temporal_fact_primitive_lookup",
            "organization_id",
            "collection_readable_id",
            "primitive_ref",
            "primitive_type",
            "status",
        ),
    )


class ContextLineageEdge(OrganizationBase, UserMixin):
    """Provenance/derivation edge between ContextD primitives and source artifacts."""

    __tablename__ = "context_lineage_edge"

    collection_readable_id: Mapped[str] = mapped_column(
        ForeignKey("collection.readable_id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_connection_id: Mapped[Optional[UUID]] = mapped_column(
        SAUUID, ForeignKey("source_connection.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sync_id: Mapped[Optional[UUID]] = mapped_column(
        SAUUID, ForeignKey("sync.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sync_job_id: Mapped[Optional[UUID]] = mapped_column(
        SAUUID, ForeignKey("sync_job.id", ondelete="SET NULL"), nullable=True, index=True
    )
    graph_event_id: Mapped[Optional[UUID]] = mapped_column(
        SAUUID, ForeignKey("graph_events.id", ondelete="SET NULL"), nullable=True, index=True
    )

    from_ref: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    from_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    to_ref: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    to_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    relationship_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    valid_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    invalid_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    transaction_created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive
    )
    transaction_expired_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="current", index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    __table_args__ = (
        Index(
            "ix_context_lineage_edge_refs",
            "organization_id",
            "collection_readable_id",
            "from_ref",
            "to_ref",
            "relationship_type",
        ),
        Index(
            "ix_context_lineage_edge_current_refs",
            "organization_id",
            "collection_readable_id",
            "status",
            "from_ref",
            "to_ref",
            "relationship_type",
        ),
    )


class ContextDecision(OrganizationBase, UserMixin):
    """Strict first-class decision primitive with bitemporal audit metadata."""

    __tablename__ = "context_decision"

    collection_readable_id: Mapped[str] = mapped_column(
        ForeignKey("collection.readable_id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_connection_id: Mapped[Optional[UUID]] = mapped_column(
        SAUUID, ForeignKey("source_connection.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sync_id: Mapped[Optional[UUID]] = mapped_column(
        SAUUID, ForeignKey("sync.id", ondelete="SET NULL"), nullable=True, index=True
    )
    graph_event_id: Mapped[Optional[UUID]] = mapped_column(
        SAUUID, ForeignKey("graph_events.id", ondelete="SET NULL"), nullable=True, index=True
    )

    decision_key: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    decision_type: Mapped[str] = mapped_column(String(80), nullable=False, default="selection", index=True)
    subject: Mapped[str] = mapped_column(String(512), nullable=False)
    outcome: Mapped[str] = mapped_column(String(255), nullable=False, default="recorded")
    decided_by_ref: Mapped[Optional[str]] = mapped_column(String(512), nullable=True, index=True)
    decided_by_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive, index=True)
    inputs: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    policy_ref: Mapped[Optional[str]] = mapped_column(String(512), nullable=True, index=True)
    exception: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    justification: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    affected_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    valid_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    invalid_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    transaction_created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive
    )
    transaction_expired_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True
    )
    superseded_by_id: Mapped[Optional[UUID]] = mapped_column(
        SAUUID, ForeignKey("context_decision.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="current", index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    __table_args__ = (
        Index(
            "ix_context_decision_audit",
            "organization_id",
            "collection_readable_id",
            "decision_type",
            "decided_at",
            "status",
        ),
    )


class ContextDriftSignal(OrganizationBase, UserMixin):
    """Native drift signal spanning config, schema, cursor, graph, and Forge mappings."""

    __tablename__ = "context_drift_signal"

    collection_readable_id: Mapped[str] = mapped_column(
        ForeignKey("collection.readable_id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_connection_id: Mapped[Optional[UUID]] = mapped_column(
        SAUUID, ForeignKey("source_connection.id", ondelete="SET NULL"), nullable=True, index=True
    )
    mapping_artifact_id: Mapped[Optional[UUID]] = mapped_column(
        SAUUID, ForeignKey("context_forge_mapping.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sync_id: Mapped[Optional[UUID]] = mapped_column(
        SAUUID, ForeignKey("sync.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sync_job_id: Mapped[Optional[UUID]] = mapped_column(
        SAUUID, ForeignKey("sync_job.id", ondelete="SET NULL"), nullable=True, index=True
    )

    drift_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(40), nullable=False, default="clean", index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active", index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expected: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    actual: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    fingerprint_before: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    fingerprint_after: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index(
            "ix_context_drift_signal_active",
            "organization_id",
            "collection_readable_id",
            "source_connection_id",
            "drift_type",
            "status",
        ),
        Index(
            "ix_context_drift_signal_open",
            "organization_id",
            "collection_readable_id",
            "status",
            "severity",
            "detected_at",
        ),
    )


class ContextQueryDecisionTrace(OrganizationBase, UserMixin):
    """Stored query response decision tree and context assembly audit packet."""

    __tablename__ = "context_query_decision_trace"

    collection_readable_id: Mapped[str] = mapped_column(
        ForeignKey("collection.readable_id", ondelete="CASCADE"), nullable=False, index=True
    )
    query_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    recipe: Mapped[str] = mapped_column(String(80), nullable=False, default="rrf")
    path_used: Mapped[str] = mapped_column(String(120), nullable=False, default="graph_search")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="completed", index=True)
    temporal_context: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    lineage_context: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    decision_history: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    drift_context: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    decision_tree: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    retrieved_node_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    retrieved_edge_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        Index(
            "ix_context_query_decision_trace_collection_created",
            "organization_id",
            "collection_readable_id",
            "created_at",
        ),
        Index(
            "ix_context_query_decision_trace_latest",
            "organization_id",
            "collection_readable_id",
            "status",
            "created_at",
        ),
    )
