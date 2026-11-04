"""Retain workflow records after deletion (DDL only)."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, table_exists

revision = "v310b1_f004_workflow_soft_delete"
down_revision = "v310b1_f003_audit_operator_dept"
branch_labels = None
depends_on = None


def upgrade():
    if table_exists("flow") and not column_exists("flow", "is_delete"):
        op.add_column("flow", sa.Column("is_delete", sa.Integer(), nullable=False, server_default=sa.text("0")))


def downgrade():
    # Dropping the marker would expose retained rows. Require an explicit
    # operational rollback plan rather than silently resurrecting resources.
    raise RuntimeError("Workflow soft-delete rollback requires retaining deletion filtering")
