"""Enable PostgreSQL cursor-aware source metadata.

Revision ID: 0003_pg_cursor
Revises: 0002_setup_draft
Create Date: 2026-05-01 00:00:00.000000

"""

from alembic import op


revision = "0003_pg_cursor"
down_revision = "0002_setup_draft"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE source
        SET supports_continuous = true,
            modified_at = now()
        WHERE short_name = 'postgresql'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE source
        SET supports_continuous = false,
            modified_at = now()
        WHERE short_name = 'postgresql'
        """
    )
