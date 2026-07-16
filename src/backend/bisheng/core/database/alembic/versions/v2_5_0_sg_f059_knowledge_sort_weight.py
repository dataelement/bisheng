"""F059: admin-defined manual ordering for knowledge spaces.

Adds ``knowledge.sort_weight``: a sparse ordering weight (smaller sorts first) that
system admins set by dragging spaces within a level. NULL means "never dragged" and
sorts behind the ordered ones, so existing rows keep their recency order untouched.

Weights are spaced (1000, 2000, ...) so a drag only rewrites the moved row, using the
midpoint between its new neighbours — important with hundreds of spaces per level.

Revision ID: v2_5_0_sg_f059_knowledge_sort_weight
Revises: v2_5_0_sg_f056_portal_recommendation
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import index_exists

revision: str = "v2_5_0_sg_f059_knowledge_sort_weight"
down_revision: str | Sequence[str] | None = "v2_5_0_sg_f056_portal_recommendation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "knowledge"
_COLUMN = "sort_weight"
_INDEX = "ix_knowledge_sort_weight"


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
                sa.Integer(),
                nullable=True,
                comment="管理员手动排序权重，越小越靠前；NULL 表示未排过，排在已排序的之后",
            ),
        )
    if not index_exists(bind, _TABLE, _INDEX):
        op.create_index(_INDEX, _TABLE, [_COLUMN])


def downgrade() -> None:
    bind = op.get_bind()
    if index_exists(bind, _TABLE, _INDEX):
        op.drop_index(_INDEX, table_name=_TABLE)
    if _has_column(bind, _TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
