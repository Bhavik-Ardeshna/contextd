"""Add persisted Context Forge mapping artifacts.

Revision ID: 0005_context_forge_mapping
Revises: 0004_clickhouse_cursor
Create Date: 2026-05-01 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op


revision = "0005_context_forge_mapping"
down_revision = "0004_clickhouse_cursor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "context_forge_mapping",
        sa.Column("source_connection_id", sa.UUID(), nullable=True),
        sa.Column("setup_draft_id", sa.UUID(), nullable=True),
        sa.Column("target_collection_id", sa.String(), nullable=True),
        sa.Column("provider_short_name", sa.String(), nullable=False),
        sa.Column("source_name", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("generated_by", sa.String(), nullable=False),
        sa.Column("mapping_schema", sa.JSON(), nullable=False),
        sa.Column("graph_preview", sa.JSON(), nullable=False),
        sa.Column("schema_fingerprint", sa.JSON(), nullable=True),
        sa.Column("drift_snapshot", sa.JSON(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("modified_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_email", sa.String(), nullable=True),
        sa.Column("modified_by_email", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_connection_id"], ["source_connection.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["setup_draft_id"], ["source_connection_setup_draft.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_collection_id"], ["collection.readable_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_context_forge_mapping_organization_id"),
        "context_forge_mapping",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_context_forge_mapping_provider_short_name"),
        "context_forge_mapping",
        ["provider_short_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_context_forge_mapping_source_connection_id"),
        "context_forge_mapping",
        ["source_connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_context_forge_mapping_setup_draft_id"),
        "context_forge_mapping",
        ["setup_draft_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_context_forge_mapping_status"),
        "context_forge_mapping",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_context_forge_mapping_target_collection_id"),
        "context_forge_mapping",
        ["target_collection_id"],
        unique=False,
    )
    op.create_index(
        "ix_context_forge_mapping_source_version",
        "context_forge_mapping",
        ["organization_id", "source_connection_id", "version"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_context_forge_mapping_source_version", table_name="context_forge_mapping")
    op.drop_index(op.f("ix_context_forge_mapping_target_collection_id"), table_name="context_forge_mapping")
    op.drop_index(op.f("ix_context_forge_mapping_status"), table_name="context_forge_mapping")
    op.drop_index(op.f("ix_context_forge_mapping_setup_draft_id"), table_name="context_forge_mapping")
    op.drop_index(op.f("ix_context_forge_mapping_source_connection_id"), table_name="context_forge_mapping")
    op.drop_index(op.f("ix_context_forge_mapping_provider_short_name"), table_name="context_forge_mapping")
    op.drop_index(op.f("ix_context_forge_mapping_organization_id"), table_name="context_forge_mapping")
    op.drop_table("context_forge_mapping")
