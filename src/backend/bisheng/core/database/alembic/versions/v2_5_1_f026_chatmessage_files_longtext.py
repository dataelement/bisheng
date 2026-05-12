"""F026: widen chatmessage.files to LONGTEXT for uploaded file metadata.

Revision ID: f026_chatmessage_files_longtext
Revises: f025_merge_f024_heads
Create Date: 2026-04-23

Background:
  Workstation chat persists uploaded file metadata as JSON in
  ``chatmessage.files``. When the payload contains signed object-storage
  URLs, the serialized JSON can exceed the legacy ``VARCHAR(4096)``
  limit and MySQL raises ``DataError(1406, "Data too long for column
  'files'")`` on insert. This migration widens the column to
  ``LONGTEXT`` so existing write paths keep working without truncation.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import CLOB
from sqlalchemy.dialects import mysql

from bisheng.core.database.dialect_helpers import get_column_type

revision: str = 'f026_chatmessage_files_longtext'
down_revision: Union[str, Sequence[str], None] = 'f025_merge_f024_heads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Expected large-text type name per dialect (as returned by get_column_type)
_LARGE_TYPE = {'mysql': 'longtext', 'dm': 'clob'}


def _alter_to_large(table: str, column: str, existing_nullable: bool,
                    existing_comment: str | None = None) -> None:
    """Widen column to the dialect's large-text type using Alembic DDL."""
    conn = op.get_bind()
    dialect = conn.dialect.name
    current = get_column_type(conn, table, column)
    large = _LARGE_TYPE.get(dialect)
    if large is None or current == large:
        return

    if dialect == 'mysql':
        op.alter_column(
            table, column,
            existing_type=mysql.VARCHAR(length=4096),
            type_=mysql.LONGTEXT(),
            existing_nullable=existing_nullable,
            existing_comment=existing_comment,
        )
    elif dialect == 'dm':
        op.alter_column(
            table, column,
            existing_type=sa.VARCHAR(length=4096),
            type_=CLOB(),
            existing_nullable=existing_nullable,
        )


def _alter_to_varchar(table: str, column: str, existing_nullable: bool,
                      existing_comment: str | None = None) -> None:
    """Shrink column back to VARCHAR(4096) using Alembic DDL."""
    conn = op.get_bind()
    dialect = conn.dialect.name
    current = get_column_type(conn, table, column)
    large = _LARGE_TYPE.get(dialect)
    if large is None or current != large:
        return

    if dialect == 'mysql':
        op.alter_column(
            table, column,
            existing_type=mysql.LONGTEXT(),
            type_=mysql.VARCHAR(length=4096),
            existing_nullable=existing_nullable,
            existing_comment=existing_comment,
        )
    elif dialect == 'dm':
        op.alter_column(
            table, column,
            existing_type=CLOB(),
            type_=sa.VARCHAR(length=4096),
            existing_nullable=existing_nullable,
        )


def upgrade() -> None:
    _alter_to_large('chatmessage', 'files', existing_nullable=True,
                    existing_comment='Uploaded documents, etc.')
    _alter_to_large('chatmessage', 'extra', existing_nullable=True,
                    existing_comment='retriever documents, etc.')


def downgrade() -> None:
    _alter_to_varchar('chatmessage', 'files', existing_nullable=True,
                      existing_comment='Uploaded documents, etc.')
