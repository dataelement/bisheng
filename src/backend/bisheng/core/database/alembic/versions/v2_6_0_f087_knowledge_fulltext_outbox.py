"""Add the independent knowledge fulltext projection outbox.

Revision ID: f087_knowledge_fulltext_outbox
Revises: f086_merge_points_qa_images
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import (
    UPDATE_TIME_SERVER_DEFAULT,
    JsonType,
    LargeText,
    index_exists,
    table_exists,
)

revision: str = "f087_knowledge_fulltext_outbox"
down_revision: str | Sequence[str] | None = "f086_merge_points_qa_images"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "knowledge_fulltext_outbox"
_INDEX = "ix_kfo_dispatch"


def _pk_type() -> sa.types.TypeEngine:
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    bind = op.get_bind()
    if not table_exists(bind, _TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id", _pk_type(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("aggregate_type", sa.String(16), nullable=False),
            sa.Column("aggregate_id", sa.BigInteger(), nullable=False),
            sa.Column("knowledge_id", sa.BigInteger(), nullable=True),
            sa.Column("desired_action", sa.String(32), nullable=False),
            sa.Column("desired_revision", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
            sa.Column("applied_revision", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("trigger_type", sa.String(64), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'pending'")),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("max_retries", sa.Integer(), nullable=False, server_default=sa.text("8")),
            sa.Column("next_retry_at", sa.DateTime(), nullable=True),
            sa.Column("lease_owner", sa.String(64), nullable=True),
            sa.Column("lease_until", sa.DateTime(), nullable=True),
            sa.Column("fanout_cursor", JsonType(), nullable=True),
            sa.Column("payload_snapshot", JsonType(), nullable=True),
            sa.Column("error_summary", LargeText(), nullable=True),
            sa.Column("last_success_at", sa.DateTime(), nullable=True),
            sa.Column(
                "create_time", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
            ),
            sa.Column(
                "update_time", sa.DateTime(), nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "aggregate_type",
                "aggregate_id",
                name="uk_knowledge_fulltext_outbox_aggregate",
            ),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
        )
    if not index_exists(bind, _TABLE, _INDEX):
        op.create_index(
            _INDEX,
            _TABLE,
            ["status", "next_retry_at", "lease_until", "update_time"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if table_exists(bind, _TABLE):
        op.drop_table(_TABLE)
