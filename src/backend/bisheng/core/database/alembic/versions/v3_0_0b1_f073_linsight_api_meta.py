"""F073: add linsight_session_version.api_meta (Open API task-mode submissions).

Set only for runs submitted through the Open API; the worker reads it to switch
to unattended execution. Nullable, no backfill: every existing row is a
workbench run and reads as NULL. ``JsonType`` keeps MySQL/DM8 compatible.

Revision ID: f073_linsight_api_meta
Revises: merge_f064_f066_heads
Create Date: 2026-09-30
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import JsonType, column_exists

revision: str = "f073_linsight_api_meta"
down_revision: Union[str, Sequence[str], None] = "merge_f064_f066_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "linsight_session_version"
_COLUMN = "api_meta"


def upgrade() -> None:
    conn = op.get_bind()
    if not column_exists(conn, _TABLE, _COLUMN):
        op.add_column(
            _TABLE,
            sa.Column(_COLUMN, JsonType, nullable=True, comment="Open API submission metadata"),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if column_exists(conn, _TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
