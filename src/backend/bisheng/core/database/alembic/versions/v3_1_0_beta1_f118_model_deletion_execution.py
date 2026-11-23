"""Add neutral private execution storage to the original confirmation ledger."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, index_exists, table_exists
from bisheng.core.database.dialect_helpers import JsonType

revision = "f118_model_delete_execution"
down_revision = "f118_move_logical_marker"
branch_labels = None
depends_on = None


def upgrade():
    table = "knowledge_operation_plan"
    if not table_exists(table):
        return
    for name, kind in (
        ("model_server_id", sa.Integer()),
        ("model_execution_state", sa.String(32)),
        ("model_execution_metadata", JsonType()),
    ):
        if not column_exists(table, name):
            op.add_column(table, sa.Column(name, kind, nullable=True))
    if not index_exists(table, "ix_kop_model_execution"):
        op.create_index("ix_kop_model_execution", table, ["tenant_id", "model_server_id", "model_execution_state"])


def downgrade():
    raise RuntimeError("F118 rollback requires the maintenance-window consistent backup")
