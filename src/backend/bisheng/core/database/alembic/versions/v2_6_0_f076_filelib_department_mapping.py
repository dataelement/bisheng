"""Add filelib external department mapping table.

Revision ID: f076_filelib_department_mapping
Revises: f075_knowledge_file_migration
Create Date: 2026-07-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, table_exists

revision: str = "f076_filelib_department_mapping"
down_revision: str | Sequence[str] | None = "f075_knowledge_file_migration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_NAME = "filelib_department_mapping"


def upgrade() -> None:
    connection = op.get_bind()
    if table_exists(connection, TABLE_NAME):
        return
    op.create_table(
        TABLE_NAME,
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            nullable=False,
            autoincrement=True,
        ),
        sa.Column(
            "external_department_id",
            sa.String(128),
            nullable=False,
            comment="External department identifier from the upstream system",
        ),
        sa.Column(
            "external_department_name",
            sa.String(256),
            nullable=True,
            comment="External department display name from the upstream system",
        ),
        sa.Column(
            "org_code",
            sa.String(128),
            nullable=False,
            comment="Organization code mapped to department.external_id",
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
        sa.UniqueConstraint(
            "external_department_id",
            name="uk_filelib_dept_map_external_department_id",
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )


def downgrade() -> None:
    connection = op.get_bind()
    if table_exists(connection, TABLE_NAME):
        op.drop_table(TABLE_NAME)
