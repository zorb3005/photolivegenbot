"""add invited_by to users

Revision ID: c5c1b0e0866a
Revises: b3f4e5d6c7ab
Create Date: 2025-02-13
"""

from alembic import op
import sqlalchemy as sa


revision = "c5c1b0e0866a"
down_revision = "b3f4e5d6c7ab"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("invited_by", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_users_invited_by",
        source_table="users",
        referent_table="users",
        local_cols=["invited_by"],
        remote_cols=["telegram_id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_users_invited_by", "users", type_="foreignkey")
    op.drop_column("users", "invited_by")

