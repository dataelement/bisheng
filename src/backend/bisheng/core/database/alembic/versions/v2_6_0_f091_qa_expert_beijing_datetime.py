# ruff: noqa: RUF002, RUF003
"""专家问答 DATETIME：存量 UTC 墙钟平移为东八区，并去掉 qa_publish_request.updated_at 的 ON UPDATE。

Revision ID: f091_qa_expert_beijing_datetime
Revises: f090_merge_f083_f087_f089
Create Date: 2026-08-18

历史行按 naive=UTC 一次性 +8 小时。禁止重复 upgrade。应用必须与本 migration 同窗口发布，
否则 expire_at 与 now() 会短暂混钟。
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.common.utils.beijing_time import shift_stored_iso
from bisheng.core.database.dialect_helpers import column_exists, table_exists

revision: str = "f091_qa_expert_beijing_datetime"
down_revision: str | Sequence[str] | None = "f090_merge_f083_f087_f089"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

QA_PUBLISH_SCENARIO = "qa_question_publish"

QA_DATETIME_COLUMNS: dict[str, tuple[str, ...]] = {
    "qa_expert": ("created_at", "updated_at"),
    "qa_question": ("created_at", "updated_at", "resolved_at"),
    "qa_answer": ("created_at", "updated_at"),
    "qa_comment": ("created_at",),
    "qa_question_invite": ("created_at",),
    "qa_answer_adopt": ("created_at",),
    "qa_anonymous_alias": ("created_at",),
    "qa_answer_eligibility": ("created_at",),
    "qa_publish_request": ("expire_at", "created_at", "updated_at"),
    "qa_publish_approver": ("decided_at", "created_at"),
    "qa_question_vote": ("created_at",),
    "qa_answer_vote": ("created_at",),
    "qa_comment_vote": ("created_at",),
    "qa_notification": ("created_at",),
}


def add_hours_sql(column: str, dialect: str, hours: int) -> str:
    """生成把 DATETIME 列平移 hours 小时的 SQL 片段。"""
    signed = int(hours)
    if dialect in ("mysql", "mariadb"):
        if signed >= 0:
            return f"DATE_ADD(`{column}`, INTERVAL {signed} HOUR)"
        return f"DATE_SUB(`{column}`, INTERVAL {abs(signed)} HOUR)"
    if dialect == "sqlite":
        sign = "+" if signed >= 0 else "-"
        return f"datetime({column}, '{sign}{abs(signed)} hours')"
    # 达梦 / Oracle 兼容：按天的小数相加
    return f"{column} + ({signed}/24.0)"


def shift_table_datetimes(bind, table: str, columns: tuple[str, ...], hours: int) -> None:
    """把表内已有 DATETIME 列平移；缺表/缺列跳过。"""
    if not table_exists(bind, table):
        return
    dialect = bind.dialect.name
    assignments = []
    for column in columns:
        if not column_exists(bind, table, column):
            continue
        assignments.append(f"{column} = {add_hours_sql(column, dialect, hours)}")
    if not assignments:
        return
    bind.execute(sa.text(f"UPDATE {table} SET {', '.join(assignments)}"))


def _parse_json(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None
    return None


def _shift_expire_keys(value, hours: int):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key == "expire_at" and isinstance(item, str):
                out[key] = shift_stored_iso(item, hours=hours)
            else:
                out[key] = _shift_expire_keys(item, hours)
        return out
    if isinstance(value, list):
        return [_shift_expire_keys(item, hours) for item in value]
    return value


def shift_publish_approval_snapshots(bind, hours: int) -> None:
    """转公开审批快照里的 expire_at 与 qa_publish_request 同步平移。"""
    if not table_exists(bind, "approval_instance"):
        return
    if not column_exists(bind, "approval_instance", "payload_snapshot"):
        return
    rows = bind.execute(
        sa.text(
            """
            SELECT id, payload_snapshot, detail_snapshot
            FROM approval_instance
            WHERE scenario_code = :code
            """
        ),
        {"code": QA_PUBLISH_SCENARIO},
    ).fetchall()
    for row in rows:
        payload = _shift_expire_keys(_parse_json(row[1]), hours)
        detail = _shift_expire_keys(_parse_json(row[2]), hours)
        if payload is None and detail is None:
            continue
        dialect = bind.dialect.name
        if dialect in ("mysql", "mariadb"):
            sql = """
                UPDATE approval_instance
                SET payload_snapshot = CAST(:payload AS JSON),
                    detail_snapshot = CAST(:detail AS JSON)
                WHERE id = :id
            """
        else:
            sql = """
                UPDATE approval_instance
                SET payload_snapshot = :payload, detail_snapshot = :detail
                WHERE id = :id
            """
        bind.execute(
            sa.text(sql),
            {
                "id": row[0],
                "payload": json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                "detail": json.dumps(detail, ensure_ascii=False) if detail is not None else None,
            },
        )


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
    """存量 +8 小时，并去掉转公开 updated_at 的库侧自动刷新。"""
    bind = op.get_bind()
    for table, columns in QA_DATETIME_COLUMNS.items():
        shift_table_datetimes(bind, table, columns, hours=8)
    shift_publish_approval_snapshots(bind, hours=8)
    drop_publish_updated_at_on_update(bind)


def downgrade() -> None:
    """反向 −8 小时并恢复 ON UPDATE（会回到 UTC naive）。"""
    bind = op.get_bind()
    restore_publish_updated_at_on_update(bind)
    shift_publish_approval_snapshots(bind, hours=-8)
    for table, columns in QA_DATETIME_COLUMNS.items():
        shift_table_datetimes(bind, table, columns, hours=-8)
