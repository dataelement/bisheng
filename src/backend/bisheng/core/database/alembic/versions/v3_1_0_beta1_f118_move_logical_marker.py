"""Prepare private move-ready storage without deriving historical ready state."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, table_exists
from bisheng.core.database.dialect_helpers import JsonType

revision = "f118_move_logical_marker"
down_revision = "f118_retired_use_floor"
branch_labels = None
depends_on = None


def upgrade():
    if table_exists("knowledge_processing_job") and not column_exists(
        "knowledge_processing_job", "move_logical_marker"
    ):
        op.add_column("knowledge_processing_job", sa.Column("move_logical_marker", JsonType(), nullable=True))


def downgrade():
    raise RuntimeError("F118 rollback requires the maintenance-window consistent backup")
