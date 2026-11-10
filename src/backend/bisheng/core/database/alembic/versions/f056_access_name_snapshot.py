"""Add optional historical app name; no historical data backfill."""

import sqlalchemy as sa
from alembic import op

revision = "f056_access_name_snapshot"
down_revision = "f059_resource_phases"
branch_labels = None
depends_on = None


def upgrade():
    if "app_name_snapshot" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("app_access_log")}:
        op.add_column("app_access_log", sa.Column("app_name_snapshot", sa.String(128), nullable=True))


def downgrade():
    op.drop_column("app_access_log", "app_name_snapshot")
