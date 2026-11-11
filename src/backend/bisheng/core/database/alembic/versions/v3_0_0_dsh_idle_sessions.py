"""Add per-device business inactivity policy without fabricating activity history."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, index_exists, table_exists

revision = "dsh_idle_sessions"
down_revision = "merge_f114_dsh_refresh"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not table_exists("dsh_session"):
        return
    columns = (
        sa.Column("expiry_policy", sa.String(32), nullable=False, server_default="ABSOLUTE_V1"),
        sa.Column("last_activity_at", sa.DateTime(), nullable=True),
        sa.Column("idle_ttl_seconds", sa.BigInteger(), nullable=True),
    )
    for column in columns:
        if not column_exists("dsh_session", column.name):
            op.add_column("dsh_session", column)
    if table_exists("dsh_refresh_token") and not index_exists("dsh_refresh_token", "ix_dsh_refresh_active"):
        op.create_index("ix_dsh_refresh_active", "dsh_refresh_token", ["tenant_id", "session_id", "state"])


def downgrade() -> None:
    # Retain additive policy/evidence columns across rollback and re-upgrade.
    pass
