"""新增部门文件查看独立授权表。

Revision ID: f067_department_file_view_grant
Revises: f066_token_file_sync_rule
Create Date: 2026-07-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import (
    UPDATE_TIME_SERVER_DEFAULT,
    index_exists,
    table_exists,
)

revision: str = "f067_department_file_view_grant"
down_revision: str | Sequence[str] | None = "f066_token_file_sync_rule"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_NAME = "department_file_view_grant"


def _create_index(name: str, columns: list[str]) -> None:
    connection = op.get_bind()
    if not index_exists(connection, TABLE_NAME, name):
        op.create_index(name, TABLE_NAME, columns, unique=False)


def upgrade() -> None:
    connection = op.get_bind()
    if not table_exists(connection, TABLE_NAME):
        op.create_table(
            TABLE_NAME,
            sa.Column(
                "id",
                sa.Integer(),
                primary_key=True,
                nullable=False,
                autoincrement=True,
            ),
            sa.Column(
                "tenant_id",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            ),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("space_id", sa.Integer(), nullable=False),
            sa.Column("file_id", sa.Integer(), nullable=False),
            sa.Column("department_id", sa.Integer(), nullable=False),
            sa.Column("approval_instance_id", sa.Integer(), nullable=False),
            sa.Column(
                "grant_source",
                sa.String(32),
                nullable=False,
                server_default=sa.text("'approval_instance'"),
            ),
            sa.Column(
                "status",
                sa.String(16),
                nullable=False,
                server_default=sa.text("'active'"),
            ),
            sa.Column(
                "granted_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_by", sa.Integer(), nullable=True),
            sa.Column("revoked_reason", sa.Text(), nullable=True),
            sa.Column("invalidated_at", sa.DateTime(), nullable=True),
            sa.Column("invalidated_reason", sa.Text(), nullable=True),
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
                "user_id",
                "space_id",
                "file_id",
                name="uk_dfvg_tenant_user_space_file",
            ),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
        )

    _create_index(
        "idx_dfvg_tenant_user_status",
        ["tenant_id", "user_id", "status"],
    )
    _create_index(
        "idx_dfvg_tenant_space_file_status",
        ["tenant_id", "space_id", "file_id", "status"],
    )
    _create_index(
        "idx_dfvg_tenant_department_status",
        ["tenant_id", "department_id", "status"],
    )
    _create_index("idx_dfvg_approval_instance", ["approval_instance_id"])


def downgrade() -> None:
    connection = op.get_bind()
    if table_exists(connection, TABLE_NAME):
        op.drop_table(TABLE_NAME)
