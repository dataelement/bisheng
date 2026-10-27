"""审计列表: 会话增加回答过程是否异常.

Revision ID: f120_message_session_answer_abnormal
Revises: f119_abnormal_upload_status_index

历史消息里已经记下的超时, 工具失败和错误标记会回填到 message_session.answer_abnormal.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, table_exists
from bisheng.database.models.answer_failure import payload_has_answer_failure

revision: str = "f120_message_session_answer_abnormal"
down_revision: str | Sequence[str] | None = "f119_abnormal_upload_status_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SESSION = "message_session"
_COLUMN = "answer_abnormal"


def upgrade() -> None:
    """增加可筛选的异常标记, 并按已落库的回答失败回填."""
    bind = op.get_bind()
    if not table_exists(bind, _SESSION):
        return
    if not column_exists(bind, _SESSION, _COLUMN):
        op.add_column(
            _SESSION,
            sa.Column(
                _COLUMN,
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
                comment="回答过程是否出现失败: 0否 1是",
            ),
        )
    _backfill(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if table_exists(bind, _SESSION) and column_exists(bind, _SESSION, _COLUMN):
        op.drop_column(_SESSION, _COLUMN)


def _backfill(bind) -> None:
    if not table_exists(bind, "chatmessage"):
        return
    message = sa.table(
        "chatmessage",
        sa.column("id"),
        sa.column("chat_id"),
        sa.column("is_bot"),
        sa.column("category"),
        sa.column("extra"),
        sa.column("message"),
    )
    last_id = 0
    while True:
        rows = bind.execute(
            sa.select(
                message.c.id,
                message.c.chat_id,
                message.c.is_bot,
                message.c.category,
                message.c.extra,
                message.c.message,
            )
            .where(message.c.id > last_id)
            .order_by(message.c.id)
            .limit(200)
        ).fetchall()
        if not rows:
            return
        failed_chats: list[str] = []
        for row in rows:
            last_id = row.id
            if not row.chat_id:
                continue
            if payload_has_answer_failure(
                is_bot=bool(row.is_bot),
                category=row.category or "",
                extra=row.extra,
                message=row.message,
            ):
                failed_chats.append(row.chat_id)
        if not failed_chats:
            continue
        update = sa.text(
            "UPDATE message_session SET answer_abnormal = 1 WHERE answer_abnormal = 0 AND chat_id IN :chat_ids"
        ).bindparams(sa.bindparam("chat_ids", expanding=True))
        bind.execute(update, {"chat_ids": list(dict.fromkeys(failed_chats))})
