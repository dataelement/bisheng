from datetime import datetime, timedelta, timezone

import pytest

from bisheng.knowledge.domain.services.portal_recommendation_service import (
    PortalRecommendationCandidate,
    PortalRecommendationScoringConfig,
    PortalRecommendationService,
)


def _candidate(
    file_id: int,
    *,
    domain_score: float = 0,
    interest_score: float = 0,
    hot_score: float = 0,
    fresh_score: float = 0,
) -> PortalRecommendationCandidate:
    return PortalRecommendationCandidate(
        space_id=10,
        file_id=file_id,
        domain_score=domain_score,
        interest_score=interest_score,
        hot_score=hot_score,
        fresh_score=fresh_score,
    )


def test_active_features_are_dynamically_normalized():
    service = PortalRecommendationService()
    candidate = _candidate(
        1,
        domain_score=100,
        interest_score=50,
        hot_score=20,
        fresh_score=40,
    )

    all_features = service.score_candidates(
        [candidate],
        tenant_id=5,
        user_id=7,
        has_domain_signal=True,
        has_interest_signal=True,
    )[0]
    generic_only = service.score_candidates(
        [candidate],
        tenant_id=5,
        user_id=7,
        has_domain_signal=False,
        has_interest_signal=False,
    )[0]

    assert all_features.base_score == pytest.approx(59)
    assert generic_only.base_score == pytest.approx(30)


@pytest.mark.parametrize(
    ("age_days", "expected_penalty"),
    [(0, -80), (7, -80), (8, -50), (30, -50), (31, -30), (90, -30), (91, 0)],
)
def test_recent_reads_are_penalized_but_remain_eligible(age_days: int, expected_penalty: int):
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    candidate = _candidate(1, hot_score=100, fresh_score=100)

    scored = PortalRecommendationService().score_candidates(
        [candidate],
        tenant_id=5,
        user_id=7,
        has_domain_signal=False,
        has_interest_signal=False,
        read_at_by_key={(10, 1): now - timedelta(days=age_days)},
        now=now,
    )

    assert len(scored) == 1
    assert scored[0].read_penalty == expected_penalty
    assert scored[0].final_score == pytest.approx(100 + expected_penalty)


def test_stable_shuffle_uses_anchor_groups_and_ignores_unrelated_config_version():
    service = PortalRecommendationService()
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    candidates = [
        _candidate(1, hot_score=100, fresh_score=100),
        _candidate(2, hot_score=97, fresh_score=97),
        _candidate(3, hot_score=94, fresh_score=94),
        _candidate(4, hot_score=80, fresh_score=80),
    ]
    config = PortalRecommendationScoringConfig(stable_shuffle_score_gap=5, stable_shuffle_cycle_days=7)

    first = service.score_candidates(
        candidates,
        tenant_id=5,
        user_id=7,
        has_domain_signal=False,
        has_interest_signal=False,
        config=config,
        now=now,
        config_version=1,
    )
    second = service.score_candidates(
        candidates,
        tenant_id=5,
        user_id=7,
        has_domain_signal=False,
        has_interest_signal=False,
        config=config,
        now=now,
        config_version=999,
    )

    assert [item.file_id for item in first] == [item.file_id for item in second]
    assert {item.file_id for item in first[:2]} == {1, 2}
    # file 3 is within five points of file 2, but outside the file-1 anchor group.
    assert first[2].file_id == 3
    assert first[3].file_id == 4


@pytest.mark.parametrize(
    "config",
    [
        PortalRecommendationScoringConfig(stable_shuffle_score_gap=-0.1),
        PortalRecommendationScoringConfig(stable_shuffle_cycle_days=0),
    ],
)
def test_scoring_config_rejects_invalid_stable_shuffle_boundaries(config):
    with pytest.raises(ValueError):
        config.validate()


def test_active_signal_flags_drop_empty_domain_and_invisible_interest_features():
    candidates = [_candidate(1, hot_score=60, fresh_score=40)]

    assert PortalRecommendationService.active_signal_flags(candidates) == (False, False)


@pytest.mark.asyncio
async def test_multi_domain_paging_refills_sparse_and_duplicate_sources():
    pages = {
        "D01": [_candidate(1), _candidate(2)],
        "D02": [_candidate(2), _candidate(3), _candidate(4), _candidate(5)],
    }

    async def load_page(code, offset, limit):
        return pages[code][offset : offset + limit]

    result = await PortalRecommendationService.load_unique_domain_pool_candidates(
        ["D02", "D01"],
        load_page=load_page,
        reserved_keys={_candidate(1).key},
        page_size=2,
    )

    assert [item.file_id for item in result["D01"]] == [2]
    assert [item.file_id for item in result["D02"]] == [3, 4, 5]


def test_cached_order_is_retained_while_recomputed_candidates_fill_after_it():
    cached = [_candidate(1), _candidate(2)]
    recomputed = [_candidate(2), _candidate(3), _candidate(4)]

    merged = PortalRecommendationService.merge_ordered_candidates(cached, recomputed)

    assert [item.file_id for item in merged] == [1, 2, 3, 4]
