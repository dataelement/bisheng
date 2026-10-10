"""Create tenant-level personal-token settings.

Revision ID: f053_pat_tenant_setting
Revises: f053_delegate_session_subject
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import table_exists
from bisheng.core.database.dialect_helpers import update_time_server_default

revision: str = "f053_pat_tenant_setting"
down_revision: str | Sequence[str] | None = "f053_delegate_session_subject"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not table_exists("open_api_tenant_setting"):
        conn = op.get_bind()
        op.create_table(
            "open_api_tenant_setting",
            sa.Column("tenant_id", sa.Integer, primary_key=True, autoincrement=False),
            sa.Column("pat_enabled", sa.Boolean, nullable=False, server_default=sa.text("0")),
            sa.Column("pat_ttl_days", sa.Integer, nullable=False, server_default=sa.text("30")),
            sa.Column(
                "update_time",
                sa.DateTime,
                nullable=False,
                server_default=update_time_server_default(conn),
            ),
        )


def downgrade() -> None:
    if table_exists("open_api_tenant_setting"):
        op.drop_table("open_api_tenant_setting")
