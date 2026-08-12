"""积分站内信模板；文案随代码发布，不允许后台动态修改。"""

NOTIFY_TEMPLATES = {
    "earn_publish": "你因「{rule_name}」获得 {delta} 积分。",
    "earn_share": "你因知识库间分享获得 {delta} 积分。",
    "earn_favorite": "你的文档被收藏，获得 {delta} 积分。",
    "earn_adopt": "你的回答被采纳，获得 {delta} 积分。",
    "deduct_admin": "因「{rule_name}」扣减 {delta} 积分。原因：{reason}",
    "adjust_admin": "管理员调整了你的积分 {delta}。原因：{reason}",
}
POINTS_CHANGED_ACTION_CODE = "points_changed"

# 自动获取类规则 → 模板；月奖等未列出的 earn 回退 earn_publish。
EARN_RULE_NOTIFY_TEMPLATE: dict[str, str] = {
    "G1": "earn_publish",
    "G2": "earn_publish",
    "G3": "earn_favorite",
    "G4": "earn_adopt",
    "G5": "earn_publish",
    "G6": "earn_publish",
    "G7": "earn_share",
}


def resolve_earn_notify(rule_code: str, *, rule_name: str, delta: int) -> tuple[str, dict]:
    """按规则编码解析站内信模板与渲染参数。

    Args:
        rule_code: 积分规则编码（如 G2、M1）。
        rule_name: 规则展示名，用于 earn_publish。
        delta: 本次实际入账分值（正数）。

    Returns:
        (template_code, format kwargs)。
    """
    code = (rule_code or "").strip().upper()
    template = EARN_RULE_NOTIFY_TEMPLATE.get(code, "earn_publish")
    if template == "earn_publish":
        return template, {"rule_name": rule_name or code, "delta": int(delta)}
    return template, {"delta": int(delta)}
