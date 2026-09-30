"""持久化迁移批次的自动恢复预算和退避时间。"""

import sqlalchemy as sa
from alembic import op

revision = "f107_migration_reconcile_budget"
down_revision = "f106_fulltext_reconcile"
branch_labels = None
depends_on = None

_TABLE = "knowledge_migration_batch"


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(_TABLE)}
    if "reconcile_count" not in columns:
        op.add_column(_TABLE, sa.Column("reconcile_count", sa.Integer(), nullable=False, server_default=sa.text("0")))
    if "next_reconcile_at" not in columns:
        op.add_column(_TABLE, sa.Column("next_reconcile_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(_TABLE)}
    for name in ("next_reconcile_at", "reconcile_count"):
        if name in columns:
            op.drop_column(_TABLE, name)
