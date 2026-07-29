"""Add qa_question.file_url column.

Revision ID: f073_add_qa_question_file_url
Revises: f072_add_system_dictionary, f072_knowledge_recycle_bin
Create Date: 2026-07-29
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, table_exists

revision: str = "f073_add_qa_question_file_url"
down_revision: Union[str, Sequence[str], None] = (
    "f072_add_system_dictionary",
    "f072_knowledge_recycle_bin",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "qa_question"
_COLUMN = "file_url"
_COMMENT = "文件URL"


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
            sa.String(length=1024),
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
