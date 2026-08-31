"""Add third-party course import fields on portal_course.

Revision ID: f104_portal_course_ext_import
Revises: f103_portal_course_external
Create Date: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, index_exists, table_exists

revision: str = "f104_portal_course_ext_import"
down_revision: str | Sequence[str] | None = "f103_portal_course_external"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COURSE_TABLE = "portal_course"
_EXTERNAL_ID = "external_id"
_COVER_URL = "cover_url"
_SOURCE_UPDATED_AT = "source_updated_at"
_UNIQUE_INDEX = "uk_portal_course_tenant_external_id"


def upgrade() -> None:
    connection = op.get_bind()
    if not table_exists(connection, _COURSE_TABLE):
        return
    missing_id = not column_exists(connection, _COURSE_TABLE, _EXTERNAL_ID)
    missing_cover = not column_exists(connection, _COURSE_TABLE, _COVER_URL)
    missing_updated = not column_exists(connection, _COURSE_TABLE, _SOURCE_UPDATED_AT)
    missing_index = not index_exists(connection, _COURSE_TABLE, _UNIQUE_INDEX)
    if not missing_id and not missing_cover and not missing_updated and not missing_index:
        return
    if connection.dialect.name == "sqlite":
        with op.batch_alter_table(_COURSE_TABLE) as batch_op:
            if missing_id:
                batch_op.add_column(sa.Column(_EXTERNAL_ID, sa.String(128), nullable=True))
            if missing_cover:
                batch_op.add_column(
                    sa.Column(
                        _COVER_URL,
                        sa.String(2048),
                        nullable=False,
                        server_default=sa.text("''"),
                    )
                )
            if missing_updated:
                batch_op.add_column(sa.Column(_SOURCE_UPDATED_AT, sa.DateTime(), nullable=True))
            if missing_index:
                batch_op.create_index(_UNIQUE_INDEX, ["tenant_id", _EXTERNAL_ID], unique=True)
        return
    if missing_id:
        op.add_column(_COURSE_TABLE, sa.Column(_EXTERNAL_ID, sa.String(128), nullable=True))
    if missing_cover:
        op.add_column(
            _COURSE_TABLE,
            sa.Column(
                _COVER_URL,
                sa.String(2048),
                nullable=False,
                server_default=sa.text("''"),
            ),
        )
    if missing_updated:
        op.add_column(_COURSE_TABLE, sa.Column(_SOURCE_UPDATED_AT, sa.DateTime(), nullable=True))
    if missing_index:
        op.create_index(_UNIQUE_INDEX, _COURSE_TABLE, ["tenant_id", _EXTERNAL_ID], unique=True)


def downgrade() -> None:
    connection = op.get_bind()
    if not table_exists(connection, _COURSE_TABLE):
        return
    if index_exists(connection, _COURSE_TABLE, _UNIQUE_INDEX):
        op.drop_index(_UNIQUE_INDEX, table_name=_COURSE_TABLE)
    drop_updated = column_exists(connection, _COURSE_TABLE, _SOURCE_UPDATED_AT)
    drop_cover = column_exists(connection, _COURSE_TABLE, _COVER_URL)
    drop_id = column_exists(connection, _COURSE_TABLE, _EXTERNAL_ID)
    if connection.dialect.name == "sqlite":
        with op.batch_alter_table(_COURSE_TABLE) as batch_op:
            if drop_updated:
                batch_op.drop_column(_SOURCE_UPDATED_AT)
            if drop_cover:
                batch_op.drop_column(_COVER_URL)
            if drop_id:
                batch_op.drop_column(_EXTERNAL_ID)
        return
    if drop_updated:
        op.drop_column(_COURSE_TABLE, _SOURCE_UPDATED_AT)
    if drop_cover:
        op.drop_column(_COURSE_TABLE, _COVER_URL)
    if drop_id:
        op.drop_column(_COURSE_TABLE, _EXTERNAL_ID)
