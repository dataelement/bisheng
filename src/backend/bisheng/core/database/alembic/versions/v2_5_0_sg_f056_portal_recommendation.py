"""F056: rebuildable portal recommendation file projection.

Revision ID: v2_5_0_sg_f056_portal_recommendation
Revises: f057_message_push_outbox, f058_approval_notification_outbox
Create Date: 2026-07-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import (
    UPDATE_TIME_SERVER_DEFAULT,
    constraint_exists,
    index_exists,
    table_exists,
)

revision: str = "v2_5_0_sg_f056_portal_recommendation"
down_revision: str | Sequence[str] | None = (
    "f057_message_push_outbox",
    "f058_approval_notification_outbox",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROJECTION_TABLE = "portal_recommendation_file_projection"

_PROJECTION_UNIQUE = "uk_portal_rec_projection_file"

_PROJECTION_INDEXES = {
    "ix_prfp_domain_recency": [
        "tenant_id",
        "business_domain_code",
        "recommendable",
        "source_update_time",
        "file_id",
    ],
    "ix_prfp_generic_recency": [
        "tenant_id",
        "recommendable",
        "source_update_time",
        "file_id",
    ],
    "ix_prfp_space_recommendable": ["tenant_id", "space_id", "recommendable"],
}


def _create_projection_table() -> None:
    op.create_table(
        _PROJECTION_TABLE,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
            comment="Tenant ID",
        ),
        sa.Column("file_id", sa.Integer(), nullable=False, comment="knowledgefile.id"),
        sa.Column("space_id", sa.Integer(), nullable=False, comment="Owning knowledge space ID"),
        sa.Column("business_domain_code", sa.String(length=16), nullable=True),
        sa.Column(
            "permission_scope",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'unknown'"),
        ),
        sa.Column(
            "recommendable",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "reason_code",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'unknown'"),
        ),
        sa.Column("source_update_time", sa.DateTime(), nullable=False),
        sa.Column(
            "projection_version",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "create_time",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "update_time",
            sa.DateTime(),
            nullable=False,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
        ),
        sa.UniqueConstraint("tenant_id", "file_id", name=_PROJECTION_UNIQUE),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )


def _create_indexes(table_name: str, indexes: dict[str, list[str]]) -> None:
    connection = op.get_bind()
    for index_name, columns in indexes.items():
        if not index_exists(connection, table_name, index_name):
            op.create_index(index_name, table_name, columns, unique=False)


def upgrade() -> None:
    connection = op.get_bind()
    if not table_exists(connection, _PROJECTION_TABLE):
        _create_projection_table()
    _create_indexes(_PROJECTION_TABLE, _PROJECTION_INDEXES)


def _drop_feature_table(table_name: str, indexes: dict[str, list[str]], unique_name: str) -> None:
    connection = op.get_bind()
    if not table_exists(connection, table_name):
        return
    for index_name in reversed(indexes):
        if index_exists(connection, table_name, index_name):
            op.drop_index(index_name, table_name=table_name)
    # SQLite cannot ALTER TABLE DROP CONSTRAINT; dropping the table removes
    # the unique constraint atomically. MySQL and DM8 support the explicit
    # rollback order required by the release contract.
    if connection.dialect.name != "sqlite" and constraint_exists(connection, table_name, unique_name):
        op.drop_constraint(unique_name, table_name, type_="unique")
    op.drop_table(table_name)


def downgrade() -> None:
    _drop_feature_table(_PROJECTION_TABLE, _PROJECTION_INDEXES, _PROJECTION_UNIQUE)
