"""add voice fields to users

Revision ID: d1a2b3c4voice
Revises: c5c1b0e0866a
Create Date: 2025-02-13
"""

from alembic import op
import sqlalchemy as sa


revision = "d1a2b3c4voice"
down_revision = "c5c1b0e0866a"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("voice_id", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("voice_name", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("voice_category", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("users", "voice_category")
    op.drop_column("users", "voice_name")
    op.drop_column("users", "voice_id")
