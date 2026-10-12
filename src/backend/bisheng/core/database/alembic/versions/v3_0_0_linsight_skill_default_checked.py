"""Add linsight_skill.default_checked (admin-preselected skills in the picker).

A skill flagged here starts out selected in the end-user task-mode picker of
every new conversation; the user can still remove it. It only seeds the
frontend selection — the backend keeps mounting exactly the skills the request
names, so a missing ``skills`` field still means "no skills".

``server_default 0`` backfills existing rows as not preselected.

Revision ID: linsight_skill_default_checked
Revises: f064_merge_market_chat_id_index_heads
Create Date: 2026-10-10
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists

revision: str = "linsight_skill_default_checked"
down_revision: Union[str, Sequence[str], None] = "f064_merge_market_chat_id_index_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "linsight_skill"
_COLUMN = "default_checked"


def upgrade() -> None:
    conn = op.get_bind()
    if not column_exists(conn, _TABLE, _COLUMN):
        op.add_column(
            _TABLE,
            sa.Column(
                _COLUMN,
                sa.Integer,
                nullable=False,
                server_default=sa.text("0"),
                comment="Preselected in the end-user picker",
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if column_exists(conn, _TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
