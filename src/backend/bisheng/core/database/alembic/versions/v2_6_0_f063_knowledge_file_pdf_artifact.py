"""Add the current unified PDF artifact table.

Revision ID: f063_knowledge_file_pdf_artifact
Revises: f062_add_portal_course_tables
Create Date: 2026-07-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import (
    UPDATE_TIME_SERVER_DEFAULT,
    index_exists,
    table_exists,
)

revision: str = "f063_knowledge_file_pdf_artifact"
down_revision: str | Sequence[str] | None = "f062_add_portal_course_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_index(name: str, columns: list[str]) -> None:
    connection = op.get_bind()
    table_name = "knowledge_file_pdf_artifact"
    if not index_exists(connection, table_name, name):
        op.create_index(name, table_name, columns, unique=False)


def upgrade() -> None:
    connection = op.get_bind()
    if not table_exists(connection, "knowledge_file_pdf_artifact"):
        op.create_table(
            "knowledge_file_pdf_artifact",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False, autoincrement=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("knowledge_file_id", sa.Integer(), nullable=False),
            sa.Column("source_object_name", sa.String(512), nullable=False),
            sa.Column("source_md5", sa.String(64), nullable=True),
            sa.Column("generation", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("status", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("artifact_origin", sa.Integer(), nullable=True),
            sa.Column("object_name", sa.String(512), nullable=True),
            sa.Column("artifact_sha256", sa.String(64), nullable=True),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("last_error", sa.String(2000), nullable=True),
            sa.Column("page_count", sa.Integer(), nullable=True),
            sa.Column("artifact_size", sa.BigInteger(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
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
            sa.ForeignKeyConstraint(
                ["knowledge_file_id"],
                ["knowledgefile.id"],
                name="fk_kf_pdf_artifact_file",
                ondelete="CASCADE",
            ),
            sa.UniqueConstraint("knowledge_file_id", name="uk_kf_pdf_artifact_file"),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
        )

    _create_index("ix_kf_pdf_artifact_tenant_status", ["tenant_id", "status"])
    _create_index("ix_kf_pdf_artifact_tenant_update", ["tenant_id", "update_time"])


def downgrade() -> None:
    connection = op.get_bind()
    if table_exists(connection, "knowledge_file_pdf_artifact"):
        op.drop_table("knowledge_file_pdf_artifact")
