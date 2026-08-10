"""为全部积分表列补齐中文 COMMENT（库侧字段说明）。

Revision ID: f084_points_column_comments
Revises: f083_points_pending_deduct

无新增/删除列；仅更新 COMMENT。注释文案以 ORM ``Column(comment=...)`` 为准。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

from bisheng.points.domain.models import (
    PointCopy,
    PointFavoriteTierAward,
    PointPendingDeduct,
    PointRankSnapshot,
    PointRule,
    PointSyncOutbox,
    UserPointAccount,
    UserPointLog,
)

revision = "f084_points_column_comments"
down_revision = "f083_points_pending_deduct"
branch_labels = None
depends_on = None

_POINT_MODELS = (
    UserPointAccount,
    UserPointLog,
    PointRule,
    PointCopy,
    PointRankSnapshot,
    PointFavoriteTierAward,
    PointPendingDeduct,
    PointSyncOutbox,
)


def _escape_sql_literal(value: str) -> str:
    """转义单引号，供 COMMENT 字面量使用。"""
    return value.replace("'", "''")


def _apply_mysql_comment(table: str, column: str, comment: str, col_info: dict) -> None:
    """MySQL/MariaDB：通过 alter_column 写入 comment，保留既有类型与可空性。"""
    op.alter_column(
        table,
        column,
        existing_type=col_info["type"],
        existing_nullable=col_info["nullable"],
        existing_server_default=col_info.get("default"),
        comment=comment,
    )


def _apply_dm_comment(table: str, column: str, comment: str) -> None:
    """达梦/Oracle 风格：COMMENT ON COLUMN。"""
    escaped = _escape_sql_literal(comment)
    op.execute(sa.text(f'COMMENT ON COLUMN "{table}"."{column}" IS \'{escaped}\''))


def upgrade() -> None:
    """按 ORM 中的 Column.comment 为已存在的积分表列补注释。"""
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "sqlite":
        # SQLite 无稳定列注释语义，跳过
        return

    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for model in _POINT_MODELS:
        table = model.__tablename__
        if table not in existing_tables:
            continue
        col_by_name = {c["name"]: c for c in inspector.get_columns(table)}
        for column in model.__table__.columns:
            comment = column.comment
            if not comment:
                continue
            name = column.name
            if name not in col_by_name:
                continue
            if dialect in ("dm", "oracle"):
                _apply_dm_comment(table, name, comment)
            else:
                # mysql / mariadb / 其他支持 alter_column comment 的方言
                _apply_mysql_comment(table, name, comment, col_by_name[name])


def downgrade() -> None:
    """注释为文档元数据，downgrade 不强制清空（避免误伤手工维护的库注释）。"""
    return
