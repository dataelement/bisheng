"""知识空间等级到入库类积分规则编码的映射。"""

from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

# personal / favorite 不计分；G5≈团队库，G6≈科室库（TEAM_KS）。
SPACE_LEVEL_TO_EARN_RULE: dict[str, str] = {
    KnowledgeSpaceLevelEnum.PUBLIC.value: "G1",
    KnowledgeSpaceLevelEnum.DEPARTMENT.value: "G2",
    KnowledgeSpaceLevelEnum.TEAM.value: "G5",
    KnowledgeSpaceLevelEnum.TEAM_KS.value: "G6",
}


def earn_rule_for_space_level(space_level: str | None) -> str | None:
    """返回入库成功应对应的 G* 编码；个人库等返回 None。"""
    if not space_level:
        return None
    value = getattr(space_level, "value", space_level)
    return SPACE_LEVEL_TO_EARN_RULE.get(str(value))
