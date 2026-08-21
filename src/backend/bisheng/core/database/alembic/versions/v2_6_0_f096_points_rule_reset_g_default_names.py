# ruff: noqa: RUF002, RUF003
"""按产品文案重置获取类规则默认名 name（G1–G7）。

Revision ID: f096_points_rule_reset_g_default_names
Revises: f095_retire_auto_tag_library_id

仅改 point_rule.name；不改 display_name / 分值 / 启停。
按 rule_code 全租户覆盖写入系统默认名（与 SEED_RULES 对齐）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import table_exists
from bisheng.points.domain.constants.seed_rules import SEED_RULES

revision: str = "f096_points_rule_reset_g_default_names"
down_revision: str | Sequence[str] | None = "f095_retire_auto_tag_library_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_G_CODES = frozenset({"G1", "G2", "G3", "G4", "G5", "G6", "G7"})

# 本迁移前 G1–G7 的系统默认名（用于 downgrade）
_OLD_G_DEFAULT_NAMES: dict[str, str] = {
    "G1": "发布/上传到公共库",
    "G2": "发布/上传到部门库",
    "G3": "文档被收藏",
    "G4": "问答被采纳",
    "G5": "上传团队库文档",
    "G6": "上传科室库文档",
    "G7": "知识分享",
}


def _apply_names(names: dict[str, str]) -> None:
    """按编码更新已有规则的系统默认名；缺表则跳过。"""
    bind = op.get_bind()
    if not table_exists(bind, "point_rule"):
        return
    for code, name in names.items():
        bind.execute(
            sa.text("UPDATE point_rule SET name = :name WHERE rule_code = :code"),
            {"name": name, "code": code},
        )


def upgrade() -> None:
    """把 G1–G7 的 name 写成当前种子默认名。"""
    names = {
        rule["rule_code"]: str(rule["name"])
        for rule in SEED_RULES
        if rule["rule_code"] in _G_CODES
    }
    _apply_names(names)


def downgrade() -> None:
    """恢复本迁移前的 G1–G7 系统默认名。"""
    _apply_names(_OLD_G_DEFAULT_NAMES)
