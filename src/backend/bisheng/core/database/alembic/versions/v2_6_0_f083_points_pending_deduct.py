"""积分补扣队列：违规删除后扣分失败可重试。

Revision ID: f083_points_pending_deduct
Revises: f082_points_perf_indexes
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "f083_points_pending_deduct"
down_revision = "f082_points_perf_indexes"
branch_labels = None
depends_on = None

TABLE = "point_pending_deduct"


def upgrade() -> None:
    """创建 point_pending_deduct；表已存在则跳过。"""
    bind = op.get_bind()
    if TABLE in inspect(bind).get_table_names():
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("rule_code", sa.String(length=32), nullable=False),
        sa.Column("biz_type", sa.String(length=32), nullable=False),
        sa.Column("biz_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("operator_id", sa.Integer(), nullable=True),
        sa.Column("remark", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("create_time", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("update_time", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uk_ppd_tenant_idem"),
    )
    op.create_index("ix_ppd_due", TABLE, ["status", "next_retry_at", "id"])


def downgrade() -> None:
    """删除补扣队列表。"""
    bind = op.get_bind()
    if TABLE not in inspect(bind).get_table_names():
        return
    op.drop_index("ix_ppd_due", table_name=TABLE)
    op.drop_table(TABLE)
