"""月奖 M* 与 space.level / 成员角色的匹配表。

矩阵（与 seed_rules M1–M8 对齐）：
  public     → M1 creator / M2 admin
  department → M3 creator / M4 admin
  team_ks    → M5 creator / M6 admin
  team       → M7 creator / M8 admin
多角色命中时取最高分（见 pick_highest_reward）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MonthlyRuleMatcher:
    """单个 M* 规则对应的空间等级与成员角色集合。"""

    levels: tuple[str, ...]
    roles: tuple[str, ...]


MONTHLY_RULE_MATCHERS: dict[str, MonthlyRuleMatcher] = {
    "M1": MonthlyRuleMatcher(levels=("public",), roles=("creator",)),
    "M2": MonthlyRuleMatcher(levels=("public",), roles=("admin",)),
    "M3": MonthlyRuleMatcher(levels=("department",), roles=("creator",)),
    "M4": MonthlyRuleMatcher(levels=("department",), roles=("admin",)),
    "M5": MonthlyRuleMatcher(levels=("team_ks",), roles=("creator",)),
    "M6": MonthlyRuleMatcher(levels=("team_ks",), roles=("admin",)),
    "M7": MonthlyRuleMatcher(levels=("team",), roles=("creator",)),
    "M8": MonthlyRuleMatcher(levels=("team",), roles=("admin",)),
}


def fixed_score(score_expr: dict | None) -> int:
    """读取 fixed 模式分值；非 fixed 或非法返回 0。"""
    expr = score_expr or {}
    if expr.get("mode") != "fixed":
        return 0
    try:
        return int(expr.get("score") or 0)
    except (TypeError, ValueError):
        return 0


def pick_highest_reward(
    candidates: list[tuple[str, int]],
) -> tuple[str, int] | None:
    """多角色取最高分；同分取规则编码字典序以保证稳定。"""
    if not candidates:
        return None
    candidates = [(code, int(score)) for code, score in candidates if int(score) > 0]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[1], item[0]))
    return candidates[0]
