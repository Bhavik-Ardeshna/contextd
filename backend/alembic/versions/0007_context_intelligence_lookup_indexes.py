"""Add production lookup indexes for ContextD intelligence lanes.

Revision ID: 0007_ctx_intel_indexes
Revises: 0006_context_intelligence
Create Date: 2026-05-03 00:00:00.000000

"""

from alembic import op


revision = "0007_ctx_intel_indexes"
down_revision = "0006_context_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_context_temporal_fact_primitive_lookup",
        "context_temporal_fact",
        ["organization_id", "collection_readable_id", "primitive_ref", "primitive_type", "status"],
        unique=False,
    )
    op.create_index(
        "ix_context_lineage_edge_current_refs",
        "context_lineage_edge",
        ["organization_id", "collection_readable_id", "status", "from_ref", "to_ref", "relationship_type"],
        unique=False,
    )
    op.create_index(
        "ix_context_drift_signal_open",
        "context_drift_signal",
        ["organization_id", "collection_readable_id", "status", "severity", "detected_at"],
        unique=False,
    )
    op.create_index(
        "ix_context_query_decision_trace_latest",
        "context_query_decision_trace",
        ["organization_id", "collection_readable_id", "status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_context_query_decision_trace_latest", table_name="context_query_decision_trace")
    op.drop_index("ix_context_drift_signal_open", table_name="context_drift_signal")
    op.drop_index("ix_context_lineage_edge_current_refs", table_name="context_lineage_edge")
    op.drop_index("ix_context_temporal_fact_primitive_lookup", table_name="context_temporal_fact")
