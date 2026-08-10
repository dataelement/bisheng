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


def _apply_mysql_comment(bind, table: str, column: str, comment: str) -> None:
    """MySQL/MariaDB：用 information_schema 拼 MODIFY，避免 alter_column 二次转义 DEFAULT。

    inspector 返回的 default 形如 ``'1'``（已含引号）；若原样传给
    ``existing_server_default`` 会变成 ``DEFAULT '''1'''`` 并触发 1067。
    同时保留 EXTRA（如 ON UPDATE CURRENT_TIMESTAMP / auto_increment）。
    """
    row = bind.execute(
        sa.text(
            """
            SELECT COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, EXTRA, COLUMN_COMMENT
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :table
              AND COLUMN_NAME = :column
            """
        ),
        {"table": table, "column": column},
    ).mappings().first()
    if row is None:
        return
    # 已是目标文案则跳过，支持中断后重跑
    if (row["COLUMN_COMMENT"] or "") == comment:
        return

    null_sql = "NULL" if row["IS_NULLABLE"] == "YES" else "NOT NULL"
    default = row["COLUMN_DEFAULT"]
    # MySQL 8 EXTRA 可能含 DEFAULT_GENERATED，不能原样拼进 MODIFY
    extra_l = (row["EXTRA"] or "").lower()
    parts = [f"ALTER TABLE `{table}` MODIFY COLUMN `{column}` {row['COLUMN_TYPE']} {null_sql}"]

    if default is not None:
        # CURRENT_TIMESTAMP 等函数默认值不能再加引号；普通标量按字符串字面量写入
        upper = str(default).upper()
        if upper in ("CURRENT_TIMESTAMP", "CURRENT_TIMESTAMP()", "NULL") or upper.startswith(
            "CURRENT_TIMESTAMP"
        ):
            parts.append(f"DEFAULT {default}")
        else:
            parts.append(f"DEFAULT '{_escape_sql_literal(str(default))}'")
    if "auto_increment" in extra_l:
        parts.append("AUTO_INCREMENT")
    if "on update current_timestamp" in extra_l:
        parts.append("ON UPDATE CURRENT_TIMESTAMP")
    parts.append(f"COMMENT '{_escape_sql_literal(comment)}'")
    op.execute(sa.text(" ".join(parts)))


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
                # mysql / mariadb
                _apply_mysql_comment(bind, table, name, comment)


def downgrade() -> None:
    """注释为文档元数据，downgrade 不强制清空（避免误伤手工维护的库注释）。"""
    return
