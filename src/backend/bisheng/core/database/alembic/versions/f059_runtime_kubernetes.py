"""Extend existing runtime ledgers for Kubernetes, without data migration.

Revision ID: f059_runtime_kubernetes
Revises: merge_vibe_f077_heads

New standalone tables are created by model discovery before online upgrade.
Historical transfer authorization_id remains NULL; an out-of-band resumable
backfill is required before enabling workload material access. Normal legacy
ORM inserts derive authorization_id from operation_id in Python.

Downgrade prerequisite: stop and clean every K8s execution, revoke workload
identities, and verify the old transfer uniqueness on a database backup.
This revision performs only DDL; it cannot establish those operational facts.
"""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, table_exists
from bisheng.core.database.dialect_helpers import JsonType, constraint_exists

revision = "f059_runtime_kubernetes"
down_revision = "merge_vibe_f077_heads"
branch_labels = None
depends_on = None


def _exists(table, name):
    connection = op.get_bind()
    return constraint_exists(connection, table, name) or constraint_exists(connection, table, name.upper())


def _columns():
    return {
        "runtime_node": [
            sa.Column("executor_kind", sa.String(24), nullable=False, server_default="docker"),
            sa.Column("capabilities", JsonType, nullable=True),
            sa.Column("controller_holder", sa.String(64), nullable=False, server_default=""),
            sa.Column("controller_epoch", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("lease_until", sa.DateTime(), nullable=True),
            sa.Column("probe_report", JsonType, nullable=True),
        ],
        "runtime_assignment": [sa.Column("data_operation_id", sa.String(36), nullable=False, server_default="")],
        "runtime_transfer": [
            sa.Column("authorization_kind", sa.String(24), nullable=False, server_default="operation"),
            sa.Column("authorization_id", sa.String(36), nullable=True),
        ],
    }


def upgrade():
    for table, columns in _columns().items():
        if table_exists(table):
            for column in columns:
                if not column_exists(table, column.name):
                    op.add_column(table, column)
    if table_exists("runtime_transfer"):
        if _exists("runtime_transfer", "uq_runtime_transfer_action"):
            op.drop_constraint("uq_runtime_transfer_action", "runtime_transfer", type_="unique")
        if not _exists("runtime_transfer", "uq_rt_transfer_authority"):
            op.create_unique_constraint(
                "uq_rt_transfer_authority",
                "runtime_transfer",
                ["authorization_kind", "authorization_id", "artifact_id", "action"],
            )


def downgrade():
    if table_exists("runtime_transfer"):
        if _exists("runtime_transfer", "uq_rt_transfer_authority"):
            op.drop_constraint("uq_rt_transfer_authority", "runtime_transfer", type_="unique")
        if not _exists("runtime_transfer", "uq_runtime_transfer_action"):
            op.create_unique_constraint(
                "uq_runtime_transfer_action", "runtime_transfer", ["operation_id", "artifact_id", "action"]
            )
    for table, columns in reversed(list(_columns().items())):
        if table_exists(table):
            for column in reversed(columns):
                if column_exists(table, column.name):
                    op.drop_column(table, column.name)
