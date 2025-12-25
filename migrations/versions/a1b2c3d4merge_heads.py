"""merge heads e3d9f5c1add and 7b1f8f5e4c1d

Revision ID: a1b2c3d4merge
Revises: e3d9f5c1add, 7b1f8f5e4c1d
Create Date: 2025-02-14
"""

from alembic import op

revision = "a1b2c3d4merge"
down_revision = ("e3d9f5c1add", "7b1f8f5e4c1d")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
