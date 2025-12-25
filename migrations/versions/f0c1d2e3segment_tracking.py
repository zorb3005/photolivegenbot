"""Add user segmentation, sources, referrals, and generation history.

Revision ID: f0c1d2e3segment
Revises: c7e3e4c1add
Create Date: 2025-05-15
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as psql


revision = "f0c1d2e3segment"
down_revision = "c7e3e4c1add"
branch_labels = None
depends_on = None


def upgrade():
    # --- users additions ---
    op.add_column("users", sa.Column("first_name", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column("segment", sa.Text(), nullable=False, server_default=sa.text("'lead'")),
    )
    op.add_column("users", sa.Column("referred_id", sa.Integer(), nullable=True))
    op.create_index("ix_users_segment", "users", ["segment"], unique=False)

    # backfill segment/referred_id where possible
    op.execute("UPDATE users SET segment = COALESCE(segment, 'lead')")
    op.execute(
        """
        UPDATE users AS u
           SET referred_id = ref.internal_id
          FROM users AS ref
         WHERE u.invited_by = ref.telegram_id
        """
    )

    # --- user_sources ---
    op.create_table(
        "user_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=True),
        sa.Column("source_value", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            psql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.telegram_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_user_sources_user"),
    )
    op.create_index("ix_user_sources_user_id", "user_sources", ["user_id"], unique=False)

    # --- segment_history ---
    op.create_table(
        "segment_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("segment", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            psql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.telegram_id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_segment_history_user_id", "segment_history", ["user_id"], unique=False
    )

    # --- referral_bonuses ---
    op.create_table(
        "referral_bonuses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ref_id", sa.Integer(), nullable=True),
        sa.Column("referrer_user_id", sa.BigInteger(), nullable=True),
        sa.Column("referred_user_id", sa.BigInteger(), nullable=False),
        sa.Column("bonus_type", sa.Text(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deposit_rub_amount", sa.Integer(), nullable=True),
        sa.Column("deposit_token_amount", sa.Integer(), nullable=True),
        sa.Column("pay_id", psql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            psql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["referrer_user_id"], ["users.telegram_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["referred_user_id"], ["users.telegram_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pay_id"], ["payments.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_referral_bonuses_referrer",
        "referral_bonuses",
        ["referrer_user_id"],
        unique=False,
    )

    # --- generation_history ---
    op.create_table(
        "generation_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "timestamp",
            psql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("request", sa.Text(), nullable=True),
        sa.Column("cost", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("generation_type", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.telegram_id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_generation_history_user_id", "generation_history", ["user_id"], unique=False
    )


def downgrade():
    op.drop_index("ix_generation_history_user_id", table_name="generation_history")
    op.drop_table("generation_history")

    op.drop_index("ix_referral_bonuses_referrer", table_name="referral_bonuses")
    op.drop_table("referral_bonuses")

    op.drop_index("ix_segment_history_user_id", table_name="segment_history")
    op.drop_table("segment_history")

    op.drop_index("ix_user_sources_user_id", table_name="user_sources")
    op.drop_table("user_sources")

    op.drop_index("ix_users_segment", table_name="users")
    op.drop_column("users", "referred_id")
    op.drop_column("users", "segment")
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
