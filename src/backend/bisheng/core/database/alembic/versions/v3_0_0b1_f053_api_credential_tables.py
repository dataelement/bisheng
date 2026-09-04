"""Create independent Open API credentials and service accounts.

Revision ID: f053_api_credential_tables
Revises: update_time_default_align
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import table_exists
from bisheng.core.database.dialect_helpers import JsonType, update_time_server_default

revision: str = "f053_api_credential_tables"
down_revision: str | Sequence[str] | None = "update_time_default_align"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    if not table_exists("service_account"):
        op.create_table(
            "service_account",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer, nullable=False, comment="Tenant ID"),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("description", sa.String(512), nullable=True),
            sa.Column("resource_owner_user_id", sa.BigInteger, nullable=False),
            sa.Column("created_by", sa.BigInteger, nullable=True),
            sa.Column("disabled_at", sa.DateTime, nullable=True),
            sa.Column("deleted_at", sa.DateTime, nullable=True),
            sa.Column("create_time", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("update_time", sa.DateTime, nullable=False, server_default=update_time_server_default(conn)),
            sa.UniqueConstraint("tenant_id", "name", name="uk_service_account_tenant_name"),
        )
        op.create_index("ix_service_account_tenant_id", "service_account", ["tenant_id"])
        op.create_index("ix_service_account_resource_owner_user_id", "service_account", ["resource_owner_user_id"])
        op.create_index(
            "idx_service_account_tenant_status",
            "service_account",
            ["tenant_id", "deleted_at", "disabled_at"],
        )

    if not table_exists("api_credential"):
        op.create_table(
            "api_credential",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer, nullable=False, comment="Tenant ID"),
            sa.Column("subject_kind", sa.String(32), nullable=False),
            sa.Column("subject_id", sa.BigInteger, nullable=False),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("key_prefix", sa.String(16), nullable=False),
            sa.Column("last4", sa.String(4), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("scopes", JsonType, nullable=False),
            sa.Column("expires_at", sa.DateTime, nullable=True),
            sa.Column("revoked_at", sa.DateTime, nullable=True),
            sa.Column("last_used_at", sa.DateTime, nullable=True),
            sa.Column("revoke_reason", sa.String(32), nullable=True),
            sa.Column("created_by", sa.BigInteger, nullable=True),
            sa.Column("create_time", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("update_time", sa.DateTime, nullable=False, server_default=update_time_server_default(conn)),
            sa.CheckConstraint(
                "subject_kind IN ('service_account', 'natural_person')",
                name="ck_api_credential_subject_kind",
            ),
            sa.UniqueConstraint("token_hash", name="uq_api_credential_token_hash"),
        )
        op.create_index("ix_api_credential_tenant_id", "api_credential", ["tenant_id"])
        op.create_index(
            "idx_api_credential_subject",
            "api_credential",
            ["tenant_id", "subject_kind", "subject_id"],
        )


def downgrade() -> None:
    if table_exists("api_credential"):
        op.drop_table("api_credential")
    if table_exists("service_account"):
        op.drop_table("service_account")
