"""给第三方课程增加课程时长秒数.

Revision ID: f117_portal_course_duration_seconds
Revises: f116_knowledge_violation_deduct
Create Date: 2026-10-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, table_exists

revision: str = "f117_portal_course_duration_seconds"
down_revision: str | Sequence[str] | None = "f116_knowledge_violation_deduct"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "portal_course"
_COLUMN = "duration_seconds"
_COMMENT = "课程时长秒数"


def upgrade() -> None:
    """第三方课程的列表和详情读取这一列, 本地课程仍用视频时长合计."""
    connection = op.get_bind()
    if not table_exists(connection, _TABLE):
        return
    if column_exists(connection, _TABLE, _COLUMN):
        return
    column = sa.Column(
        _COLUMN,
        sa.Integer(),
        nullable=False,
        server_default=sa.text("0"),
        comment=_COMMENT,
    )
    if connection.dialect.name == "sqlite":
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.add_column(column)
        return
    op.add_column(_TABLE, column)


def downgrade() -> None:
    """去掉课程时长秒数."""
    connection = op.get_bind()
    if not table_exists(connection, _TABLE):
        return
    if not column_exists(connection, _TABLE, _COLUMN):
        return
    if connection.dialect.name == "sqlite":
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.drop_column(_COLUMN)
        return
    op.drop_column(_TABLE, _COLUMN)
