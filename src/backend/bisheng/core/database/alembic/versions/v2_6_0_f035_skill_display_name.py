"""F035: add linsight_skill.display_name (C3 contract change 2026-06-12).

display_name is the only skill name surfaced in UI (Chinese OK); the slug
``name`` stays the unique key / activation key / on-disk directory name.
Uniqueness of (tenant_id, display_name) is enforced at the application layer
(no DB constraint — DM8/MySQL index-length compatibility, see design §7).

Revision ID: f035_skill_display_name
Revises: f035_linsight_skill
Create Date: 2026-06-12
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists

revision: str = "f035_skill_display_name"
down_revision: Union[str, Sequence[str], None] = "f035_linsight_skill"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "linsight_skill"
_COLUMN = "display_name"


def upgrade() -> None:
    conn = op.get_bind()
    if not column_exists(conn, _TABLE, _COLUMN):
        op.add_column(
            _TABLE,
            sa.Column(
                _COLUMN,
                sa.String(length=255),
                nullable=False,
                server_default=sa.text("''"),
                comment="Display name",
            ),
        )
        # Backfill any pre-existing rows: fall back to the slug name.
        op.execute(sa.text(f"UPDATE {_TABLE} SET {_COLUMN} = name WHERE {_COLUMN} = ''"))


def downgrade() -> None:
    conn = op.get_bind()
    if column_exists(conn, _TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
