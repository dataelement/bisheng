"""F044 follow-up: add developer token route allowlist.

Revision ID: f044_route_allowlist
Revises: f057_message_push_outbox, f058_approval_notification_outbox
Create Date: 2026-07-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import JsonType, column_exists, table_exists

revision: str = "f044_route_allowlist"
down_revision: str | Sequence[str] | None = (
    "f057_message_push_outbox",
    "f058_approval_notification_outbox",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "developer_token"
_COLUMN = "route_whitelist"


def upgrade() -> None:
    connection = op.get_bind()
    if table_exists(connection, _TABLE) and not column_exists(connection, _TABLE, _COLUMN):
        op.add_column(
            _TABLE,
            sa.Column(
                _COLUMN,
                JsonType(),
                nullable=True,
                comment="Developer token route allowlist rules",
            ),
        )


def downgrade() -> None:
    connection = op.get_bind()
    if table_exists(connection, _TABLE) and column_exists(connection, _TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
