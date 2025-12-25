"""add internal_id to users

Revision ID: 7b1f8f5e4c1d
Revises: a1b2c3d4e5f6
Create Date: 2025-01-06
"""

from alembic import op
import sqlalchemy as sa


revision = "7b1f8f5e4c1d"
down_revision = "d1a2b3c4voice"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE SEQUENCE IF NOT EXISTS users_internal_id_seq")

    op.add_column(
        "users",
        sa.Column("internal_id", sa.Integer(), nullable=True, server_default=sa.text("nextval('users_internal_id_seq')")),
    )

    op.execute("UPDATE users SET internal_id = nextval('users_internal_id_seq') WHERE internal_id IS NULL")
    op.alter_column(
        "users",
        "internal_id",
        nullable=False,
        server_default=sa.text("nextval('users_internal_id_seq')"),
    )
    op.create_unique_constraint("uq_users_internal_id", "users", ["internal_id"])
    op.execute("ALTER SEQUENCE users_internal_id_seq OWNED BY users.internal_id")


def downgrade():
    op.drop_constraint("uq_users_internal_id", "users", type_="unique")
    op.drop_column("users", "internal_id")
    op.execute("DROP SEQUENCE IF EXISTS users_internal_id_seq")
