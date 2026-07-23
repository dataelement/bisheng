"""Add alias_name to knowledgefile.

Revision ID: f067_add_knowledge_file_alias_name
Revises: f066_token_file_sync_rule
Create Date: 2026-07-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, table_exists

revision: str = "f067_add_knowledge_file_alias_name"
down_revision: str | Sequence[str] | None = "f066_token_file_sync_rule"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "knowledgefile"
_COLUMN = "alias_name"


def upgrade() -> None:
    connection = op.get_bind()
    if not table_exists(connection, _TABLE):
        return
    if column_exists(connection, _TABLE, _COLUMN):
        return
    op.add_column(
        _TABLE,
        sa.Column(
            _COLUMN,
            sa.String(200),
            nullable=True,
            comment="AI-generated display alias for the file; falls back to file_name when null (F067)",
        ),
    )


def downgrade() -> None:
    connection = op.get_bind()
    if not table_exists(connection, _TABLE):
        return
    if not column_exists(connection, _TABLE, _COLUMN):
        return
    op.drop_column(_TABLE, _COLUMN)
