"""G5–G7 / M2/M3/M5/M7/M8：初始禁用且库内可为空；列表展示 —，启用/新增时须填分值与日上限。"""

from __future__ import annotations

DEFERRED_CONFIG_RULE_CODES = frozenset({"G5", "G6", "G7", "M2", "M3", "M5", "M7", "M8"})

# 兼容旧名
OPTIONAL_FIXED_SCORE_RULE_CODES = DEFERRED_CONFIG_RULE_CODES


def fixed_score_from_expr(score_expr: dict | None) -> int:
    """从 fixed 模式 score_expr 读取分值；非法/缺失视为 0。"""
    if not score_expr:
        return 0
    try:
        return max(0, int(score_expr.get("score") or 0))
    except (TypeError, ValueError):
        return 0


def validate_deferred_config_rule_can_enable(
    rule_code: str,
    *,
    score_expr: dict | None,
    daily_cap: int | None,
    status: str,
) -> str | None:
    """启用校验：延迟配置规则在 status=enabled 时必须已填写分值与日上限。

    Returns:
        错误文案；通过时返回 None。
    """
    code = (rule_code or "").strip().upper()
    if status != "enabled" or code not in DEFERRED_CONFIG_RULE_CODES:
        return None
    if fixed_score_from_expr(score_expr) <= 0:
        return "启用规则须填写积分分值"
    if daily_cap is None:
        return "启用规则须填写每日上限"
    return None


# 兼容旧调用名
validate_optional_fixed_rule_can_enable = validate_deferred_config_rule_can_enable
