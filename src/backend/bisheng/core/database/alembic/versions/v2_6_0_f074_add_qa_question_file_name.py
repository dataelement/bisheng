"""Add qa_question.file_name column.

Revision ID: f074_add_qa_question_file_name
Revises: f073_add_qa_question_file_url
Create Date: 2026-07-29
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, table_exists

revision: str = "f074_add_qa_question_file_name"
down_revision: Union[str, Sequence[str], None] = "f073_add_qa_question_file_url"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "qa_question"
_COLUMN = "file_name"
_COMMENT = "文件名"


def upgrade() -> None:
    conn = op.get_bind()
    if not table_exists(conn, _TABLE):
        return
    if column_exists(conn, _TABLE, _COLUMN):
        return
    op.add_column(
        _TABLE,
        sa.Column(
            _COLUMN,
            sa.String(length=512),
            nullable=True,
            comment=_COMMENT,
        ),
    )


def downgrade() -> None:
    conn = op.get_bind()
    if not table_exists(conn, _TABLE):
        return
    if column_exists(conn, _TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
