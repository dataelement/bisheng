"""G3 等阶梯规则 score_expr 校验。"""

from __future__ import annotations

from typing import Any

# 与门户调分绝对值上限对齐，防止异常大 lifetime_cap。
G3_LIFETIME_CAP_MAX = 10_000


def _parse_tier_rows(tiers: Any) -> list[tuple[int, int]] | None:
    """解析 tiers 为 (threshold, score) 列表；结构非法时返回 None。"""
    if not isinstance(tiers, list) or not tiers:
        return None
    parsed: list[tuple[int, int]] = []
    for raw in tiers:
        if not isinstance(raw, dict):
            return None
        try:
            threshold = int(raw.get("threshold"))
            score = int(raw.get("score"))
        except (TypeError, ValueError):
            return None
        if threshold < 0 or score < 0:
            return None
        parsed.append((threshold, score))
    parsed.sort(key=lambda row: row[0])
    for i in range(1, len(parsed)):
        if parsed[i][0] <= parsed[i - 1][0]:
            return None
        if parsed[i][1] < parsed[i - 1][1]:
            return None
    return parsed


def validate_g3_tier_score_expr(score_expr: dict[str, Any] | None) -> str | None:
    """校验 G3 阶梯 score_expr；通过返回 None，否则返回业务错误文案。

    Args:
        score_expr: 规则 score_expr JSON

    Returns:
        错误文案或 None
    """
    if not score_expr or score_expr.get("mode") != "tier":
        return None
    tiers = _parse_tier_rows(score_expr.get("tiers"))
    if not tiers:
        return "G3 阶梯规则须至少配置一档且阈值、分值合法"
    try:
        lifetime_cap = int(score_expr.get("lifetime_cap"))
    except (TypeError, ValueError):
        return "G3 终身上限须为非负整数"
    if lifetime_cap < 0:
        return "G3 终身上限须为非负整数"
    if lifetime_cap > G3_LIFETIME_CAP_MAX:
        return f"G3 终身上限最大为 {G3_LIFETIME_CAP_MAX} 分"
    top_score = tiers[-1][1]
    if lifetime_cap < top_score:
        return "G3 终身上限不得低于最高档奖励分"
    return None
