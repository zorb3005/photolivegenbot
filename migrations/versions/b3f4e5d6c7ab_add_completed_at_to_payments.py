"""add completed_at to payments

Revision ID: b3f4e5d6c7ab
Revises: a1b2c3d4e5f6
Create Date: 2025-02-13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as psql

revision = "b3f4e5d6c7ab"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "payments",
        sa.Column(
            "completed_at",
            psql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_column("payments", "completed_at")

