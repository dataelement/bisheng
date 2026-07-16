from datetime import datetime, timezone

from bisheng.knowledge.domain.schemas.portal_hot_search_schema import PortalSearchRecord
from bisheng.knowledge.domain.services.portal_hot_search_filter_service import (
    PortalHotSearchFilterService,
)
from bisheng.knowledge.domain.services.portal_hot_search_text_utils import (
    normalize_hot_search_query,
)


def test_normalize_collapses_whitespace_and_strips_trailing_punctuation():
    assert normalize_hot_search_query("  设备   检修 ") == "设备 检修"
    assert normalize_hot_search_query("设备检修。") == "设备检修"
    assert normalize_hot_search_query("设备检修？") == "设备检修"


def test_normalize_unifies_fullwidth_and_lowercases():
    assert normalize_hot_search_query("ＡＢＣ") == "abc"
    assert normalize_hot_search_query("ＳＴＥＥＬ 安全") == "steel 安全"
    # full-width digits unified to half width
    assert normalize_hot_search_query("１２３ABC") == "123abc"


def _record(user_id: int, query: str, when: datetime) -> PortalSearchRecord:
    return PortalSearchRecord(user_id=user_id, query=query, normalized_query=query.casefold(), searched_at=when)


def test_filter_excludes_invalid_content():
    svc = PortalHotSearchFilterService()
    assert svc.is_valid_query("北京") is True
    assert svc.is_valid_query("京") is False  # < 2 han
    assert svc.is_valid_query("检" * 51) is False  # > 50 han
    assert svc.is_valid_query("12345") is False  # pure digits
    assert svc.is_valid_query("！！！") is False  # pure symbols
    assert svc.is_valid_query("我的手机13800138000") is False  # phone
    assert svc.is_valid_query("身份证11010119900307621x") is False  # id card / phone-like digits


def test_filter_cleans_before_dedup_same_user_same_day():
    svc = PortalHotSearchFilterService()
    day = datetime(2026, 7, 10, 3, 0, tzinfo=timezone.utc)
    records = [
        _record(1, "设备检修安全", day),
        _record(1, "设备检修安全。", day.replace(hour=5)),  # trailing punctuation -> same cleaned query
        _record(2, "设备检修安全", day),
    ]
    cleaned = svc.filter_and_dedup(records)
    # user1 collapses to one; user2 separate -> 2 records
    keys = {(r.user_id, r.cleaned_query) for r in cleaned}
    assert (1, "设备检修安全") in keys
    assert (2, "设备检修安全") in keys
    assert len([r for r in cleaned if r.user_id == 1]) == 1


def test_filter_drops_invalid_and_keeps_earliest():
    svc = PortalHotSearchFilterService()
    day = datetime(2026, 7, 10, 8, 0, tzinfo=timezone.utc)
    records = [
        _record(1, "设备检修安全", day),
        _record(1, "设备检修安全", day.replace(hour=2)),  # earlier same day
        _record(3, "12345", day),  # invalid
    ]
    cleaned = svc.filter_and_dedup(records)
    assert len(cleaned) == 1
    assert cleaned[0].user_id == 1
    assert cleaned[0].searched_at.hour == 2
