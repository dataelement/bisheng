"""Add the operator department snapshot to audit source tables (v3.1.0-beta1 F003).

DDL only: existing rows keep NULL, which the audit page shows as "unrecorded".
No server default and no foreign key — 0 and -1 are sentinels, not department ids.
"""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, index_exists, table_exists

revision = "v310b1_f003_audit_operator_dept"
down_revision = "f114_app_authorization"
branch_labels = None
depends_on = None

_TABLES = (
    "auditlog",
    "message_session",
    "model_call_record",
    "app_capability_call_record",
    "app_access_log",
)


def _index_name(table: str) -> str:
    return f"ix_{table}_operator_dept_id"


def upgrade():
    for table in _TABLES:
        if not table_exists(table):
            continue
        if not column_exists(table, "operator_dept_id"):
            op.add_column(table, sa.Column("operator_dept_id", sa.Integer(), nullable=True))
        if not column_exists(table, "operator_dept_path"):
            op.add_column(table, sa.Column("operator_dept_path", sa.String(1024), nullable=True))
        if not index_exists(table, _index_name(table)):
            op.create_index(_index_name(table), table, ["operator_dept_id"])


def downgrade():
    for table in reversed(_TABLES):
        if not table_exists(table):
            continue
        if index_exists(table, _index_name(table)):
            op.drop_index(_index_name(table), table_name=table)
        for column in ("operator_dept_path", "operator_dept_id"):
            if column_exists(table, column):
                op.drop_column(table, column)
