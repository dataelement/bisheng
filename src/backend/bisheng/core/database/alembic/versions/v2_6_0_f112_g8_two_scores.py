"""G8 分成采纳和采纳并更新两档分值.

Revision ID: f112_g8_two_scores
Revises: f111_file_correction_award_kind
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import table_exists

revision: str = "f112_g8_two_scores"
down_revision: str | Sequence[str] | None = "f111_file_correction_award_kind"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """把已有 G8 从单分值改成采纳 1 分, 采纳并更新 2 分."""
    connection = op.get_bind()
    if not table_exists(connection, "point_rule"):
        return
    connection.execute(
        sa.text(
            "UPDATE point_rule SET daily_cap = NULL, score_expr = :expr WHERE rule_code = 'G8'"
        ),
        {"expr": '{"mode": "file_correction", "adopt_score": 1, "update_score": 2}'},
    )


def downgrade() -> None:
    """不把两档分值压回单分值."""
    pass
