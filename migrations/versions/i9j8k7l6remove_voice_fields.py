"""remove voice fields from users

Revision ID: i9j8k7l6remove
Revises: h7a8b9c0split
Create Date: 2026-02-26
"""

from alembic import op
import sqlalchemy as sa


revision = "i9j8k7l6remove"
down_revision = "h7a8b9c0split"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("users", "voice_id")
    op.drop_column("users", "voice_name")
    op.drop_column("users", "voice_category")


def downgrade() -> None:
    op.add_column("users", sa.Column("voice_category", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("voice_name", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("voice_id", sa.Text(), nullable=True))
