"""F118 metadata-schema CAS storage; no content or reference conversion."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, table_exists

revision = "f118_metadata_schema"
down_revision = "f118_knowledge_unification"
branch_labels = None
depends_on = None


def upgrade():
    if table_exists("knowledge") and not column_exists("knowledge", "metadata_schema_revision"):
        op.add_column(
            "knowledge",
            sa.Column("metadata_schema_revision", sa.Integer(), nullable=False, server_default=sa.text("0")),
        )


def downgrade():
    # Removing a live revision could let obsolete plans execute again.
    raise RuntimeError("F118 rollback requires the maintenance-window consistent backup")
