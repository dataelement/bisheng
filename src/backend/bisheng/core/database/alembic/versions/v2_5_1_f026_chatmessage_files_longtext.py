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
from sqlalchemy.dialects import mysql

revision: str = 'f026_chatmessage_files_longtext'
down_revision: Union[str, Sequence[str], None] = 'f025_merge_f024_heads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_type(table_name: str, column_name: str) -> str | None:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            'SELECT DATA_TYPE FROM information_schema.COLUMNS '
            'WHERE TABLE_SCHEMA = DATABASE() '
            '  AND TABLE_NAME = :t AND COLUMN_NAME = :c'
        ),
        {'t': table_name, 'c': column_name},
    )
    value = result.scalar()
    return value.lower() if isinstance(value, str) else None


def upgrade() -> None:
    if _column_type('chatmessage', 'files') != 'longtext':
        op.alter_column(
            'chatmessage',
            'files',
            existing_type=mysql.VARCHAR(length=4096),
            type_=mysql.LONGTEXT(),
            existing_nullable=True,
            existing_comment='Uploaded documents, etc.',
        )


def downgrade() -> None:
    if _column_type('chatmessage', 'files') == 'longtext':
        op.alter_column(
            'chatmessage',
            'files',
            existing_type=mysql.LONGTEXT(),
            type_=mysql.VARCHAR(length=4096),
            existing_nullable=True,
            existing_comment='Uploaded documents, etc.',
        )
