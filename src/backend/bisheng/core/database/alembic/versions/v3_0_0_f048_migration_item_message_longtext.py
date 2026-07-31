"""F048: widen frozen migration item payloads to a large-text column.

``permission_migration_item.message`` stores the frozen source payload used by
crash-safe resume. Legacy permission binding Config values can exceed MySQL's
64 KiB ``TEXT`` limit, so existing installations must widen the column to
``LONGTEXT``. DaMeng already represents ``TEXT`` as ``CLOB``; the guarded DDL
keeps that equivalent large-text representation unchanged.

Revision ID: f048_migration_item_message_longtext
Revises: f048_permission_grants
Create Date: 2026-07-31
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import CLOB
from sqlalchemy.dialects import mysql

from bisheng.core.database.dialect_helpers import get_column_type

revision: str = "f048_migration_item_message_longtext"
down_revision: Union[str, Sequence[str], None] = "f048_permission_grants"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "permission_migration_item"
_COLUMN = "message"


def upgrade() -> None:
    connection = op.get_bind()
    current_type = get_column_type(connection, _TABLE, _COLUMN)
    if connection.dialect.name == "mysql" and current_type != "longtext":
        op.alter_column(
            _TABLE,
            _COLUMN,
            existing_type=sa.Text(),
            type_=mysql.LONGTEXT(),
            existing_nullable=True,
        )
    elif connection.dialect.name == "dm" and current_type != "clob":
        op.alter_column(
            _TABLE,
            _COLUMN,
            existing_type=sa.Text(),
            type_=CLOB(),
            existing_nullable=True,
        )


def downgrade() -> None:
    connection = op.get_bind()
    current_type = get_column_type(connection, _TABLE, _COLUMN)
    if connection.dialect.name == "mysql" and current_type == "longtext":
        op.alter_column(
            _TABLE,
            _COLUMN,
            existing_type=mysql.LONGTEXT(),
            type_=sa.Text(),
            existing_nullable=True,
        )
