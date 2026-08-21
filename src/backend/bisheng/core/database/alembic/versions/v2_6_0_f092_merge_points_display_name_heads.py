# ruff: noqa: RUF002
"""合并积分展示名与专家问答迁移 head，并为 point_rule 增加 display_name。

Revision ID: f092_merge_points_display_name_heads
Revises: f090_points_rule_display_names, f091_qa_expert_beijing_datetime
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "f092_merge_points_display_name_heads"
down_revision: str | Sequence[str] | None = (
    "f090_points_rule_display_names",
    "f091_qa_expert_beijing_datetime",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """空合并 revision，仅收口双 head。"""
    pass


def downgrade() -> None:
    pass
