"""纠错单拆成原文错误处和纠正后内容两段.

Revision ID: f114_correction_two_part
Revises: f113_correction_pending_update_file
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, table_exists

revision: str = "f114_correction_two_part"
down_revision: str | Sequence[str] | None = "f113_correction_pending_update_file"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "knowledge_file_correction"


def upgrade() -> None:
    """给已有纠错单补两段正文列. 旧数据两列为空, 仍读 content."""
    bind = op.get_bind()
    if not table_exists(bind, _TABLE):
        return
    if not column_exists(bind, _TABLE, "original_error"):
        op.add_column(
            _TABLE,
            sa.Column(
                "original_error",
                sa.String(500),
                nullable=True,
                comment="用户认为原文中错误的地方, 最多500字",
            ),
        )
    if not column_exists(bind, _TABLE, "corrected_content"):
        op.add_column(
            _TABLE,
            sa.Column(
                "corrected_content",
                sa.String(500),
                nullable=True,
                comment="用户纠正后的内容, 最多500字",
            ),
        )


def downgrade() -> None:
    """不删已经写下的两段正文."""
    pass
