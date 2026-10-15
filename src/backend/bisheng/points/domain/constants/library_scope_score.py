"""知识文档扣减规则 R4-R6 的库档分值."""

from __future__ import annotations

from typing import Any

LIBRARY_SCOPE_RULE_CODES = frozenset({"R4", "R5", "R6"})
LIBRARY_SCOPE_TIERS = ("public", "department", "team")
_INVALID_MSG = "知识文档扣减规则须分别配置公共库, 部门库, 团队库的正整数分值"


def is_library_scope_rule(rule_code: str | None) -> bool:
    """判断编码是不是知识文档三档扣减规则.

    Args:
        rule_code: 规则编码.

    Returns:
        R4, R5, R6 为 True.
    """
    return (rule_code or "").strip().upper() in LIBRARY_SCOPE_RULE_CODES


def validate_library_scope_score_expr(score_expr: dict[str, Any] | None) -> str | None:
    """校验 library_scope 分值. 通过返回 None.

    Args:
        score_expr: 规则上的分值 JSON.

    Returns:
        非法时的中文原因. 合法时为 None.
    """
    expr = score_expr or {}
    if str(expr.get("mode") or "") != "library_scope":
        return _INVALID_MSG
    for key in LIBRARY_SCOPE_TIERS:
        raw = expr.get(key)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
            return _INVALID_MSG
    return None


def library_scope_score(score_expr: dict[str, Any] | None, tier: str) -> int:
    """读取某一档的扣分绝对值.

    Args:
        score_expr: 规则上的分值 JSON.
        tier: public, department 或 team. 科室库调用前先映射成 team.

    Returns:
        该档正整数分值.

    Raises:
        ValueError: 分值结构或档位非法.
    """
    if validate_library_scope_score_expr(score_expr):
        raise ValueError("invalid library_scope score_expr")
    normalized = tier.strip().lower()
    if normalized not in LIBRARY_SCOPE_TIERS:
        raise ValueError("invalid library scope tier")
    return int((score_expr or {})[normalized])
