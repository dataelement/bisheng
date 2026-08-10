"""F078: add the immutable knowledge-file parsing priority snapshot.

Revision ID: f078_knowledge_parse_priority
Revises: f077_knowledge_folder_sort_weight
Create Date: 2026-08-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f078_knowledge_parse_priority"
down_revision: str | Sequence[str] | None = "f077_knowledge_folder_sort_weight"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "knowledgefile"
_COLUMN = "parse_priority"


def _has_column(bind, table: str, column: str) -> bool:
    inspector = sa.inspect(bind)
    return any(item["name"] == column for item in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind, _TABLE, _COLUMN):
        op.add_column(
            _TABLE,
            sa.Column(
                _COLUMN,
                sa.String(length=16),
                nullable=True,
                comment="Immutable knowledge-file parsing priority snapshot",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, _TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
