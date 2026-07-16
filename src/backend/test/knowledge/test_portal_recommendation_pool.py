from datetime import date, datetime, timedelta, timezone

import pytest

from bisheng.knowledge.domain.services.portal_recommendation_pool_service import (
    PortalRecommendationPoolService,
    PortalRecommendationPoolState,
    PortalRecommendationView,
)
from bisheng.knowledge.domain.services.portal_recommendation_service import PortalRecommendationCandidate


def _candidate(file_id: int, *, space_id: int = 10) -> PortalRecommendationCandidate:
    return PortalRecommendationCandidate(space_id=space_id, file_id=file_id)


def test_hot_fresh_pool_is_three_to_one_with_dedup_and_exhaustion_backfill():
    hot = [_candidate(file_id) for file_id in (1, 2, 3, 4, 5)]
    fresh = [_candidate(file_id) for file_id in (1, 6, 7, 8)]

    result = PortalRecommendationPoolService.interleave_hot_fresh(hot, fresh, limit=8)

    assert [item.file_id for item in result] == [1, 2, 3, 6, 4, 5, 7, 8]


def test_pool_can_be_filled_by_one_stream_and_one_space():
    hot = [_candidate(file_id, space_id=99) for file_id in range(1, 501)]

    result = PortalRecommendationPoolService.interleave_hot_fresh(hot, [], limit=500)

    assert len(result) == 500
    assert {item.space_id for item in result} == {99}


def test_candidate_fuse_round_robins_domains_instead_of_truncating_first_pool():
    pools = {
        "A": [_candidate(file_id, space_id=1) for file_id in range(1, 8)],
        "B": [_candidate(file_id, space_id=2) for file_id in range(1, 8)],
    }

    result = PortalRecommendationPoolService.round_robin_limit(pools, limit=6)

    assert [(item.space_id, item.file_id) for item in result] == [
        (1, 1),
        (2, 1),
        (1, 2),
        (2, 2),
        (1, 3),
        (2, 3),
    ]


def test_rotation_runs_fourteen_days_then_cools_down_for_three_days():
    start = date(2026, 7, 1)
    active = PortalRecommendationPoolState(active_since=start)

    assert PortalRecommendationPoolService.is_rotation_active(active, start + timedelta(days=13))
    cooled = PortalRecommendationPoolService.advance_rotation(active, start + timedelta(days=14))
    assert cooled.cooldown_until == start + timedelta(days=17)
    assert not PortalRecommendationPoolService.is_rotation_active(cooled, start + timedelta(days=16))
    assert PortalRecommendationPoolService.is_rotation_active(cooled, start + timedelta(days=17))


def test_per_file_rotation_filters_cooldown_and_keeps_independent_pool_state():
    today = date(2026, 7, 15)
    candidates = [_candidate(1), _candidate(2), _candidate(3)]
    states = {
        candidates[0].key: PortalRecommendationPoolState(active_since=today - timedelta(days=13)),
        candidates[1].key: PortalRecommendationPoolState(active_since=today - timedelta(days=14)),
        candidates[2].key: PortalRecommendationPoolState(
            active_since=today - timedelta(days=20),
            cooldown_until=today,
        ),
    }

    eligible, next_states, filtered = PortalRecommendationPoolService.rotate_hot_candidates(
        candidates,
        states=states,
        today=today,
    )

    assert [item.file_id for item in eligible] == [1, 3]
    assert filtered == 1
    assert next_states[candidates[1].key].cooldown_until == today + timedelta(days=3)
    assert next_states[candidates[2].key] == PortalRecommendationPoolState(active_since=today)


def test_heat_deduplicates_user_file_natural_day_and_applies_source_weight_and_decay():
    now = datetime(2026, 7, 15, 12, tzinfo=timezone.utc)
    views = [
        PortalRecommendationView(1, 10, now - timedelta(hours=1), "natural"),
        PortalRecommendationView(1, 10, now - timedelta(hours=2), "natural"),
        PortalRecommendationView(2, 10, now - timedelta(days=7), "home_recommendation"),
        PortalRecommendationView(3, 10, now - timedelta(days=31), "natural"),
    ]

    count = PortalRecommendationPoolService.decayed_view_count(
        views,
        now=now,
        half_life_days=7,
        recommendation_source_weight=0.3,
    )

    # Same user/file/day is one view; the >30-day event is outside the window.
    assert count == pytest.approx(1 + 0.3 * 0.5, rel=1e-2)


def test_heat_natural_day_uses_shanghai_boundary_instead_of_utc_date():
    first = datetime(2026, 7, 14, 16, 30, tzinfo=timezone.utc)  # 2026-07-15 00:30 CST
    same_business_day = datetime(2026, 7, 15, 15, 30, tzinfo=timezone.utc)  # 23:30 CST

    count = PortalRecommendationPoolService.decayed_view_count(
        [
            PortalRecommendationView(1, 10, first, "natural"),
            PortalRecommendationView(1, 10, same_business_day, "natural"),
        ],
        now=datetime(2026, 7, 15, 16, tzinfo=timezone.utc),
        half_life_days=365,
        recommendation_source_weight=0.3,
    )

    assert count == pytest.approx(1.0, rel=1e-2)
    assert PortalRecommendationPoolService.business_date(first) == date(2026, 7, 15)
