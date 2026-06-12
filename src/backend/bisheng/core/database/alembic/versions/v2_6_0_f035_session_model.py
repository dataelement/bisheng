"""F035: add linsight_session_version.model (Track E per-task model injection).

The deepagents migration makes the execution model per-task selectable: the
submit payload carries a ``model`` id which is persisted on the session version
so re-execution and auditing can see which model ran. Nullable — empty means the
task resolved the tenant ``linsight_default_model_id`` at run time
(agent_factory._resolve_model). Generic ``Text`` keeps DM8/MySQL compatible.

Revision ID: f035_session_model
Revises: f035_skill_display_name
Create Date: 2026-06-12
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists

revision: str = "f035_session_model"
down_revision: Union[str, Sequence[str], None] = "f035_skill_display_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "linsight_session_version"
_COLUMN = "model"


def upgrade() -> None:
    conn = op.get_bind()
    if not column_exists(conn, _TABLE, _COLUMN):
        op.add_column(
            _TABLE,
            sa.Column(
                _COLUMN,
                sa.Text(),
                nullable=True,
                comment="Per-task execution model id",
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if column_exists(conn, _TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
