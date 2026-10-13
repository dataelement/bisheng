"""纠错单记下采纳并更新正在登记的新文件.

Revision ID: f113_correction_pending_update_file
Revises: f112_g8_two_scores
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, table_exists

revision: str = "f113_correction_pending_update_file"
down_revision: str | Sequence[str] | None = "f112_g8_two_scores"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """同一条待处理纠错同时只指向一份已登记的新文件."""
    if not table_exists(op.get_bind(), "knowledge_file_correction"):
        return
    if column_exists(op.get_bind(), "knowledge_file_correction", "pending_update_file_id"):
        return
    op.add_column(
        "knowledge_file_correction",
        sa.Column(
            "pending_update_file_id",
            sa.Integer(),
            nullable=True,
            comment="采纳并更新已登记、尚未替换完成的新文件ID",
        ),
    )


def downgrade() -> None:
    """不删除已记下的新文件指针."""
    pass
