"""Widen t_gpts_tools_type.openapi_schema to the dialect's large-text type.

Revision ID: v3_0_0_tool_openapi_schema_longtext
Revises: f114_app_authorization
Create Date: 2026-11-10

Why:
  Creating a custom tool stores the imported OpenAPI document verbatim in
  ``t_gpts_tools_type.openapi_schema``. The column was MySQL ``TEXT`` (64 KB
  byte limit), so a larger spec failed the INSERT with
  ``DataError(1406, "Data too long for column 'openapi_schema'")`` and the API
  answered 500. Widen it to ``LONGTEXT`` (MySQL) / ``CLOB`` (DaMeng) — the type
  the model now declares through ``LargeText`` — so real-world specs import.

  DDL only; no row is rewritten.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

from bisheng.core.database.dialect_helpers import LargeText, get_column_type

# revision identifiers, used by Alembic.
revision: str = 'v3_0_0_tool_openapi_schema_longtext'
down_revision: Union[str, Sequence[str], None] = 'f114_app_authorization'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 't_gpts_tools_type'
_COLUMN = 'openapi_schema'
#: Type name `get_column_type` reports once the column is wide enough.
_LARGE_TYPE = {'mysql': 'longtext', 'dm': 'clob'}


def upgrade() -> None:
    """Widen the column; idempotent across MySQL and DaMeng."""
    conn = op.get_bind()
    dialect = conn.dialect.name
    target = _LARGE_TYPE.get(dialect)
    if target is None:
        return
    if get_column_type(conn, _TABLE, _COLUMN) == target:
        return
    op.alter_column(
        _TABLE, _COLUMN,
        existing_type=sa.Text(),
        type_=LargeText(),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Shrink back to TEXT.

    DaMeng maps TEXT to CLOB already, so only MySQL has a narrower type to go
    back to — and values longer than 64 KB would then be rejected on insert.
    """
    conn = op.get_bind()
    if conn.dialect.name != 'mysql':
        return
    if get_column_type(conn, _TABLE, _COLUMN) != 'longtext':
        return
    op.alter_column(
        _TABLE, _COLUMN,
        existing_type=mysql.LONGTEXT(),
        type_=mysql.TEXT(),
        existing_nullable=True,
    )
