"""add email to users

Revision ID: c7e3e4c1add
Revises: b123free_tier_used
Create Date: 2025-03-01
"""

from alembic import op
import sqlalchemy as sa


revision = "c7e3e4c1add"
down_revision = "b123free_tier_used"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("email", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("users", "email")
