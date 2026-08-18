# ruff: noqa: RUF002
"""去掉 qa_publish_request.updated_at 的 ON UPDATE CURRENT_TIMESTAMP。

Revision ID: f091_qa_expert_beijing_datetime
Revises: f090_merge_f083_f087_f089
Create Date: 2026-08-18

应用侧改为东八墙钟写入后，MySQL ON UPDATE CURRENT_TIMESTAMP 会按会话/服务器时区刷新，
与 Python now_beijing() 混钟。本 revision 只改列定义，不平移存量 DATETIME。
生产未启用专家问答；测试环境旧行若仍是 UTC naive，展示可能偏 8 小时，按产品确认不回填。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, table_exists

revision: str = "f091_qa_expert_beijing_datetime"
down_revision: str | Sequence[str] | None = "f090_merge_f083_f087_f089"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def drop_publish_updated_at_on_update(bind) -> None:
    """去掉 ON UPDATE CURRENT_TIMESTAMP，避免与 Python 东八写入再混钟。"""
    if not table_exists(bind, "qa_publish_request"):
        return
    if not column_exists(bind, "qa_publish_request", "updated_at"):
        return
    dialect = bind.dialect.name
    if dialect in ("mysql", "mariadb"):
        bind.execute(
            sa.text(
                "ALTER TABLE qa_publish_request "
                "MODIFY COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP "
                "COMMENT '更新时间'"
            )
        )


def restore_publish_updated_at_on_update(bind) -> None:
    """downgrade：恢复 MySQL ON UPDATE。"""
    if not table_exists(bind, "qa_publish_request"):
        return
    if not column_exists(bind, "qa_publish_request", "updated_at"):
        return
    dialect = bind.dialect.name
    if dialect in ("mysql", "mariadb"):
        bind.execute(
            sa.text(
                "ALTER TABLE qa_publish_request "
                "MODIFY COLUMN updated_at DATETIME NOT NULL "
                "DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP "
                "COMMENT '更新时间'"
            )
        )


def upgrade() -> None:
    """只改转公开 updated_at 列定义，不 UPDATE 历史行。"""
    drop_publish_updated_at_on_update(op.get_bind())


def downgrade() -> None:
    """恢复 ON UPDATE。"""
    restore_publish_updated_at_on_update(op.get_bind())
