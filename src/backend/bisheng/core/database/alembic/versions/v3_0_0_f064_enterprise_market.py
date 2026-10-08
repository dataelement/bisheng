"""Add tenant marketplace deletion state while retaining installed-version history."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists

revision = "f064_enterprise_market"
down_revision = "f062_profile_version"
branch_labels = None
depends_on = None


def upgrade():
    if not column_exists("dsh_market_plugin", "deleted"):
        op.add_column(
            "dsh_market_plugin", sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade():
    if column_exists("dsh_market_plugin", "deleted"):
        op.drop_column("dsh_market_plugin", "deleted")
