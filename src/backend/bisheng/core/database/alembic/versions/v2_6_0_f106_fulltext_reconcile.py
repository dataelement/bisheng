"""新增每日全文对账进度和失败登记, 不执行数据对账。"""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import JsonType, index_exists, table_exists

revision = "f106_fulltext_reconcile"
down_revision = "f058_dashboard_dataset_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not table_exists(bind, "knowledge_fulltext_reconcile_run"):
        op.create_table(
            "knowledge_fulltext_reconcile_run",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("day", sa.String(10), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("phase", sa.String(16), nullable=False),
            sa.Column("cursor", sa.BigInteger(), nullable=False),
            sa.Column("upper_id", sa.BigInteger(), nullable=False),
            sa.Column("counters", JsonType(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if not index_exists(bind, "knowledge_fulltext_reconcile_run", "ix_knowledge_fulltext_reconcile_run_day"):
        op.create_index("ix_knowledge_fulltext_reconcile_run_day", "knowledge_fulltext_reconcile_run", ["day"])
    if not table_exists(bind, "knowledge_fulltext_reconcile_issue"):
        op.create_table(
            "knowledge_fulltext_reconcile_issue",
            sa.Column("run_id", sa.String(32), primary_key=True),
            sa.Column("file_id", sa.BigInteger(), primary_key=True),
            sa.Column("status", sa.String(24), nullable=False),
            sa.Column("reason", sa.String(128), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("next_retry_at", sa.DateTime()),
            sa.Column("fingerprint", sa.String(64)),
            sa.Column("task_id", sa.String(64)),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if not index_exists(bind, "knowledge_fulltext_reconcile_issue", "ix_kfri_due"):
        op.create_index("ix_kfri_due", "knowledge_fulltext_reconcile_issue", ["run_id", "status", "next_retry_at"])


def downgrade() -> None:
    for table in ("knowledge_fulltext_reconcile_issue", "knowledge_fulltext_reconcile_run"):
        if table_exists(op.get_bind(), table):
            op.drop_table(table)
