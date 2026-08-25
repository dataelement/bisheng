# ruff: noqa: RUF002
"""合并统一共享存储与积分规则迁移 head。

Revision ID: f097_merge_shared_storage_points_heads
Revises: f090_space_shared_storage_routing, f096_points_rule_reset_g_default_names
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "f097_merge_shared_storage_points_heads"
down_revision: str | Sequence[str] | None = (
    "f090_space_shared_storage_routing",
    "f096_points_rule_reset_g_default_names",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """空合并 revision，仅收口双 head。"""
    pass


def downgrade() -> None:
    pass
