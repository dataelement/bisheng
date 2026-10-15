"""知识文档违规删除的档位, 豁免和被扣人判定."""

from __future__ import annotations

from collections.abc import Iterable

from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.points.domain.constants.monthly_reward_rules import MonthlyRuleMatcher

# 数值越大, 影响范围越高. 科室库与团队库同一档.
_SCOPE_RANK = {
    KnowledgeSpaceLevelEnum.PUBLIC.value: 3,
    KnowledgeSpaceLevelEnum.DEPARTMENT.value: 2,
    KnowledgeSpaceLevelEnum.TEAM.value: 1,
    KnowledgeSpaceLevelEnum.TEAM_KS.value: 1,
}
_TIER_BY_LEVEL = {
    KnowledgeSpaceLevelEnum.PUBLIC.value: "public",
    KnowledgeSpaceLevelEnum.DEPARTMENT.value: "department",
    KnowledgeSpaceLevelEnum.TEAM.value: "team",
    KnowledgeSpaceLevelEnum.TEAM_KS.value: "team",
}


def highest_scope_tier(levels: Iterable[str]) -> str | None:
    """在非个人库等级里取影响范围最高的扣分档.

    Args:
        levels: 库等级, 如 public, department, team, team_ks, personal.

    Returns:
        public, department 或 team. 没有非个人库时为 None.
    """
    best_rank = 0
    best_tier: str | None = None
    for raw in levels:
        level = str(getattr(raw, "value", raw) or "")
        rank = _SCOPE_RANK.get(level, 0)
        if rank > best_rank:
            best_rank = rank
            best_tier = _TIER_BY_LEVEL[level]
    return best_tier


def is_personal_level(level: str | None) -> bool:
    """判断库等级是不是个人库.

    Args:
        level: 知识空间等级.

    Returns:
        缺失或 personal 时为 True. 违规删除不从个人库发起.
    """
    value = str(getattr(level, "value", level) or "")
    return value in ("", KnowledgeSpaceLevelEnum.PERSONAL.value)


def monthly_award_exempt(
    *,
    uploader_id: int,
    space_levels: dict[int, str],
    owners_by_space: dict[int, set[int]],
    managers_by_space: dict[int, set[int]],
    enabled_matchers: list[MonthlyRuleMatcher],
) -> bool:
    """删除当时, 可见的非个人库里是否有上传者的有效月奖身份.

    Args:
        uploader_id: 原始上传者.
        space_levels: 空间 id 到库等级.
        owners_by_space: 各空间所有者.
        managers_by_space: 各空间管理者.
        enabled_matchers: 当前启用且分值大于 0 的月奖匹配器.

    Returns:
        命中任一已启用月奖身份时为 True.
    """
    for space_id, level in space_levels.items():
        if is_personal_level(level):
            continue
        owners = owners_by_space.get(int(space_id), set())
        managers = managers_by_space.get(int(space_id), set())
        for matcher in enabled_matchers:
            if level not in matcher.levels:
                continue
            if "owner" in matcher.roles and int(uploader_id) in owners:
                return True
            if "manager" in matcher.roles and int(uploader_id) in managers:
                return True
    return False


def resolve_payee_id(original_uploader_id: int | None, entry_user_id: int | None) -> int | None:
    """确定被扣人.

    Args:
        original_uploader_id: 文档上的原始上传者.
        entry_user_id: 管理入口上的上传人.

    Returns:
        被扣用户 id. 两个都没有时为 None.
    """
    if original_uploader_id is not None and int(original_uploader_id) > 0:
        return int(original_uploader_id)
    if entry_user_id is not None and int(entry_user_id) > 0:
        return int(entry_user_id)
    return None


def deduct_block_reason(
    *,
    rule_code: str | None,
    payee_id: int | None,
    operator_id: int,
    exempt: bool,
) -> str | None:
    """给出本次不扣分的原因.

    Args:
        rule_code: 操作者选择的规则. 空表示只删不扣.
        payee_id: 被扣人.
        operator_id: 操作者.
        exempt: 是否命中月奖豁免.

    Returns:
        不扣分原因. 需要扣分时为 None.
    """
    if not (rule_code or "").strip():
        return "no_rule"
    if payee_id is None:
        return "payee_missing"
    if int(operator_id) == int(payee_id):
        return "self_author"
    if exempt:
        return "monthly_award_exempt"
    return None
