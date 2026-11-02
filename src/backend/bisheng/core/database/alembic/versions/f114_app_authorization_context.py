"""Add trusted publication origins and isolated preview bindings (F114)."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, index_exists, table_exists
from bisheng.core.database.dialect_helpers import JsonType

revision = "f114_app_authorization"
down_revision = "v300_merge_beta7_heads"
branch_labels = None
depends_on = None


def _columns():
    return {
        "app_deployment": [sa.Column("authorization_context", JsonType(), nullable=True)],
        "app_preview_session": [
            sa.Column("purpose", sa.String(16), nullable=True),
            sa.Column("approval_instance_id", sa.Integer(), nullable=True),
            sa.Column("approval_task_id", sa.Integer(), nullable=True),
            sa.Column("credential_id", sa.BigInteger(), nullable=True),
            sa.Column("operation_id", sa.String(36), nullable=True),
        ],
    }


_INDEXES = (
    ("ux_app_preview_credential", ["credential_id"], True),
    ("ux_app_preview_operation", ["operation_id"], True),
    ("ix_app_preview_reuse", ["version_id", "approver_user_id", "purpose", "approval_task_id", "status"], False),
)


def upgrade():
    for table, columns in _columns().items():
        if table_exists(table):
            for column in columns:
                if not column_exists(table, column.name):
                    op.add_column(table, column)
    if table_exists("app_preview_session"):
        for name, columns, unique in _INDEXES:
            if not index_exists("app_preview_session", name):
                op.create_index(name, "app_preview_session", columns, unique=unique)


def downgrade():
    if table_exists("app_preview_session"):
        for name, _, _ in reversed(_INDEXES):
            if index_exists("app_preview_session", name):
                op.drop_index(name, table_name="app_preview_session")
    for table, columns in reversed(tuple(_columns().items())):
        if table_exists(table):
            for column in reversed(columns):
                if column_exists(table, column.name):
                    op.drop_column(table, column.name)
