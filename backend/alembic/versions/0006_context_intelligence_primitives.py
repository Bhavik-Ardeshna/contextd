"""Add native ContextD temporal, lineage, decision, drift primitives.

Revision ID: 0006_context_intelligence
Revises: 0005_context_forge_mapping
Create Date: 2026-05-03 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op


revision = "0006_context_intelligence"
down_revision = "0005_context_forge_mapping"
branch_labels = None
depends_on = None


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("modified_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_email", sa.String(), nullable=True),
        sa.Column("modified_by_email", sa.String(), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "context_temporal_fact",
        sa.Column("collection_readable_id", sa.String(), nullable=False),
        sa.Column("source_connection_id", sa.UUID(), nullable=True),
        sa.Column("sync_id", sa.UUID(), nullable=True),
        sa.Column("sync_job_id", sa.UUID(), nullable=True),
        sa.Column("graph_event_id", sa.UUID(), nullable=True),
        sa.Column("primitive_ref", sa.String(length=512), nullable=False),
        sa.Column("primitive_type", sa.String(length=40), nullable=False),
        sa.Column("subject_node_id", sa.String(length=512), nullable=True),
        sa.Column("predicate", sa.String(length=255), nullable=False),
        sa.Column("object_value", sa.JSON(), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("valid_at", sa.DateTime(), nullable=False),
        sa.Column("invalid_at", sa.DateTime(), nullable=True),
        sa.Column("transaction_created_at", sa.DateTime(), nullable=False),
        sa.Column("transaction_expired_at", sa.DateTime(), nullable=True),
        sa.Column("supersedes_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("feedback_weight", sa.Float(), nullable=False),
        *_base_columns(),
        sa.ForeignKeyConstraint(["collection_readable_id"], ["collection.readable_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["graph_event_id"], ["graph_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_connection_id"], ["source_connection.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["supersedes_id"], ["context_temporal_fact.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sync_id"], ["sync.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sync_job_id"], ["sync_job.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_context_temporal_fact_organization_id"), "context_temporal_fact", ["organization_id"], unique=False)
    op.create_index(op.f("ix_context_temporal_fact_collection_readable_id"), "context_temporal_fact", ["collection_readable_id"], unique=False)
    op.create_index(op.f("ix_context_temporal_fact_source_connection_id"), "context_temporal_fact", ["source_connection_id"], unique=False)
    op.create_index(op.f("ix_context_temporal_fact_sync_id"), "context_temporal_fact", ["sync_id"], unique=False)
    op.create_index(op.f("ix_context_temporal_fact_sync_job_id"), "context_temporal_fact", ["sync_job_id"], unique=False)
    op.create_index(op.f("ix_context_temporal_fact_graph_event_id"), "context_temporal_fact", ["graph_event_id"], unique=False)
    op.create_index(op.f("ix_context_temporal_fact_primitive_ref"), "context_temporal_fact", ["primitive_ref"], unique=False)
    op.create_index(op.f("ix_context_temporal_fact_primitive_type"), "context_temporal_fact", ["primitive_type"], unique=False)
    op.create_index(op.f("ix_context_temporal_fact_subject_node_id"), "context_temporal_fact", ["subject_node_id"], unique=False)
    op.create_index(op.f("ix_context_temporal_fact_predicate"), "context_temporal_fact", ["predicate"], unique=False)
    op.create_index(op.f("ix_context_temporal_fact_invalid_at"), "context_temporal_fact", ["invalid_at"], unique=False)
    op.create_index(op.f("ix_context_temporal_fact_transaction_expired_at"), "context_temporal_fact", ["transaction_expired_at"], unique=False)
    op.create_index(op.f("ix_context_temporal_fact_status"), "context_temporal_fact", ["status"], unique=False)
    op.create_index(
        "ix_context_temporal_fact_current",
        "context_temporal_fact",
        ["organization_id", "collection_readable_id", "subject_node_id", "predicate", "status"],
        unique=False,
    )
    op.create_index(
        "ix_context_temporal_fact_knowledge_time",
        "context_temporal_fact",
        ["organization_id", "collection_readable_id", "transaction_created_at", "transaction_expired_at"],
        unique=False,
    )

    op.create_table(
        "context_lineage_edge",
        sa.Column("collection_readable_id", sa.String(), nullable=False),
        sa.Column("source_connection_id", sa.UUID(), nullable=True),
        sa.Column("sync_id", sa.UUID(), nullable=True),
        sa.Column("sync_job_id", sa.UUID(), nullable=True),
        sa.Column("graph_event_id", sa.UUID(), nullable=True),
        sa.Column("from_ref", sa.String(length=512), nullable=False),
        sa.Column("from_type", sa.String(length=80), nullable=False),
        sa.Column("to_ref", sa.String(length=512), nullable=False),
        sa.Column("to_type", sa.String(length=80), nullable=False),
        sa.Column("relationship_type", sa.String(length=120), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("valid_at", sa.DateTime(), nullable=False),
        sa.Column("invalid_at", sa.DateTime(), nullable=True),
        sa.Column("transaction_created_at", sa.DateTime(), nullable=False),
        sa.Column("transaction_expired_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        *_base_columns(),
        sa.ForeignKeyConstraint(["collection_readable_id"], ["collection.readable_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["graph_event_id"], ["graph_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_connection_id"], ["source_connection.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sync_id"], ["sync.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sync_job_id"], ["sync_job.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "organization_id",
        "collection_readable_id",
        "source_connection_id",
        "sync_id",
        "sync_job_id",
        "graph_event_id",
        "from_ref",
        "from_type",
        "to_ref",
        "to_type",
        "relationship_type",
        "invalid_at",
        "transaction_expired_at",
        "status",
    ):
        op.create_index(op.f(f"ix_context_lineage_edge_{column}"), "context_lineage_edge", [column], unique=False)
    op.create_index(
        "ix_context_lineage_edge_refs",
        "context_lineage_edge",
        ["organization_id", "collection_readable_id", "from_ref", "to_ref", "relationship_type"],
        unique=False,
    )

    op.create_table(
        "context_decision",
        sa.Column("collection_readable_id", sa.String(), nullable=False),
        sa.Column("source_connection_id", sa.UUID(), nullable=True),
        sa.Column("sync_id", sa.UUID(), nullable=True),
        sa.Column("graph_event_id", sa.UUID(), nullable=True),
        sa.Column("decision_key", sa.String(length=512), nullable=False),
        sa.Column("decision_type", sa.String(length=80), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=False),
        sa.Column("outcome", sa.String(length=255), nullable=False),
        sa.Column("decided_by_ref", sa.String(length=512), nullable=True),
        sa.Column("decided_by_name", sa.String(length=255), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("policy_ref", sa.String(length=512), nullable=True),
        sa.Column("exception", sa.Boolean(), nullable=False),
        sa.Column("justification", sa.Text(), nullable=True),
        sa.Column("affected_refs", sa.JSON(), nullable=False),
        sa.Column("valid_at", sa.DateTime(), nullable=False),
        sa.Column("invalid_at", sa.DateTime(), nullable=True),
        sa.Column("transaction_created_at", sa.DateTime(), nullable=False),
        sa.Column("transaction_expired_at", sa.DateTime(), nullable=True),
        sa.Column("superseded_by_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        *_base_columns(),
        sa.ForeignKeyConstraint(["collection_readable_id"], ["collection.readable_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["graph_event_id"], ["graph_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_connection_id"], ["source_connection.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["superseded_by_id"], ["context_decision.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sync_id"], ["sync.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "organization_id",
        "collection_readable_id",
        "source_connection_id",
        "sync_id",
        "graph_event_id",
        "decision_key",
        "decision_type",
        "decided_by_ref",
        "decided_at",
        "policy_ref",
        "invalid_at",
        "transaction_expired_at",
        "status",
    ):
        op.create_index(op.f(f"ix_context_decision_{column}"), "context_decision", [column], unique=False)
    op.create_index(
        "ix_context_decision_audit",
        "context_decision",
        ["organization_id", "collection_readable_id", "decision_type", "decided_at", "status"],
        unique=False,
    )

    op.create_table(
        "context_drift_signal",
        sa.Column("collection_readable_id", sa.String(), nullable=False),
        sa.Column("source_connection_id", sa.UUID(), nullable=True),
        sa.Column("mapping_artifact_id", sa.UUID(), nullable=True),
        sa.Column("sync_id", sa.UUID(), nullable=True),
        sa.Column("sync_job_id", sa.UUID(), nullable=True),
        sa.Column("drift_type", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("expected", sa.JSON(), nullable=False),
        sa.Column("actual", sa.JSON(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("fingerprint_before", sa.String(length=128), nullable=True),
        sa.Column("fingerprint_after", sa.String(length=128), nullable=True),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        *_base_columns(),
        sa.ForeignKeyConstraint(["collection_readable_id"], ["collection.readable_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["mapping_artifact_id"], ["context_forge_mapping.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_connection_id"], ["source_connection.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sync_id"], ["sync.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sync_job_id"], ["sync_job.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "organization_id",
        "collection_readable_id",
        "source_connection_id",
        "mapping_artifact_id",
        "sync_id",
        "sync_job_id",
        "drift_type",
        "severity",
        "status",
        "fingerprint_before",
        "fingerprint_after",
    ):
        op.create_index(op.f(f"ix_context_drift_signal_{column}"), "context_drift_signal", [column], unique=False)
    op.create_index(
        "ix_context_drift_signal_active",
        "context_drift_signal",
        ["organization_id", "collection_readable_id", "source_connection_id", "drift_type", "status"],
        unique=False,
    )

    op.create_table(
        "context_query_decision_trace",
        sa.Column("collection_readable_id", sa.String(), nullable=False),
        sa.Column("query_id", sa.String(length=80), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("recipe", sa.String(length=80), nullable=False),
        sa.Column("path_used", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("temporal_context", sa.JSON(), nullable=False),
        sa.Column("lineage_context", sa.JSON(), nullable=False),
        sa.Column("decision_history", sa.JSON(), nullable=False),
        sa.Column("drift_context", sa.JSON(), nullable=False),
        sa.Column("decision_tree", sa.JSON(), nullable=False),
        sa.Column("retrieved_node_ids", sa.JSON(), nullable=False),
        sa.Column("retrieved_edge_ids", sa.JSON(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        *_base_columns(),
        sa.ForeignKeyConstraint(["collection_readable_id"], ["collection.readable_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("organization_id", "collection_readable_id", "query_id", "status"):
        op.create_index(op.f(f"ix_context_query_decision_trace_{column}"), "context_query_decision_trace", [column], unique=False)
    op.create_index(
        "ix_context_query_decision_trace_collection_created",
        "context_query_decision_trace",
        ["organization_id", "collection_readable_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_context_query_decision_trace_collection_created", table_name="context_query_decision_trace")
    for column in ("status", "query_id", "collection_readable_id", "organization_id"):
        op.drop_index(op.f(f"ix_context_query_decision_trace_{column}"), table_name="context_query_decision_trace")
    op.drop_table("context_query_decision_trace")

    op.drop_index("ix_context_drift_signal_active", table_name="context_drift_signal")
    for column in (
        "fingerprint_after",
        "fingerprint_before",
        "status",
        "severity",
        "drift_type",
        "sync_job_id",
        "sync_id",
        "mapping_artifact_id",
        "source_connection_id",
        "collection_readable_id",
        "organization_id",
    ):
        op.drop_index(op.f(f"ix_context_drift_signal_{column}"), table_name="context_drift_signal")
    op.drop_table("context_drift_signal")

    op.drop_index("ix_context_decision_audit", table_name="context_decision")
    for column in (
        "status",
        "transaction_expired_at",
        "invalid_at",
        "policy_ref",
        "decided_at",
        "decided_by_ref",
        "decision_type",
        "decision_key",
        "graph_event_id",
        "sync_id",
        "source_connection_id",
        "collection_readable_id",
        "organization_id",
    ):
        op.drop_index(op.f(f"ix_context_decision_{column}"), table_name="context_decision")
    op.drop_table("context_decision")

    op.drop_index("ix_context_lineage_edge_refs", table_name="context_lineage_edge")
    for column in (
        "status",
        "transaction_expired_at",
        "invalid_at",
        "relationship_type",
        "to_type",
        "to_ref",
        "from_type",
        "from_ref",
        "graph_event_id",
        "sync_job_id",
        "sync_id",
        "source_connection_id",
        "collection_readable_id",
        "organization_id",
    ):
        op.drop_index(op.f(f"ix_context_lineage_edge_{column}"), table_name="context_lineage_edge")
    op.drop_table("context_lineage_edge")

    op.drop_index("ix_context_temporal_fact_knowledge_time", table_name="context_temporal_fact")
    op.drop_index("ix_context_temporal_fact_current", table_name="context_temporal_fact")
    for column in (
        "status",
        "transaction_expired_at",
        "invalid_at",
        "predicate",
        "subject_node_id",
        "primitive_type",
        "primitive_ref",
        "graph_event_id",
        "sync_job_id",
        "sync_id",
        "source_connection_id",
        "collection_readable_id",
        "organization_id",
    ):
        op.drop_index(op.f(f"ix_context_temporal_fact_{column}"), table_name="context_temporal_fact")
    op.drop_table("context_temporal_fact")
