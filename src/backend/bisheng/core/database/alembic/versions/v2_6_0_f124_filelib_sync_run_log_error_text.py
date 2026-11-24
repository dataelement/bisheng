"""Widen filelib_scheduled_sync_run_log.error_message for sync-record details.

Revision ID: f124_filelib_sync_run_log_error_text
Revises: f123_developer_token_knowledge_uploader
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import (
    LargeText,
    column_exists,
    get_column_type,
    index_exists,
    table_exists,
)

revision: str = "f124_filelib_sync_run_log_error_text"
down_revision: str | Sequence[str] | None = "f123_developer_token_knowledge_uploader"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "filelib_scheduled_sync_run_log"
_COLUMN = "error_message"
_INDEX = "ix_fssrl_token_id"
_VARCHAR_LENGTH = 500
_TARGET_TYPES = {"mysql": "longtext", "dm": "clob"}
_SUPPORTED_SOURCE_TYPES = {"varchar", "string", "text"}


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    target_type = _TARGET_TYPES.get(dialect)
    if target_type is None:
        return
    if not table_exists(bind, _TABLE) or not column_exists(bind, _TABLE, _COLUMN):
        return
    current = get_column_type(bind, _TABLE, _COLUMN) or ""
    if current != target_type and current in _SUPPORTED_SOURCE_TYPES:
        op.alter_column(
            _TABLE,
            _COLUMN,
            existing_type=sa.VARCHAR(length=_VARCHAR_LENGTH),
            type_=LargeText(),
            existing_nullable=True,
        )
    if not index_exists(bind, _TABLE, _INDEX):
        op.create_index(_INDEX, _TABLE, ["developer_token_id", "id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name not in _TARGET_TYPES:
        return
    if table_exists(bind, _TABLE) and index_exists(bind, _TABLE, _INDEX):
        op.drop_index(_INDEX, table_name=_TABLE)
    if not table_exists(bind, _TABLE) or not column_exists(bind, _TABLE, _COLUMN):
        return
    current = get_column_type(bind, _TABLE, _COLUMN) or ""
    if current in {"longtext", "clob", "text"}:
        op.alter_column(
            _TABLE,
            _COLUMN,
            existing_type=LargeText(),
            type_=sa.VARCHAR(length=_VARCHAR_LENGTH),
            existing_nullable=True,
        )
