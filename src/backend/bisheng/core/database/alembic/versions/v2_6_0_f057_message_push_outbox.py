"""F057: add message_push_outbox table for Shougang enterprise WeChat push.

Revision ID: f057_message_push_outbox
Revises: f056_user_wechat_user_id
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import (
    UPDATE_TIME_SERVER_DEFAULT,
    JsonType,
    LargeText,
    index_exists,
    table_exists,
)

revision: str = "f057_message_push_outbox"
down_revision: Union[str, Sequence[str], None] = "f056_user_wechat_user_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE_NAME = "message_push_outbox"

_INDEXES = {
    "ix_message_push_outbox_tenant_id": ["tenant_id"],
    "ix_message_push_outbox_status_next_retry_at": ["status", "next_retry_at"],
    "ix_message_push_outbox_inbox_message_id": ["inbox_message_id"],
    "ix_message_push_outbox_action_code": ["action_code"],
}


def _create_table() -> None:
    op.create_table(
        _TABLE_NAME,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
            comment="Tenant ID",
        ),
        sa.Column("inbox_message_id", sa.Integer(), nullable=True),
        sa.Column("action_code", sa.String(length=64), nullable=False),
        sa.Column("receiver_user_ids", JsonType, nullable=False),
        sa.Column("wechat_user_ids", JsonType, nullable=False),
        sa.Column("body", LargeText, nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_retries", sa.Integer(),nullable=False,server_default=sa.text("3")),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("failure_reason", LargeText, nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column(
            "create_time",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "update_time",
            sa.DateTime(),
            nullable=False,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
        ),
    )


def upgrade() -> None:
    conn = op.get_bind()
    if not table_exists(conn, _TABLE_NAME):
        _create_table()

    for index_name, columns in _INDEXES.items():
        if not index_exists(conn, _TABLE_NAME, index_name):
            op.create_index(index_name, _TABLE_NAME, columns, unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    if table_exists(conn, _TABLE_NAME):
        op.drop_table(_TABLE_NAME)
