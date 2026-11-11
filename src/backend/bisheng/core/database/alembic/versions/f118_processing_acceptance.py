"""Preserve the immutable acceptance revision without guessing old evidence."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, table_exists

revision = "f118_processing_acceptance"
down_revision = "f118_metadata_schema"
branch_labels = None
depends_on = None


def upgrade():
    if table_exists("knowledge_processing_job") and not column_exists(
        "knowledge_processing_job", "accepted_model_config_revision"
    ):
        op.add_column(
            "knowledge_processing_job",
            sa.Column("accepted_model_config_revision", sa.Integer(), nullable=True),
        )


def downgrade():
    # Dropping original acceptance facts could make stale operations reusable.
    raise RuntimeError("F118 rollback requires the maintenance-window consistent backup")
