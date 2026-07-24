"""新增调岗知识权限回收事件与回收项。

Revision ID: f070_department_transfer_permission_cleanup
Revises: f067_add_knowledge_file_alias_name, f067_clinic_space_level_team_ks,
         f069_department_space_binding_backfill
Create Date: 2026-07-24
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

revision: str = "f070_department_transfer_permission_cleanup"
down_revision: str | Sequence[str] | None = (
    "f067_add_knowledge_file_alias_name",
    "f067_clinic_space_level_team_ks",
    "f069_department_space_binding_backfill",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVENT_TABLE = "department_transfer_permission_cleanup_event"
ITEM_TABLE = "department_transfer_permission_cleanup_item"


def _create_index(table_name: str, name: str, columns: list[str]) -> None:
    connection = op.get_bind()
    if not index_exists(connection, table_name, name):
        op.create_index(name, table_name, columns, unique=False)


def upgrade() -> None:
    connection = op.get_bind()
    if not table_exists(connection, EVENT_TABLE):
        op.create_table(
            EVENT_TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False, autoincrement=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("event_key", sa.String(128), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("old_department_id", sa.Integer(), nullable=False),
            sa.Column("new_department_id", sa.Integer(), nullable=False),
            sa.Column("trigger_source", sa.String(32), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default=sa.text("'preparing'")),
            sa.Column(
                "requested_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("changed_at", sa.DateTime(), nullable=True),
            sa.Column("deadline_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("overdue_at", sa.DateTime(), nullable=True),
            sa.Column("next_retry_at", sa.DateTime(), nullable=True),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("snapshot_complete", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("total_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("revoked_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("protected_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("skipped_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("failed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("last_error", sa.Text(), nullable=True),
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
            sa.UniqueConstraint("event_key", name="uk_dtpc_event_key"),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
        )

    if not table_exists(connection, ITEM_TABLE):
        op.create_table(
            ITEM_TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False, autoincrement=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("event_id", sa.Integer(), nullable=False),
            sa.Column("item_key", sa.String(255), nullable=False),
            sa.Column("item_type", sa.String(32), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("resource_type", sa.String(32), nullable=False),
            sa.Column("resource_id", sa.String(64), nullable=False),
            sa.Column("root_space_id", sa.Integer(), nullable=True),
            sa.Column("relation", sa.String(32), nullable=True),
            sa.Column("source_ref", sa.String(128), nullable=True),
            sa.Column("snapshot", JsonType(), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default=sa.text("'pending'")),
            sa.Column("protected_at", sa.DateTime(), nullable=True),
            sa.Column("protected_source", sa.String(32), nullable=True),
            sa.Column("processed_at", sa.DateTime(), nullable=True),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("last_error", sa.Text(), nullable=True),
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
            sa.UniqueConstraint("event_id", "item_key", name="uk_dtpc_item_event_key"),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
        )

    _create_index(EVENT_TABLE, "idx_dtpc_status_retry", ["status", "next_retry_at"])
    _create_index(EVENT_TABLE, "idx_dtpc_user_changed", ["user_id", "changed_at"])
    _create_index(ITEM_TABLE, "idx_dtpc_item_user_status", ["user_id", "status"])
    _create_index(ITEM_TABLE, "idx_dtpc_item_event_status", ["event_id", "status"])


def downgrade() -> None:
    connection = op.get_bind()
    if table_exists(connection, ITEM_TABLE):
        op.drop_table(ITEM_TABLE)
    if table_exists(connection, EVENT_TABLE):
        op.drop_table(EVENT_TABLE)
