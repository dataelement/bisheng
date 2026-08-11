"""积分通知模板测试。"""

from bisheng.points.domain.constants.notify_templates import (
    NOTIFY_TEMPLATES,
    POINTS_CHANGED_ACTION_CODE,
    resolve_earn_notify,
)


def test_templates_cover_supported_business_events():
    assert {
        "earn_publish",
        "earn_share",
        "earn_favorite",
        "earn_adopt",
        "deduct_admin",
        "adjust_admin",
    } <= set(NOTIFY_TEMPLATES)
    assert POINTS_CHANGED_ACTION_CODE == "points_changed"


def test_resolve_earn_notify_maps_g_rules():
    """G* 规则映射到对应模板；未知编码回退 earn_publish。"""
    assert resolve_earn_notify("G2", rule_name="上传部门库文档", delta=2) == (
        "earn_publish",
        {"rule_name": "上传部门库文档", "delta": 2},
    )
    assert resolve_earn_notify("G3", rule_name="文档被收藏", delta=5) == (
        "earn_favorite",
        {"delta": 5},
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
        "earn_publish",
        {"rule_name": "公共库所有者月奖", "delta": 200},
    )
