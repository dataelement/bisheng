"""Nullable persisted reference Coverage epoch; no old row is certified."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, index_exists, table_exists

revision = "f118_reference_coverage_epoch"
down_revision = "f118_model_delete_execution"
branch_labels = None
depends_on = None


def upgrade():
    table = "knowledge_unification_run"
    if not table_exists(table):
        return
    if not column_exists(table, "coverage_epoch"):
        op.add_column(table, sa.Column("coverage_epoch", sa.BigInteger(), nullable=True))
    if not index_exists(table, "ix_kun_coverage_epoch"):
        op.create_index("ix_kun_coverage_epoch", table, ["writer_contract_version", "coverage_epoch", "tenant_id"])


def downgrade():
    raise RuntimeError("F118 rollback requires the maintenance-window consistent backup")
