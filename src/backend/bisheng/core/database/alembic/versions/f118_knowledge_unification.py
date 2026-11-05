"""F118 existing-table metadata only; conversion is an offline ops procedure."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, table_exists
from bisheng.core.database.dialect_helpers import JsonType

revision = "f118_knowledge_unification"
down_revision = "v310b1_f004_workflow_soft_delete"
branch_labels = None
depends_on = None


def upgrade():
    columns = {
        "knowledge": (
            sa.Column("processing_defaults", JsonType, nullable=True),
            sa.Column("processing_config_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("model_config_revision", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("model_transition", JsonType, nullable=True),
            sa.Column("index_generation", sa.String(64), nullable=True),
            sa.Column("migration_origin", sa.String(64), nullable=True),
        ),
        "permission_model": (
            sa.Column("visibility_only_resource_types", JsonType, nullable=True),
            sa.Column("visibility_level", sa.Integer(), nullable=True),
        ),
    }
    for table, additions in columns.items():
        if not table_exists(table):
            # Fresh installs create complete SQLModel tables before revisions.
            continue
        for column in additions:
            if not column_exists(table, column.name):
                op.add_column(table, column)


def downgrade():
    # Dropping visibility metadata can revoke valid grants; dropping migration
    # origin can silently charge migrated spaces against the personal quota.
    # Restore the maintenance-window consistent backup with the prior app.
    raise RuntimeError("F118 rollback requires the complete maintenance backup; metadata cannot be dropped safely")
