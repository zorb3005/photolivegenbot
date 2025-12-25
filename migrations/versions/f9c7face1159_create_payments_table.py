from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as psql

# Идентификаторы ревизии
revision = "f9c7face1159"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # 1) Устанавливаем расширение pgcrypto (для gen_random_uuid)
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # 2) Таблица пользователей
    op.create_table(
        "users",
        sa.Column("telegram_id", sa.BigInteger(), primary_key=True),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("balance_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("friends_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", psql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", psql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=False)
    op.create_index("ix_users_balance_tokens", "users", ["balance_tokens"], unique=False)

    # 3) Таблица платежей
    op.create_table(
        "payments",
        sa.Column(
            "id",
            psql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),  # telegram user_id
        sa.Column("payment_id", sa.Text(), unique=True, nullable=True),  # YooKassa payment.id
        sa.Column("amount_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("rub_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False, server_default=sa.text("'RUB'")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column(
            "metadata",
            psql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", psql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", psql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_index("ix_payments_user_id", "payments", ["user_id"])
    op.create_index("ix_payments_status", "payments", ["status"])

    # 4) Внешний ключ user_id → users.telegram_id
    op.create_foreign_key(
        "fk_payments_user",
        "payments",
        "users",
        ["user_id"],
        ["telegram_id"],
        ondelete="CASCADE",
    )


def downgrade():
    # Удаляем связи и таблицы в обратном порядке
    op.drop_constraint("fk_payments_user", "payments", type_="foreignkey")
    op.drop_index("ix_payments_status", table_name="payments")
    op.drop_index("ix_payments_user_id", table_name="payments")
    op.drop_table("payments")

    op.drop_index("ix_users_balance_tokens", table_name="users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
