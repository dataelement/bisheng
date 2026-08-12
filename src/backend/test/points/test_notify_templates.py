"""积分通知模板测试。"""

from bisheng.points.domain.constants.notify_templates import NOTIFY_TEMPLATES, POINTS_CHANGED_ACTION_CODE


def test_templates_cover_supported_business_events():
    assert {"earn_publish", "earn_share", "earn_favorite", "earn_adopt", "deduct_admin", "adjust_admin"} <= set(NOTIFY_TEMPLATES)
    assert POINTS_CHANGED_ACTION_CODE == "points_changed"
