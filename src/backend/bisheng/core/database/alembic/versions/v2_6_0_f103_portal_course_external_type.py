"""Add local/external course type and third-party URL on portal_course.

Revision ID: f103_portal_course_external
Revises: f102_portal_course_catalog
Create Date: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, table_exists

revision: str = "f103_portal_course_external"
down_revision: str | Sequence[str] | None = "f102_portal_course_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COURSE_TABLE = "portal_course"
_TYPE_COLUMN = "course_type"
_URL_COLUMN = "external_url"


def upgrade() -> None:
    connection = op.get_bind()
    if not table_exists(connection, _COURSE_TABLE):
        return
    missing_type = not column_exists(connection, _COURSE_TABLE, _TYPE_COLUMN)
    missing_url = not column_exists(connection, _COURSE_TABLE, _URL_COLUMN)
    if not missing_type and not missing_url:
        return
    if connection.dialect.name == "sqlite":
        with op.batch_alter_table(_COURSE_TABLE) as batch_op:
            if missing_type:
                batch_op.add_column(
                    sa.Column(
                        _TYPE_COLUMN,
                        sa.String(16),
                        nullable=False,
                        server_default=sa.text("'local'"),
                    )
                )
            if missing_url:
                batch_op.add_column(
                    sa.Column(
                        _URL_COLUMN,
                        sa.String(2048),
                        nullable=False,
                        server_default=sa.text("''"),
                    )
                )
        return
    if missing_type:
        op.add_column(
            _COURSE_TABLE,
            sa.Column(
                _TYPE_COLUMN,
                sa.String(16),
                nullable=False,
                server_default=sa.text("'local'"),
            ),
        )
    if missing_url:
        op.add_column(
            _COURSE_TABLE,
            sa.Column(
                _URL_COLUMN,
                sa.String(2048),
                nullable=False,
                server_default=sa.text("''"),
            ),
        )


def downgrade() -> None:
    connection = op.get_bind()
    if not table_exists(connection, _COURSE_TABLE):
        return
    drop_type = column_exists(connection, _COURSE_TABLE, _TYPE_COLUMN)
    drop_url = column_exists(connection, _COURSE_TABLE, _URL_COLUMN)
    if not drop_type and not drop_url:
        return
    if connection.dialect.name == "sqlite":
        with op.batch_alter_table(_COURSE_TABLE) as batch_op:
            if drop_url:
                batch_op.drop_column(_URL_COLUMN)
            if drop_type:
                batch_op.drop_column(_TYPE_COLUMN)
        return
    if drop_url:
        op.drop_column(_COURSE_TABLE, _URL_COLUMN)
    if drop_type:
        op.drop_column(_COURSE_TABLE, _TYPE_COLUMN)
