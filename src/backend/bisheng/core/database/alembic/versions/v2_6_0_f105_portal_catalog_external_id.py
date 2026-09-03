"""Add portal_course_catalog.external_id for third-party catalog numbers.

Revision ID: f105_portal_catalog_external_id
Revises: f104_portal_course_ext_import
Create Date: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, index_exists, table_exists

revision: str = "f105_portal_catalog_external_id"
down_revision: str | Sequence[str] | None = "f104_portal_course_ext_import"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "portal_course_catalog"
_COLUMN = "external_id"
_UNIQUE_INDEX = "uk_portal_catalog_tenant_external_id"
_UUID_HEX = set("0123456789abcdef")


def upgrade() -> None:
    connection = op.get_bind()
    if not table_exists(connection, _TABLE):
        return
    missing_column = not column_exists(connection, _TABLE, _COLUMN)
    missing_index = not index_exists(connection, _TABLE, _UNIQUE_INDEX)
    if missing_column or missing_index:
        if connection.dialect.name == "sqlite":
            with op.batch_alter_table(_TABLE) as batch_op:
                if missing_column:
                    batch_op.add_column(sa.Column(_COLUMN, sa.String(128), nullable=True))
                if missing_index:
                    batch_op.create_index(_UNIQUE_INDEX, ["tenant_id", _COLUMN], unique=True)
        else:
            if missing_column:
                op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(128), nullable=True))
            if missing_index:
                op.create_index(_UNIQUE_INDEX, _TABLE, ["tenant_id", _COLUMN], unique=True)
    _backfill_legacy_external_ids(connection)


def downgrade() -> None:
    connection = op.get_bind()
    if not table_exists(connection, _TABLE):
        return
    if index_exists(connection, _TABLE, _UNIQUE_INDEX):
        op.drop_index(_UNIQUE_INDEX, table_name=_TABLE)
    if not column_exists(connection, _TABLE, _COLUMN):
        return
    if connection.dialect.name == "sqlite":
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.drop_column(_COLUMN)
        return
    op.drop_column(_TABLE, _COLUMN)


def _backfill_legacy_external_ids(connection) -> None:
    catalog = sa.table(
        _TABLE,
        sa.column("id", sa.String),
        sa.column(_COLUMN, sa.String),
    )
    rows = connection.execute(sa.select(catalog.c.id, catalog.c.external_id)).fetchall()
    for catalog_id, external_id in rows:
        if external_id:
            continue
        text = str(catalog_id or "").strip()
        if not text or _is_uuid_hex(text):
            continue
        connection.execute(
            catalog.update().where(catalog.c.id == catalog_id).values(external_id=text)
        )


def _is_uuid_hex(value: str) -> bool:
    return len(value) == 32 and set(value.lower()) <= _UUID_HEX
