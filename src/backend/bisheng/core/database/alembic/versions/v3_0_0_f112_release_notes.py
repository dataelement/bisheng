"""Add immutable release notes to publish attempts and application versions."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, table_exists
from bisheng.core.database.dialect_helpers import LargeText

revision = "f112_release_notes"
down_revision = "vibe_merge_release_20261025"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("app_deployment", "app_version"):
        if table_exists(table) and not column_exists(table, "release_notes"):
            op.add_column(table, sa.Column("release_notes", LargeText(), nullable=True))


def downgrade():
    for table in ("app_version", "app_deployment"):
        if table_exists(table) and column_exists(table, "release_notes"):
            op.drop_column(table, "release_notes")
