"""Add linsight_skill.auto_enabled (F005: skills the user never picks but always gets).

An auto-enabled skill is left out of every end-user picker and is treated as
enabled for every user who may see it, regardless of a personal opt-out. It only
takes effect while the skill itself is enabled.

``server_default 0`` backfills existing rows as user-picked (no behaviour change).

Revision ID: f005_linsight_skill_auto_enabled
Revises: v310b2_merge_f016_pricing_memory_heads
Create Date: 2026-11-20
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists

revision: str = "f005_linsight_skill_auto_enabled"
down_revision: Union[str, Sequence[str], None] = "v310b2_merge_f016_pricing_memory_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "linsight_skill"
_COLUMN = "auto_enabled"


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
                comment="Auto-enabled: hidden from pickers, always available",
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if column_exists(conn, _TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
