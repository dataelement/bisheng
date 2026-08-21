"""F094: admin-defined display order for tenant tag libraries.

Revision ID: f094_tag_library_sort_weight
Revises: f093_point_rule_display_name
Create Date: 2026-08-21

Nullable on purpose, with no backfill. A NULL weight means "nobody has dragged
this list yet", and the query keeps those rows on their historical newest-first
ordering. The first drag freezes whatever is on screen into evenly spaced
weights, so existing installs see no change until an admin actually reorders.
A library created after that point also starts NULL and lands at the top, which
is where a newly created one used to appear anyway.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, table_exists

revision: str = "f094_tag_library_sort_weight"
down_revision: str | Sequence[str] | None = "f093_point_rule_display_name"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "knowledge_space_tag_library"
_COLUMN = "sort_weight"


def upgrade() -> None:
    bind = op.get_bind()
    if not table_exists(bind, _TABLE):
        return
    if column_exists(bind, _TABLE, _COLUMN):
        return
    op.add_column(
        _TABLE,
        sa.Column(
            _COLUMN,
            sa.Integer,
            nullable=True,
            comment="Admin drag order; NULL means never reordered",
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not table_exists(bind, _TABLE):
        return
    if column_exists(bind, _TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
