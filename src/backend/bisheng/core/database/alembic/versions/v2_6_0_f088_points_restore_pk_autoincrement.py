# ruff: noqa: RUF002, RUF003
"""补回积分表主键 AUTO_INCREMENT（f084 中断重跑曾把自增剥掉）。

Revision ID: f088_points_restore_pk_autoincrement
Revises: f086_merge_points_qa_images

f084 第一版用 ``op.alter_column`` 写 COMMENT，MySQL MODIFY 未带 AUTO_INCREMENT
会剥掉主键自增；随后 tenant_id DEFAULT 二次转义报 1067 中断，只有已处理到的
``user_point_account.id`` 中招。修复版又因 COMMENT 已是「主键」而跳过，自增
再也没补回。本迁移对全部积分主键做幂等补回。

达梦走 COMMENT ON COLUMN，不会剥 IDENTITY，此处跳过。
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import inspect

from bisheng.core.database.alembic.versions.v2_6_0_f084_points_column_comments import (
    _POINT_MODELS,
    _apply_mysql_comment,
    _column_needs_autoincrement,
)

revision: str = "f088_points_restore_pk_autoincrement"
down_revision: str | Sequence[str] | None = "f086_merge_points_qa_images"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """MySQL：主键缺 AUTO_INCREMENT 时 MODIFY 补回；已有则跳过。"""
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect not in ("mysql", "mariadb"):
        # 达梦 COMMENT ON COLUMN 不改变 IDENTITY；SQLite INTEGER PK 自增语义不同。
        return

    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    for model in _POINT_MODELS:
        table = model.__tablename__
        if table not in existing_tables:
            continue
        for column in model.__table__.columns:
            if not _column_needs_autoincrement(column):
                continue
            comment = column.comment or "主键"
            _apply_mysql_comment(
                bind,
                table,
                column.name,
                comment,
                needs_autoincrement=True,
            )


def downgrade() -> None:
    """自增是主键不变量，downgrade 不剥 AUTO_INCREMENT。"""
    return
