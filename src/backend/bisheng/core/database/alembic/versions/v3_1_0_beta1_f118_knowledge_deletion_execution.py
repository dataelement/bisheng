"""Add neutral business phases to the original knowledge cleanup ledger."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, index_exists, table_exists

revision = "f118_knowledge_delete_execution"
down_revision = "f118_reference_coverage_epoch"
branch_labels = None
depends_on = None


def upgrade():
    table = "knowledge_space_delete_job"
    if not table_exists(table):
        return
    for name, kind in (("operation_type", sa.String(48)), ("business_phase", sa.String(24))):
        if not column_exists(table, name):
            op.add_column(table, sa.Column(name, kind, nullable=True))
    if not index_exists(table, "ix_space_delete_scope"):
        op.create_index(
            "ix_space_delete_scope", table, ["tenant_id", "space_id", "operation_type", "business_phase", "state"]
        )


def downgrade():
    raise RuntimeError("F118 rollback requires the maintenance-window consistent backup")
