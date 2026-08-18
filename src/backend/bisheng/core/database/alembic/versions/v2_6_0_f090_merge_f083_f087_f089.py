# ruff: noqa: RUF002
"""合并 Alembic 三 head：F083 专家问答 + 全文 outbox + 积分 last_earned_at。

Revision ID: f090_merge_f083_f087_f089
Revises: f083_expert_qa_enhancement, f087_knowledge_fulltext_outbox, f089_points_last_earned_at
Create Date: 2026-08-15

三条链路均从 f086_merge_points_qa_images 分叉，本空合并 revision 收口为单 head。
无 DDL、无回填、不改表。
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "f090_merge_f083_f087_f089"
down_revision: str | Sequence[str] | None = (
    "f083_expert_qa_enhancement",
    "f087_knowledge_fulltext_outbox",
    "f089_points_last_earned_at",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """空合并：三侧 schema 已由各自 revision 完成。"""
    pass


def downgrade() -> None:
    """空合并无反向 DDL。"""
    pass
