"""F076: record which skill row owns each directory in a session.

Nullable JSON, no backfill. Each item is
``{name, skill_id, owner_user_id, content_hash}``. The existing ``skills``
column stays a list of selected names. ``JsonType`` is valid on MySQL and DM8.

Revision ID: f076_session_skill_snapshot
Revises: f076_linsight_skill_owner
Create Date: 2026-10-19
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import JsonType, column_exists

revision: str = "f076_session_skill_snapshot"
down_revision: Union[str, Sequence[str], None] = "f076_linsight_skill_owner"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "linsight_session_version"
_COLUMN = "skill_snapshot"


def upgrade() -> None:
    conn = op.get_bind()
    if not column_exists(conn, _TABLE, _COLUMN):
        op.add_column(
            _TABLE,
            sa.Column(
                _COLUMN,
                JsonType,
                nullable=True,
                comment="Directory ownership for skills copied into this session",
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if column_exists(conn, _TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
