"""Add the optional locally maintained department short name.

Revision ID: f082_department_short_name
Revises: f081_knowledge_file_original_origin
Create Date: 2026-08-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f082_department_short_name"
down_revision: str | Sequence[str] | None = "f081_knowledge_file_original_origin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "department"
_COLUMN = "short_name"


def _has_column(bind, table: str, column: str) -> bool:
    return any(item["name"] == column for item in sa.inspect(bind).get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind, _TABLE, _COLUMN):
        op.add_column(
            _TABLE,
            sa.Column(
                _COLUMN,
                sa.String(64),
                nullable=True,
                comment="Optional department short name maintained locally",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    # Dropping the column permanently removes all locally maintained short names.
    if _has_column(bind, _TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
