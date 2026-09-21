"""F071: add a visible-entry override for knowledge-space chat sessions.

Revision ID: f068_knowledge_chat_entry
Revises: f066_pat_data_scope
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, index_exists

revision: str = "f068_knowledge_chat_entry"
down_revision: str | Sequence[str] | None = "f066_pat_data_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "message_session"
_COLUMN = "entry_flow_id"
_INDEX = "idx_message_session_entry_flow_id"


def upgrade() -> None:
    if not column_exists(_TABLE, _COLUMN):
        op.add_column(
            _TABLE,
            sa.Column(_COLUMN, sa.String(length=255), nullable=True),
        )
    if not index_exists(_TABLE, _INDEX):
        op.create_index(_INDEX, _TABLE, [_COLUMN], unique=False)


def downgrade() -> None:
    if index_exists(_TABLE, _INDEX):
        op.drop_index(_INDEX, table_name=_TABLE)
    if column_exists(_TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
