"""F044: create developer_token table.

Revision ID: f044_developer_token
Revises: f043_backfill_channel_membership_relation, f038_merge_remaining_heads
Create Date: 2026-06-10
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import (
    UPDATE_TIME_SERVER_DEFAULT,
    LargeText,
    index_exists,
    table_exists,
)

revision: str = "f044_developer_token"
down_revision: Union[str, Sequence[str], None] = (
    "f043_backfill_channel_membership_relation",
    "f038_merge_remaining_heads",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_index_if_missing(name: str, columns: list[str], unique: bool = False) -> None:
    conn = op.get_bind()
    if not index_exists(conn, "developer_token", name):
        op.create_index(name, "developer_token", columns, unique=unique)


def upgrade() -> None:
    conn = op.get_bind()
    if not table_exists(conn, "developer_token"):
        op.create_table(
            "developer_token",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("token_hash", sa.String(length=128), nullable=False),
            sa.Column("token_ciphertext", LargeText(), nullable=False),
            sa.Column("token_prefix", sa.String(length=16), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("override_ip_whitelist", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("ip_whitelist", LargeText(), nullable=True),
            sa.Column("override_rate_limit", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("rate_limit_per_minute", sa.Integer(), nullable=True),
            sa.Column("last_used_time", sa.DateTime(), nullable=True),
            sa.Column("last_used_ip", sa.String(length=64), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("updated_by", sa.Integer(), nullable=True),
            sa.Column("logic_delete", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("create_time", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("update_time", sa.DateTime(), nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
        )

    _create_index_if_missing("uk_developer_token_hash", ["token_hash"], unique=True)
    _create_index_if_missing("idx_developer_token_tenant_id", ["tenant_id"])
    _create_index_if_missing("idx_developer_token_user_id", ["user_id"])
    _create_index_if_missing("idx_developer_token_prefix", ["token_prefix"])
    _create_index_if_missing("idx_developer_token_logic_delete", ["logic_delete"])


def downgrade() -> None:
    conn = op.get_bind()
    if not table_exists(conn, "developer_token"):
        return
    for index_name in (
        "idx_developer_token_logic_delete",
        "idx_developer_token_prefix",
        "idx_developer_token_user_id",
        "idx_developer_token_tenant_id",
        "uk_developer_token_hash",
    ):
        if index_exists(conn, "developer_token", index_name):
            op.drop_index(index_name, table_name="developer_token")
    op.drop_table("developer_token")
