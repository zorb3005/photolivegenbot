from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "f9c7face1159" 
branch_labels = None
depends_on = None


def upgrade():
    # База уже имеет FK из первой миграции, поэтому здесь только гарантируем расширение
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")


def downgrade():
    op.execute("ALTER TABLE payments DROP CONSTRAINT IF EXISTS fk_payments_user")
