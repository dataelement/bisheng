"""积分站内信模板；文案随代码发布，不允许后台动态修改。"""

NOTIFY_TEMPLATES = {
    "earn_publish": ("您上传/发布文档至{library_name}，获得{delta}积分，您可前往【我的积分】查看完整记录；"),
    "earn_share": ("您因知识库间分享获得{delta}积分，您可前往【我的积分】查看完整记录；"),
    "earn_favorite": ("您的文档被收藏{favorite_count}次，获得{delta}积分，您可前往【我的积分】查看完整记录；"),
    "earn_adopt": ("您的回答被采纳，获得{delta}积分，您可前往【我的积分】查看完整记录；"),
    "earn_monthly": ("您因「{rule_name}」获得{delta}积分，您可前往【我的积分】查看完整记录；"),
    "deduct_admin": ("管理员为您扣减{delta}积分，原因：{reason}，您可前往【我的积分】查看完整记录；"),
    "adjust_admin_add": ("管理员为您增加{delta}积分，原因：{reason}，您可前往【我的积分】查看完整记录；"),
    "adjust_admin_deduct": ("管理员为您扣减{delta}积分，原因：{reason}，您可前往【我的积分】查看完整记录；"),
}
POINTS_CHANGED_ACTION_CODE = "points_changed"

# 自动获取类规则 → 模板；月奖等未列出的 earn 回退 earn_monthly。
EARN_RULE_NOTIFY_TEMPLATE: dict[str, str] = {
    "G1": "earn_publish",
    "G2": "earn_publish",
    "G3": "earn_favorite",
    "G4": "earn_adopt",
    "G5": "earn_publish",
    "G6": "earn_publish",
    "G7": "earn_share",
}

# 上传/发布类规则 → 知识库层级展示名（PRD 站内信文案）。
EARN_RULE_LIBRARY_LABEL: dict[str, str] = {
    "G1": "公共库",
    "G2": "部门库",
    "G5": "团队库",
    "G6": "科室库",
}


def format_deduct_notify_reason(*, rule_name: str | None = None, remark: str | None = None) -> str:
    """扣减站内信原因：优先运营填写的备注，否则用扣减项名称。"""
    text = (remark or "").strip() or (rule_name or "").strip()
    return text or "—"


def resolve_earn_notify(
    rule_code: str,
    *,
    rule_name: str,
    delta: int,
    favorite_count: int | None = None,
) -> tuple[str, dict]:
    """按规则编码解析站内信模板与渲染参数。

    Args:
        rule_code: 积分规则编码（如 G2、M1）。
        rule_name: 规则展示名；月奖等回退模板使用。
        delta: 本次实际入账分值（正数）。
        favorite_count: G3 文档累计收藏人数（站内信展示「被收藏 N 次」）。

    Returns:
        (template_code, format kwargs)。
    """
    code = (rule_code or "").strip().upper()
    template = EARN_RULE_NOTIFY_TEMPLATE.get(code)
    if template is None:
        return "earn_monthly", {"rule_name": rule_name or code, "delta": int(delta)}
    if template == "earn_favorite":
        count = int(favorite_count) if favorite_count is not None else int(delta)
        return template, {"favorite_count": count, "delta": int(delta)}
    if template == "earn_adopt":
        return template, {"delta": int(delta)}
    if template == "earn_share":
        return template, {"delta": int(delta)}
    if template == "earn_publish":
        library_name = EARN_RULE_LIBRARY_LABEL.get(code, rule_name or code)
        return template, {"library_name": library_name, "delta": int(delta)}
    return template, {"delta": int(delta)}
