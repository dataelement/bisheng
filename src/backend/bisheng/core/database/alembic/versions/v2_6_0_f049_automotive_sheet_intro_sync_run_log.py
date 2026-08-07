"""F049: add filelib_scheduled_sync_run_log for automotive sheet intro sync.

Revision ID: f049_automotive_sheet_intro_sync_run_log
Revises: f078_knowledge_parse_priority
Create Date: 2026-07-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import index_exists, table_exists

revision: str = "f049_automotive_sheet_intro_sync_run_log"
down_revision: str | Sequence[str] | None = "f078_knowledge_parse_priority"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE_NAME = "filelib_scheduled_sync_run_log"
_INDEX_NAME = "ix_fssrl_tenant_job_id"


def _create_table() -> None:
    op.create_table(
        _TABLE_NAME,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
            comment="Tenant ID",
        ),
        sa.Column("job_code", sa.String(length=64), nullable=False),
        sa.Column("trigger_type", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'running'"),
        ),
        sa.Column("developer_token_id", sa.Integer(), nullable=True),
        sa.Column("file_id", sa.Integer(), nullable=True),
        sa.Column("knowledge_id", sa.Integer(), nullable=True),
        sa.Column("file_name", sa.String(length=200), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "create_time",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def upgrade() -> None:
    conn = op.get_bind()
    if not table_exists(conn, _TABLE_NAME):
        _create_table()

    if not index_exists(conn, _TABLE_NAME, _INDEX_NAME):
        op.create_index(_INDEX_NAME, _TABLE_NAME, ["tenant_id", "job_code", "id"], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    if table_exists(conn, _TABLE_NAME):
        if index_exists(conn, _TABLE_NAME, _INDEX_NAME):
            op.drop_index(_INDEX_NAME, table_name=_TABLE_NAME)
        op.drop_table(_TABLE_NAME)
