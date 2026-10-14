"""add source connection setup drafts

Revision ID: 0002_setup_draft
Revises: 0001_contextd_initial_schema
Create Date: 2026-05-01 02:20:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_setup_draft"
down_revision = "0001_contextd_initial_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "source_connection_setup_draft",
        sa.Column("provider_short_name", sa.String(), nullable=False),
        sa.Column("target_collection_id", sa.String(), nullable=True),
        sa.Column("connection_name", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("current_step", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("auth_method", sa.String(), nullable=True),
        sa.Column("auth_summary", sa.JSON(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("test_result", sa.JSON(), nullable=True),
        sa.Column("discovery_snapshot", sa.JSON(), nullable=True),
        sa.Column("scope", sa.JSON(), nullable=True),
        sa.Column("schedule", sa.JSON(), nullable=True),
        sa.Column("finalized_source_connection_id", sa.UUID(), nullable=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("modified_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_email", sa.String(), nullable=True),
        sa.Column("modified_by_email", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["finalized_source_connection_id"], ["source_connection.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_collection_id"], ["collection.readable_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_source_connection_setup_draft_organization_id"),
        "source_connection_setup_draft",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_source_connection_setup_draft_provider_short_name"),
        "source_connection_setup_draft",
        ["provider_short_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_source_connection_setup_draft_target_collection_id"),
        "source_connection_setup_draft",
        ["target_collection_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        op.f("ix_source_connection_setup_draft_target_collection_id"),
        table_name="source_connection_setup_draft",
    )
    op.drop_index(
        op.f("ix_source_connection_setup_draft_provider_short_name"),
        table_name="source_connection_setup_draft",
    )
    op.drop_index(
        op.f("ix_source_connection_setup_draft_organization_id"),
        table_name="source_connection_setup_draft",
    )
    op.drop_table("source_connection_setup_draft")
