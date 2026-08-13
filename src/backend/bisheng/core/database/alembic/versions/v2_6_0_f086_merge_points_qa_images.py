"""Merge alembic heads: points f085 + QA images f083.

Revision ID: f086_merge_points_qa_images
Revises: f085_merge_points_dept_short_name, f083_qa_answer_images_url_longtext
Create Date: 2026-08-12

积分恢复分支与 feat/2.5.0-sg 上的 QA 图片持久化链路形成双 head，本空合并 revision 收口。
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "f086_merge_points_qa_images"
down_revision: str | Sequence[str] | None = (
    "f085_merge_points_dept_short_name",
    "f083_qa_answer_images_url_longtext",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """空合并：两侧 schema 已由各自 revision 完成。"""
    pass


def downgrade() -> None:
    """空合并无反向 DDL。"""
    pass
