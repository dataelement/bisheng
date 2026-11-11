"""Minimal tenant consistency markers; schema only, no business-data repair."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, table_exists

revision = "v310b1_f009_managed_tenant"
down_revision = "v310b1_f004_workflow_soft_delete"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("flow", "t_gpts_tools_type"):
        if table_exists(table) and not column_exists(table, "creation_state"):
            op.add_column(
                table,
                sa.Column("creation_state", sa.String(16), nullable=False, server_default=sa.text("'READY'")),
            )
    for column in ("copy_source_id", "copy_target_id"):
        if table_exists("knowledge") and not column_exists("knowledge", column):
            op.add_column("knowledge", sa.Column(column, sa.Integer(), nullable=True))


def downgrade():
    # The operator must first stop new writers and resolve pending creations /
    # copy claims; removing markers alone cannot safely cancel in-flight work.
    for column in ("copy_target_id", "copy_source_id"):
        if table_exists("knowledge") and column_exists("knowledge", column):
            op.drop_column("knowledge", column)
    for table in ("t_gpts_tools_type", "flow"):
        if table_exists(table) and column_exists(table, "creation_state"):
            op.drop_column(table, "creation_state")
