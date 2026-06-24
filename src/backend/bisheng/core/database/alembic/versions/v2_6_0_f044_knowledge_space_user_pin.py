"""F044 (feature 037): per-user knowledge-space pin table, decoupled from membership.

Pin state used to live on ``space_channel_member.is_pinned``, so a user reaching a
space only via ReBAC / department authorization (no membership row) could not pin
it ("set-pin succeeds but nothing pins"). This table stores pins as a pure per-user
preference, independent of membership. The legacy ``is_pinned`` column is left in
place for now (backfilled by scripts/backfill_knowledge_space_user_pin.py) and may
be dropped in a later, separate migration.

Revision ID: f044_knowledge_space_user_pin
Revises: f035_linsight_status_varchar
Create Date: 2026-06-24
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import index_exists, table_exists

revision: str = "f044_knowledge_space_user_pin"
down_revision: Union[str, Sequence[str], None] = "f035_linsight_status_varchar"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if not table_exists(conn, "knowledge_space_user_pin"):
        op.create_table(
            "knowledge_space_user_pin",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer, nullable=False, comment="User who pinned the space"),
            sa.Column("space_id", sa.Integer, nullable=False, comment="Pinned knowledge space id"),
            sa.Column("create_time", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("user_id", "space_id", name="uk_ksup_user_space"),
        )
        op.create_index("idx_ksup_user_id", "knowledge_space_user_pin", ["user_id"])
    else:
        if not index_exists(conn, "knowledge_space_user_pin", "idx_ksup_user_id"):
            op.create_index("idx_ksup_user_id", "knowledge_space_user_pin", ["user_id"])


def downgrade() -> None:
    conn = op.get_bind()
    if table_exists(conn, "knowledge_space_user_pin"):
        if index_exists(conn, "knowledge_space_user_pin", "idx_ksup_user_id"):
            op.drop_index("idx_ksup_user_id", table_name="knowledge_space_user_pin")
        op.drop_table("knowledge_space_user_pin")
