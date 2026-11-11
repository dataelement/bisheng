"""Prepare nullable provenance storage; the formal permission plan owns issuance."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, table_exists

revision = "f118_retired_use_floor"
down_revision = "f118_move_actor_subject"
branch_labels = None
depends_on = None


def upgrade():
    if table_exists("permission_model") and not column_exists("permission_model", "retired_use_level_floor"):
        op.add_column("permission_model", sa.Column("retired_use_level_floor", sa.Integer(), nullable=True))


def downgrade():
    raise RuntimeError("F118 rollback requires the maintenance-window consistent backup")
