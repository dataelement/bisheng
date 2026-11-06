"""Store Information article sync progress on channel_info_source.

Revision ID: f074_information_cursor_on_source
Revises: merge_enterprise_chat_heads
Create Date: 2026-10-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists

revision: str = "f074_information_cursor_on_source"
down_revision: str | Sequence[str] | None = "merge_enterprise_chat_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOURCE_TABLE = "channel_info_source"
_COLUMNS = (
    "article_cursor_create_time",
    "processed_remote_sync_at",
    "processed_article_list_updated_at",
)


def upgrade() -> None:
    for name in _COLUMNS:
        if not column_exists(_SOURCE_TABLE, name):
            op.add_column(_SOURCE_TABLE, sa.Column(name, sa.BigInteger(), nullable=True))


def downgrade() -> None:
    for name in reversed(_COLUMNS):
        if column_exists(_SOURCE_TABLE, name):
            op.drop_column(_SOURCE_TABLE, name)
