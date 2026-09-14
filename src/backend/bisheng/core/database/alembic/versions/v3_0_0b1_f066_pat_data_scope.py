"""F066: tenant-level data scope for personal access tokens (PRD v2.9 D21).

Existing rows receive the server default ``all_visible`` — the upgrade never
changes observable behaviour on its own (AC-P23).
"""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists

revision = "f066_pat_data_scope"
down_revision = "f053_pat_default_ttl_365"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not column_exists("open_api_tenant_setting", "pat_data_scope"):
        op.add_column(
            "open_api_tenant_setting",
            sa.Column(
                "pat_data_scope",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'all_visible'"),
            ),
        )


def downgrade() -> None:
    if column_exists("open_api_tenant_setting", "pat_data_scope"):
        op.drop_column("open_api_tenant_setting", "pat_data_scope")
