"""Add approval notification outbox.

Revision ID: f058_approval_notification_outbox
Revises: f057_knowledge_space_user_link_pin
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import (
    UPDATE_TIME_SERVER_DEFAULT,
    JsonType,
    index_exists,
    table_exists,
)

revision: str = "f058_approval_notification_outbox"
down_revision: str | Sequence[str] | None = "f057_knowledge_space_user_link_pin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "approval_notification_outbox"
_DISPATCH_INDEX = "idx_approval_notification_outbox_dispatch"


def upgrade() -> None:
    connection = op.get_bind()
    if not table_exists(connection, _TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("instance_id", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(64), nullable=False),
            sa.Column(
                "status",
                sa.String(32),
                nullable=False,
                server_default=sa.text("'pending'"),
            ),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("max_retries", sa.Integer(), nullable=False, server_default=sa.text("3")),
            sa.Column("payload_snapshot", JsonType(), nullable=False),
            sa.Column("error_summary", sa.Text(), nullable=True),
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
            sa.UniqueConstraint(
                "tenant_id",
                "instance_id",
                "event_type",
                name="uk_approval_notification_outbox_event",
            ),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
        )
    if not index_exists(connection, _TABLE, _DISPATCH_INDEX):
        op.create_index(
            _DISPATCH_INDEX,
            _TABLE,
            ["status", "retry_count", "update_time"],
            unique=False,
        )


def downgrade() -> None:
    connection = op.get_bind()
    if table_exists(connection, _TABLE):
        op.drop_table(_TABLE)
