"""积分通知模板测试。"""

from bisheng.points.domain.constants.notify_templates import (
    NOTIFY_TEMPLATES,
    POINTS_CHANGED_ACTION_CODE,
    format_deduct_notify_reason,
    resolve_earn_notify,
)


def test_templates_cover_supported_business_events():
    assert {
        "earn_publish",
        "earn_share",
        "earn_favorite",
        "earn_adopt",
        "earn_monthly",
        "deduct_admin",
        "adjust_admin_add",
        "adjust_admin_deduct",
    } <= set(NOTIFY_TEMPLATES)
    assert POINTS_CHANGED_ACTION_CODE == "points_changed"


def test_resolve_earn_notify_maps_g_rules():
    """G* 规则映射到对应模板；未知编码回退 earn_monthly。"""
    assert resolve_earn_notify("G2", rule_name="上传部门库文档", delta=2) == (
        "earn_publish",
        {"library_name": "部门库", "delta": 2},
    )
    assert resolve_earn_notify("G1", rule_name="上传公共库文档", delta=3) == (
        "earn_publish",
        {"library_name": "公共库", "delta": 3},
    )
    assert resolve_earn_notify("G3", rule_name="文档被收藏", delta=5, favorite_count=75) == (
        "earn_favorite",
        {"favorite_count": 75, "delta": 5},
    )
    assert resolve_earn_notify("G4", rule_name="回答被采纳", delta=3) == (
        "earn_adopt",
        {"delta": 3},
    )
    assert resolve_earn_notify("G7", rule_name="分享", delta=2) == (
        "earn_share",
        {"delta": 2},
    )
    assert resolve_earn_notify("M1", rule_name="公共库所有者月奖", delta=200) == (
        "earn_monthly",
        {"rule_name": "公共库所有者月奖", "delta": 200},
    )


def test_notify_templates_render_prd_copy():
    """站内信完整文案对齐 PRD。"""
    assert NOTIFY_TEMPLATES["earn_publish"].format(library_name="部门库", delta=2) == (
        "您上传/发布文档至部门库，获得2积分，您可前往【我的积分】查看完整记录；"
    )
    assert NOTIFY_TEMPLATES["earn_favorite"].format(favorite_count=75, delta=5) == (
        "您的文档被收藏75次，获得5积分，您可前往【我的积分】查看完整记录；"
    )
    assert NOTIFY_TEMPLATES["earn_adopt"].format(delta=3) == (
        "您的回答被采纳，获得3积分，您可前往【我的积分】查看完整记录；"
    )
    assert NOTIFY_TEMPLATES["deduct_admin"].format(delta=100, reason="违规扣减 R1") == (
        "管理员为您扣减100积分，原因：违规扣减 R1，您可前往【我的积分】查看完整记录；"
    )
    assert NOTIFY_TEMPLATES["adjust_admin_add"].format(delta=10, reason="活动奖励") == (
        "管理员为您增加10积分，原因：活动奖励，您可前往【我的积分】查看完整记录；"
    )


def test_format_deduct_notify_reason_prefers_remark():
    assert format_deduct_notify_reason(rule_name="违规扣减 R1", remark="内容违规") == "内容违规"
    assert format_deduct_notify_reason(rule_name="违规扣减 R1", remark="") == "违规扣减 R1"
