"""F051: per-user channel pin table, decoupled from membership.

Channel pin state used to live on ``space_channel_member.is_pinned``, coupling a
pure per-user UI preference to the membership row (so a channel reachable only via
ReBAC / department authorization, with no membership row, could not be pinned).
This mirrors the knowledge-space pin refactor (F044): pins move to a dedicated
``channel_user_pin`` table keyed by ``(user_id, channel_id)``. The legacy
``channel.is_pinned`` / ``space_channel_member.is_pinned`` columns are left in place
for now (backfilled by scripts/backfill_channel_user_pin.py) and may be dropped in a
later, separate migration.

Revision ID: f051_channel_user_pin
Revises: f050_creation_idempotency
Create Date: 2026-08-17
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import index_exists, table_exists

revision: str = "f051_channel_user_pin"
down_revision: Union[str, Sequence[str], None] = "f050_creation_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if not table_exists(conn, "channel_user_pin"):
        op.create_table(
            "channel_user_pin",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer, nullable=False, comment="User who pinned the channel"),
            sa.Column("channel_id", sa.CHAR(36), nullable=False, comment="Pinned channel id"),
            sa.Column("create_time", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("user_id", "channel_id", name="uk_cup_user_channel"),
        )
        op.create_index("idx_cup_user_id", "channel_user_pin", ["user_id"])
    else:
        if not index_exists(conn, "channel_user_pin", "idx_cup_user_id"):
            op.create_index("idx_cup_user_id", "channel_user_pin", ["user_id"])


def downgrade() -> None:
    conn = op.get_bind()
    if table_exists(conn, "channel_user_pin"):
        if index_exists(conn, "channel_user_pin", "idx_cup_user_id"):
            op.drop_index("idx_cup_user_id", table_name="channel_user_pin")
        op.drop_table("channel_user_pin")
