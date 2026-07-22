"""Add the optional developer token file-sync rule.

Revision ID: f066_token_file_sync_rule
Revises: f064_add_qa_expert_job_fields
Create Date: 2026-07-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import JsonType, column_exists, table_exists

revision: str = "f066_token_file_sync_rule"
down_revision: str | Sequence[str] | None = "f064_add_qa_expert_job_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "developer_token"
_COLUMN = "file_sync_rule"


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
            JsonType(),
            nullable=True,
            comment="Developer token file sync business rule",
        ),
    )


def downgrade() -> None:
    connection = op.get_bind()
    if not table_exists(connection, _TABLE):
        return
    if column_exists(connection, _TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
