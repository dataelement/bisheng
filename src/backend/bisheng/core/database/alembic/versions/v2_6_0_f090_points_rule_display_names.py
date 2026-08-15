# ruff: noqa: RUF002, RUF003
"""按产品文案更新积分规则展示名（G1–G7、R1–R3）。

Revision ID: f090_points_rule_display_names
Revises: f089_points_last_earned_at

仅改 point_rule.name；不改 rule_code / 分值 / 启停。
按 rule_code 全租户覆盖写入（含运营改过的同编码名称）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f090_points_rule_display_names"
down_revision: str | Sequence[str] | None = "f089_points_last_earned_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 产品给定展示名；G3/G5/G6 与旧种子相同，一并幂等写回。
_RULE_NAMES: dict[str, str] = {
    "G1": "发布/上传到公共库",
    "G2": "发布/上传到部门库",
    "G3": "文档被收藏",
    "G4": "问答被采纳",
    "G5": "上传团队库文档",
    "G6": "上传科室库文档",
    "G7": "知识分享",
    "R1": "色情低俗/暴力违法",
    "R2": "不当言论",
    "R3": "其他违反规范",
}

_OLD_RULE_NAMES: dict[str, str] = {
    "G1": "上传公共库文档",
    "G2": "上传部门库文档",
    "G3": "文档被收藏",
    "G4": "回答被采纳",
    "G5": "上传团队库文档",
    "G6": "上传科室库文档",
    "G7": "文档库间分享",
    "R1": "违规扣减 R1",
    "R2": "违规扣减 R2",
    "R3": "违规扣减 R3",
}


def _table_exists(bind, name: str) -> bool:
    """跨库检查表是否存在。"""
    return name in sa.inspect(bind).get_table_names()


def _apply_names(names: dict[str, str]) -> None:
    """按编码更新已有规则名称；缺表则跳过。"""
    bind = op.get_bind()
    if not _table_exists(bind, "point_rule"):
        return
    for code, name in names.items():
        bind.execute(
            sa.text("UPDATE point_rule SET name = :name WHERE rule_code = :code"),
            {"name": name, "code": code},
        )


def upgrade() -> None:
    """把 G1–G7、R1–R3 的展示名写成产品文案。"""
    _apply_names(_RULE_NAMES)


def downgrade() -> None:
    """恢复本迁移前的种子展示名。"""
    _apply_names(_OLD_RULE_NAMES)
