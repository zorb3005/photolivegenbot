"""Align DB schema with external spec (aliases, ids, bonus_type).

Revision ID: g1h2i3j4align_spec
Revises: f0c1d2e3segment
Create Date: 2025-12-04
"""

from alembic import op
import sqlalchemy as sa


revision = "g1h2i3j4align_spec"
down_revision = "f0c1d2e3segment"
branch_labels = None
depends_on = None


def upgrade():
    # Users: add aliases to match spec wording
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS mail text GENERATED ALWAYS AS (email) STORED")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS balance integer GENERATED ALWAYS AS (balance_tokens) STORED")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_updated timestamptz GENERATED ALWAYS AS (updated_at) STORED")

    # Payments: add integer identity to align with spec (keep UUID id for backward compat)
    op.add_column("payments", sa.Column("id_int", sa.Integer(), sa.Identity(always=True), nullable=False))
    op.create_unique_constraint("uq_payments_id_int", "payments", ["id_int"])

    # Referral bonuses: align bonus_type vocabulary, add pay_id_int FK to payments.id_int
    op.add_column("referral_bonuses", sa.Column("pay_id_int", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_referral_bonuses_pay_id_int",
        source_table="referral_bonuses",
        referent_table="payments",
        local_cols=["pay_id_int"],
        remote_cols=["id_int"],
        ondelete="SET NULL",
    )

    op.execute("UPDATE referral_bonuses SET bonus_type = 'deposit' WHERE bonus_type = 'invite'")
    op.execute("UPDATE referral_bonuses SET bonus_type = 'generation' WHERE bonus_type = 'invitee'")
    op.execute("ALTER TABLE referral_bonuses ALTER COLUMN bonus_type SET DEFAULT 'deposit'")
    op.execute("ALTER TABLE referral_bonuses DROP CONSTRAINT IF EXISTS ck_referral_bonuses_bonus_type")
    op.execute(
        "ALTER TABLE referral_bonuses ADD CONSTRAINT ck_referral_bonuses_bonus_type CHECK (bonus_type IN ('deposit','generation'))"
    )


def downgrade():
    op.execute("ALTER TABLE referral_bonuses DROP CONSTRAINT IF EXISTS ck_referral_bonuses_bonus_type")
    op.execute("ALTER TABLE referral_bonuses ALTER COLUMN bonus_type DROP DEFAULT")
    op.drop_constraint("fk_referral_bonuses_pay_id_int", "referral_bonuses", type_="foreignkey")
    op.drop_column("referral_bonuses", "pay_id_int")

    op.drop_constraint("uq_payments_id_int", "payments", type_="unique")
    op.drop_column("payments", "id_int")

    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS mail")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS balance")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS last_updated")
