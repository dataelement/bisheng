"""Add knowledgefile.deleted_at and knowledge_recycle_item table.

Revision ID: f072_knowledge_recycle_bin
Revises: f071_knowledge_document_distribution
Create Date: 2026-07-28

Idempotent: safe when knowledge_recycle_item already exists (e.g. create_all)
and when deleted_at was partially applied.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import (
    UPDATE_TIME_SERVER_DEFAULT,
    JsonType,
    column_exists,
    index_exists,
    table_exists,
)

revision: str = "f072_knowledge_recycle_bin"
down_revision: str | Sequence[str] | None = "f071_knowledge_document_distribution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KF_TABLE = "knowledgefile"
_RECYCLE_TABLE = "knowledge_recycle_item"
_KF_INDEX = "ix_knowledgefile_knowledge_id_deleted_at"
_RECYCLE_INDEX = "ix_knowledge_recycle_item_list_entry"


def upgrade() -> None:
    connection = op.get_bind()
    if table_exists(connection, _KF_TABLE) and not column_exists(connection, _KF_TABLE, "deleted_at"):
        op.add_column(
            _KF_TABLE,
            sa.Column(
                "deleted_at",
                sa.DateTime(),
                nullable=True,
                comment="Soft-delete timestamp; NULL=active, set when in recycle bin",
            ),
        )
    if table_exists(connection, _KF_TABLE) and not index_exists(connection, _KF_TABLE, _KF_INDEX):
        op.create_index(_KF_INDEX, _KF_TABLE, ["knowledge_id", "deleted_at"])

    if not table_exists(connection, _RECYCLE_TABLE):
        op.create_table(
            _RECYCLE_TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False, server_default=sa.text("1"), index=True),
            sa.Column("file_id", sa.Integer(), nullable=False, index=True),
            sa.Column("knowledge_id", sa.Integer(), nullable=False, index=True),
            sa.Column("file_type", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("is_list_entry", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("display_name", sa.String(length=200), nullable=False),
            sa.Column("file_category_code", sa.String(length=64), nullable=True),
            sa.Column("file_subcategory_code", sa.String(length=16), nullable=True),
            sa.Column("business_domain_code", sa.String(length=64), nullable=True),
            sa.Column("tags_snapshot", JsonType, nullable=True),
            sa.Column("file_encoding", sa.String(length=64), nullable=True),
            sa.Column("file_size", sa.BigInteger(), nullable=True),
            sa.Column("md5", sa.String(length=64), nullable=True),
            sa.Column("space_level", sa.String(length=32), nullable=True),
            sa.Column("space_level_label", sa.String(length=64), nullable=True),
            sa.Column("original_knowledge_id", sa.Integer(), nullable=False),
            sa.Column("original_parent_id", sa.Integer(), nullable=True),
            sa.Column("original_path", sa.String(length=1024), nullable=False, server_default=""),
            sa.Column("original_file_level_path", sa.String(length=1024), nullable=True),
            sa.Column("original_path_fingerprint", sa.String(length=128), nullable=True),
            sa.Column("deleted_by", sa.Integer(), nullable=False),
            sa.Column("deleted_by_name", sa.String(length=128), nullable=True),
            sa.Column("deleted_at", sa.DateTime(), nullable=False),
            sa.Column("expire_at", sa.DateTime(), nullable=False, index=True),
            sa.Column("recycle_batch_id", sa.String(length=64), nullable=False, index=True),
            sa.Column("recycle_root_id", sa.Integer(), nullable=False, index=True),
            sa.Column("document_id", sa.Integer(), nullable=True),
            sa.Column("version_file_ids", JsonType, nullable=True),
            sa.Column("create_time", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column(
                "update_time",
                sa.DateTime(),
                nullable=False,
                server_default=UPDATE_TIME_SERVER_DEFAULT,
            ),
        )
    if table_exists(connection, _RECYCLE_TABLE) and not index_exists(connection, _RECYCLE_TABLE, _RECYCLE_INDEX):
        op.create_index(_RECYCLE_INDEX, _RECYCLE_TABLE, ["is_list_entry", "deleted_at"])


def downgrade() -> None:
    connection = op.get_bind()
    if table_exists(connection, _RECYCLE_TABLE):
        if index_exists(connection, _RECYCLE_TABLE, _RECYCLE_INDEX):
            op.drop_index(_RECYCLE_INDEX, table_name=_RECYCLE_TABLE)
        op.drop_table(_RECYCLE_TABLE)
    if table_exists(connection, _KF_TABLE) and column_exists(connection, _KF_TABLE, "deleted_at"):
        if index_exists(connection, _KF_TABLE, _KF_INDEX):
            op.drop_index(_KF_INDEX, table_name=_KF_TABLE)
        op.drop_column(_KF_TABLE, "deleted_at")
