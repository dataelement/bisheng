"""审计异常不再包含未使用的工具准备失败.

Revision ID: f121_answer_abnormal_prep_failure
Revises: f120_message_session_answer_abnormal

只把已经标成异常、按新规则不再命中的会话改回 0.
显式写回 update_time, 避免工作台会话列表被刷新到最前.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, table_exists
from bisheng.database.models.answer_failure import payload_has_answer_failure

revision: str = "f121_answer_abnormal_prep_failure"
down_revision: str | Sequence[str] | None = "f120_message_session_answer_abnormal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SESSION = "message_session"
_COLUMN = "answer_abnormal"
_COMMENT = "任务是否异常: 0否 1是. 工具准备失败且执行中未使用不算"
_OLD_COMMENT = "回答过程是否出现失败: 0否 1是"


def upgrade() -> None:
    """按新规则清掉误标, 并更新列注释."""
    bind = op.get_bind()
    if not table_exists(bind, _SESSION) or not column_exists(bind, _SESSION, _COLUMN):
        return
    _alter_comment(_COMMENT)
    _clear_false_positives(bind)


def downgrade() -> None:
    """只恢复列注释. 已经改回 0 的会话不按旧规则再标成 1."""
    bind = op.get_bind()
    if table_exists(bind, _SESSION) and column_exists(bind, _SESSION, _COLUMN):
        _alter_comment(_OLD_COMMENT)


def _alter_comment(comment: str) -> None:
    op.alter_column(
        _SESSION,
        _COLUMN,
        existing_type=sa.Integer(),
        existing_nullable=False,
        existing_server_default=sa.text("0"),
        comment=comment,
    )


def _clear_false_positives(bind) -> None:
    if not table_exists(bind, "chatmessage"):
        return
    session = sa.table(_SESSION, sa.column("chat_id"), sa.column(_COLUMN))
    chat_ids = [
        row.chat_id
        for row in bind.execute(sa.select(session.c.chat_id).where(session.c.answer_abnormal == 1)).fetchall()
        if row.chat_id
    ]
    clear_ids = [chat_id for chat_id in chat_ids if not _still_abnormal(bind, chat_id)]
    if not clear_ids:
        return
    # 同一赋值挡住 ON UPDATE CURRENT_TIMESTAMP, 会话排序用的更新时间保持原值.
    update = sa.text(
        "UPDATE message_session SET answer_abnormal = 0, update_time = update_time "
        "WHERE answer_abnormal = 1 AND chat_id IN :chat_ids"
    ).bindparams(sa.bindparam("chat_ids", expanding=True))
    bind.execute(update, {"chat_ids": clear_ids})


def _still_abnormal(bind, chat_id: str) -> bool:
    message = sa.table(
        "chatmessage",
        sa.column("is_bot"),
        sa.column("category"),
        sa.column("extra"),
        sa.column("message"),
        sa.column("chat_id"),
    )
    rows = bind.execute(
        sa.select(
            message.c.is_bot,
            message.c.category,
            message.c.extra,
            message.c.message,
        ).where(message.c.chat_id == chat_id)
    ).fetchall()
    return any(
        payload_has_answer_failure(
            is_bot=bool(row.is_bot),
            category=row.category or "",
            extra=row.extra,
            message=row.message,
        )
        for row in rows
    )
