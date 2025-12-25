"""add clone_unlimited flag to users

Revision ID: e3d9f5c1add
Revises: d1a2b3c4voice
Create Date: 2025-02-14
"""

from alembic import op
import sqlalchemy as sa


revision = "e3d9f5c1add"
down_revision = "d1a2b3c4voice"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column(
            "clone_unlimited",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Remove server_default to avoid future writes with explicit True/False only
    op.alter_column("users", "clone_unlimited", server_default=None)


def downgrade():
    op.drop_column("users", "clone_unlimited")
