"""F077: admin-defined manual ordering for folders inside a knowledge space.

Adds ``knowledgefile.sort_weight``: a sparse ordering weight (smaller sorts first)
that space admins set by dragging folders within one directory. NULL means "never
dragged" and sorts behind the ordered ones, so existing listings keep their current
order until an admin actually drags something.

Weights are spaced (1000, 2000, ...) so a drag only rewrites the moved row, using the
midpoint between its new neighbours. Ordering is scoped to one directory, identified
by ``knowledge_id`` + ``file_level_path``; the index matches that lookup.

Only folders are draggable, so the column stays NULL for regular files.

Revision ID: f077_knowledge_folder_sort_weight
Revises: f076_filelib_department_mapping
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import index_exists

revision: str = "f077_knowledge_folder_sort_weight"
down_revision: str | Sequence[str] | None = "f076_filelib_department_mapping"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "knowledgefile"
_COLUMN = "sort_weight"
_INDEX = "ix_knowledgefile_dir_sort_weight"


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
        # Mirrors the directory-scoped ordering lookup: filter by space + directory,
        # then order by weight.
        op.create_index(_INDEX, _TABLE, ["knowledge_id", "file_level_path", _COLUMN])


def downgrade() -> None:
    bind = op.get_bind()
    if index_exists(bind, _TABLE, _INDEX):
        op.drop_index(_INDEX, table_name=_TABLE)
    if _has_column(bind, _TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
