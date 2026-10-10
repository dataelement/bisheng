"""Create delegate scopes and add typed Open API session ownership.

Revision ID: f053_delegate_session_subject
Revises: f053_api_credential_tables
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, index_exists, table_exists

revision: str = "f053_delegate_session_subject"
down_revision: str | Sequence[str] | None = "f053_api_credential_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SESSION_TABLE = "message_session"
_SESSION_INDEX = "idx_message_session_api_subject"


def upgrade() -> None:
    if not table_exists("api_credential_delegate_scope"):
        op.create_table(
            "api_credential_delegate_scope",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer, nullable=False),
            sa.Column("credential_id", sa.BigInteger, nullable=False),
            sa.Column("subject_type", sa.String(32), nullable=False),
            sa.Column("subject_id", sa.BigInteger, nullable=False),
            sa.Column("create_time", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.CheckConstraint(
                "subject_type IN ('user', 'department')",
                name="ck_api_credential_delegate_scope_type",
            ),
            sa.UniqueConstraint(
                "credential_id",
                "subject_type",
                "subject_id",
                name="uk_api_credential_delegate_scope_subject",
            ),
        )
        op.create_index(
            "idx_api_credential_delegate_scope_tenant_credential",
            "api_credential_delegate_scope",
            ["tenant_id", "credential_id"],
        )
        op.create_index(
            "ix_api_credential_delegate_scope_credential_id",
            "api_credential_delegate_scope",
            ["credential_id"],
        )
        op.create_index(
            "ix_api_credential_delegate_scope_tenant_id",
            "api_credential_delegate_scope",
            ["tenant_id"],
        )

    for name, column in (
        ("api_subject_type", sa.Column("api_subject_type", sa.String(32), nullable=True)),
        ("api_subject_id", sa.Column("api_subject_id", sa.BigInteger, nullable=True)),
        ("external_user_id", sa.Column("external_user_id", sa.String(128), nullable=True)),
    ):
        if not column_exists(_SESSION_TABLE, name):
            op.add_column(_SESSION_TABLE, column)
    if not index_exists(_SESSION_TABLE, _SESSION_INDEX):
        op.create_index(
            _SESSION_INDEX,
            _SESSION_TABLE,
            ["tenant_id", "api_subject_type", "api_subject_id", "update_time"],
        )


def downgrade() -> None:
    if index_exists(_SESSION_TABLE, _SESSION_INDEX):
        op.drop_index(_SESSION_INDEX, table_name=_SESSION_TABLE)
    for name in ("external_user_id", "api_subject_id", "api_subject_type"):
        if column_exists(_SESSION_TABLE, name):
            op.drop_column(_SESSION_TABLE, name)
    if table_exists("api_credential_delegate_scope"):
        op.drop_table("api_credential_delegate_scope")
