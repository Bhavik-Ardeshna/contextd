"""Index temporal supersession references for fast collection deletes.

Revision ID: 0008_temporal_supersedes_idx
Revises: 0007_ctx_intel_indexes
Create Date: 2026-05-09 00:00:00.000000

"""

from alembic import op

revision = "0008_temporal_supersedes_idx"
down_revision = "0007_ctx_intel_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_context_temporal_fact_supersedes_id",
        "context_temporal_fact",
        ["supersedes_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_context_temporal_fact_supersedes_id",
        table_name="context_temporal_fact",
    )
