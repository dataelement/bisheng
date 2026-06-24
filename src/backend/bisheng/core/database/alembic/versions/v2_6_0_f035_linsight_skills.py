"""F035: add linsight_session_version.skills column (per-run skill selection).

Task mode persists the skill names the user picked for a run so the worker can
copy the matched (governance-enabled ∩ selected) skill bundles into the session
workspace at startup, and so resume/continue (which reload this row) materialize
the same skills. One nullable JSON column carries the name list.

Nullable for backward compatibility: sessions created before this column existed
read as NULL → no skills. ``JsonType`` keeps DM8/MySQL compatible.

Revision ID: f035_linsight_skills
Revises: f044_knowledge_space_user_pin
Create Date: 2026-06-24

Note: chained onto the current branch head (f044_...) rather than the F035 leaf,
so it linearly extends the single head — a fork off a mid-chain ancestor would
create a second head and break ``alembic upgrade head`` (singular) at startup.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import JsonType, column_exists

revision: str = "f035_linsight_skills"
down_revision: Union[str, Sequence[str], None] = "f044_knowledge_space_user_pin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "linsight_session_version"
_COLUMN = "skills"


def upgrade() -> None:
    conn = op.get_bind()
    if not column_exists(conn, _TABLE, _COLUMN):
        op.add_column(
            _TABLE,
            sa.Column(_COLUMN, JsonType, nullable=True, comment="Selected skill names for this run"),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if column_exists(conn, _TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
