"""Merge alembic heads: points f084 + department short_name f082.

Revision ID: f085_merge_points_dept_short_name
Revises: f084_points_column_comments, f082_department_short_name
Create Date: 2026-08-10

积分链路与 feat/2.5.0-sg 的部门简称链路自 f077 分叉后形成双 head，本空合并 revision 收口。
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "f085_merge_points_dept_short_name"
down_revision: str | Sequence[str] | None = (
    "f084_points_column_comments",
    "f082_department_short_name",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """空合并：两侧 schema 已由各自 revision 完成。"""
    pass


def downgrade() -> None:
    """空合并无反向 DDL。"""
    pass
