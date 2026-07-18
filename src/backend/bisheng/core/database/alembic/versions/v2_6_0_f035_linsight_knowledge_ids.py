"""F035: add linsight_session_version exact knowledge-selection columns.

Task mode threads the daily picker's EXACT selection into the session version so
the agent searches precisely the chosen knowledge bases / spaces instead of every
KB of a coarse type. Two nullable JSON columns carry those id lists:

- ``organization_knowledge_ids`` — selected organization (NORMAL-type) KB ids.
- ``knowledge_space_ids``        — selected knowledge-space (SPACE-type) ids.

Nullable for backward compatibility: sessions created before this column existed
fall back to the coarse ``personal_knowledge_enabled`` / ``org_knowledge_enabled``
booleans. ``JsonType`` keeps DM8/MySQL compatible.

Revision ID: f035_linsight_knowledge_ids
Revises: f035_session_model
Create Date: 2026-06-17
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import JsonType, column_exists

revision: str = "f035_linsight_knowledge_ids"
down_revision: Union[str, Sequence[str], None] = "f035_session_model"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "linsight_session_version"
_COLUMNS = (
    ("organization_knowledge_ids", "Selected organization knowledge base ids"),
    ("knowledge_space_ids", "Selected knowledge space ids"),
)


def upgrade() -> None:
    conn = op.get_bind()
    for name, comment in _COLUMNS:
        if not column_exists(conn, _TABLE, name):
            op.add_column(
                _TABLE,
                sa.Column(name, JsonType, nullable=True, comment=comment),
            )


def downgrade() -> None:
    conn = op.get_bind()
    for name, _comment in reversed(_COLUMNS):
        if column_exists(conn, _TABLE, name):
            op.drop_column(_TABLE, name)
