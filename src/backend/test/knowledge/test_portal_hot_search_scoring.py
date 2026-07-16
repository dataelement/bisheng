from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from bisheng.knowledge.domain.schemas.portal_hot_search_schema import (
    CleanedSearchRecord,
    HotSearchIntentGroup,
)
from bisheng.knowledge.domain.services.portal_hot_search_scoring_service import (
    PortalHotSearchScoringService,
    intent_key_for,
)

_SH = ZoneInfo("Asia/Shanghai")
_NOW = datetime(2026, 7, 16, 2, 0, tzinfo=timezone.utc)
_TODAY = _NOW.astimezone(_SH).date()


def _rec(user_id: int, query: str, age_days: int) -> CleanedSearchRecord:
    local_date = _TODAY - timedelta(days=age_days)
    searched_at = datetime(local_date.year, local_date.month, local_date.day, 12, 0, tzinfo=_SH)
    return CleanedSearchRecord(
        user_id=user_id,
        cleaned_query=query,
        searched_at=searched_at.astimezone(timezone.utc),
        local_date=local_date,
    )


def _group(canonical: str, *members: str) -> HotSearchIntentGroup:
    return HotSearchIntentGroup(
        intent_key=intent_key_for(canonical),
        canonical_query=canonical,
        member_queries=list(members) or [canonical],
    )


def test_scoring_weights_windows_and_qualifies_top_item():
    q = "设备检修安全要求"
    group = _group(q, q)
    records = []
    # 5 distinct users in the last 7 days -> count_7d = 5
    for uid in range(1, 6):
        records.append(_rec(uid, q, age_days=1))
    # 3 distinct users in days 8-30 -> count_8_30d = 3
    for uid in range(1, 4):
        records.append(_rec(uid, q, age_days=10))
    # duplicate same user same day must not double count
    records.append(_rec(1, q, age_days=1))

    svc = PortalHotSearchScoringService(min_unique_users=5, min_search_count=8)
    items = svc.score([group], records, now=_NOW, top_k=5)

    assert len(items) == 1
    item = items[0]
    assert item.search_count_7d == 5
    assert item.search_count_8_30d == 3
    assert item.heat_score == 2 * 5 + 3
    assert item.unique_users == 5
    assert item.qualified is True
    assert item.final_rank == 1


def test_scoring_excludes_below_thresholds_from_rank():
    q = "能源管理制度"
    group = _group(q, q)
    # only 3 users, 3 records -> below both thresholds
    records = [_rec(uid, q, age_days=2) for uid in range(1, 4)]
    svc = PortalHotSearchScoringService(min_unique_users=5, min_search_count=8)
    items = svc.score([group], records, now=_NOW, top_k=5)
    assert len(items) == 1
    assert items[0].qualified is False
    assert items[0].final_rank is None


def test_scoring_orders_by_heat_then_assigns_sequential_ranks():
    strong = "设备检修安全要求"
    weak = "环保设施运行要求"
    groups = [_group(strong, strong), _group(weak, weak)]
    records = []
    for uid in range(1, 7):
        records.append(_rec(uid, strong, age_days=1))  # 6 recent -> heat 12
    for uid in range(1, 6):
        records.append(_rec(uid, strong, age_days=10))  # +5 older
    for uid in range(10, 16):
        records.append(_rec(uid, weak, age_days=1))  # 6 recent -> heat 12
    for uid in range(10, 13):
        records.append(_rec(uid, weak, age_days=10))  # +3 older

    svc = PortalHotSearchScoringService(min_unique_users=5, min_search_count=8)
    items = svc.score(groups, records, now=_NOW, top_k=5)
    assert [i.canonical_query for i in items] == [strong, weak]
    assert items[0].final_rank == 1
    assert items[1].final_rank == 2
