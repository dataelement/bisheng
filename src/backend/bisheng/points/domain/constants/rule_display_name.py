"""积分规则展示名解析（默认名 vs 运营可改展示名）。"""

from __future__ import annotations

from typing import Protocol


class PointRuleNameSource(Protocol):
    rule_code: str
    name: str
    display_name: str | None


def resolve_point_rule_display_name(rule: PointRuleNameSource) -> str:
    """返回用户可见规则名：优先 ``display_name``，否则回退 ``name`` / ``rule_code``。"""
    for candidate in (getattr(rule, "display_name", None), rule.name, rule.rule_code):
        text = str(candidate or "").strip()
        if text:
            return text
    return str(rule.rule_code or "").strip()
