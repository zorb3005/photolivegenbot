"""add free_tier_used flag to users

Revision ID: b123free_tier_used
Revises: a1b2c3d4merge
Create Date: 2025-02-14
"""

from alembic import op
import sqlalchemy as sa


revision = "b123free_tier_used"
down_revision = "a1b2c3d4merge"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column(
            "free_tier_used",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.alter_column("users", "free_tier_used", server_default=None)


def downgrade():
    op.drop_column("users", "free_tier_used")
