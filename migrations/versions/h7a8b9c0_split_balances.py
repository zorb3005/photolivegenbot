"""split balances for animate/avatar

Revision ID: h7a8b9c0split
Revises: g1h2i3j4align_spec
Create Date: 2025-02-14
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "h7a8b9c0split"
down_revision = "g1h2i3j4align_spec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("animate_balance_tokens", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("avatar_balance_tokens", sa.Integer(), nullable=False, server_default="0"))
    op.execute("UPDATE users SET animate_balance_tokens = balance_tokens, avatar_balance_tokens = 0, balance_tokens = 0")
    op.alter_column("users", "animate_balance_tokens", server_default=None)
    op.alter_column("users", "avatar_balance_tokens", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "avatar_balance_tokens")
    op.drop_column("users", "animate_balance_tokens")
