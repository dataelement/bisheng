from datetime import datetime, timedelta, timezone

import pytest

from bisheng.knowledge.domain.repositories.interfaces.portal_recommendation_telemetry_repository import (
    PortalInterestHit,
    PortalSearchQuerySignal,
)
from bisheng.knowledge.domain.services.portal_recommendation_behavior_service import (
    PortalRecommendationBehaviorService,
    normalize_search_query,
)


class _StateRepository:
    def __init__(self):
        self.behavior_versions: list[tuple[int, int]] = []
        self.reads = []
        self.interests = None

    async def increment_behavior_version(self, tenant_id: int, user_id: int) -> int:
        self.behavior_versions.append((tenant_id, user_id))
        return len(self.behavior_versions)

    async def record_read(self, tenant_id, user_id, space_id, file_id, read_at):
        self.reads.append((tenant_id, user_id, space_id, file_id, read_at))

    async def record_read_and_increment_behavior_version(
        self, tenant_id, user_id, space_id, file_id, read_at
    ):
        self.reads.append((tenant_id, user_id, space_id, file_id, read_at))
        self.behavior_versions.append((tenant_id, user_id))
        return len(self.behavior_versions)

    async def replace_interest(self, tenant_id, user_id, entries, ttl_seconds):
        self.interests = (tenant_id, user_id, entries, ttl_seconds)


class _TelemetryRepository:
    def __init__(self, now):
        self.now = now
        self.received_queries = None

    async def list_recent_search_queries(self, tenant_id, user_id, since, limit):
        assert tenant_id == 5
        assert user_id == 7
        assert limit == 20
        assert since == self.now - timedelta(days=90)
        return [
            PortalSearchQuerySignal("steel", self.now - timedelta(days=2), 2),
            PortalSearchQuerySignal("safety", self.now - timedelta(days=40), 1),
        ]

    async def search_interest_candidates(self, tenant_id, queries, limit):
        self.received_queries = queries
        assert tenant_id == 5
        assert limit == 50
        return [
            PortalInterestHit(10, 100, {"STEEL": (1, 0, 0), "safety": (0, 1, 0)}),
            PortalInterestHit(10, 101, {"steel": (0, 0, 1)}),
        ]


def test_query_normalization_trims_collapses_spaces_and_folds_english_case():
    assert normalize_search_query("  安全   STEEL  ") == "安全 steel"


@pytest.mark.asyncio
async def test_search_increments_version_and_queues_current_query_for_es_refresh_gap():
    state = _StateRepository()
    queued = []
    service = PortalRecommendationBehaviorService(
        state_repository=state,
        telemetry_repository=None,
        enqueue_interest_rebuild=lambda **kwargs: queued.append(kwargs),
    )
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)

    await service.record_search(tenant_id=5, user_id=7, query="  安全   STEEL ", searched_at=now)

    assert state.behavior_versions == [(5, 7)]
    assert queued == [
        {"tenant_id": 5, "user_id": 7, "current_query": "安全 steel", "searched_at": now}
    ]
    assert not hasattr(state, "query")
    assert not hasattr(state, "query")


@pytest.mark.asyncio
async def test_read_updates_last_seen_and_behavior_version():
    state = _StateRepository()
    service = PortalRecommendationBehaviorService(state_repository=state, telemetry_repository=None)
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)

    await service.record_read(tenant_id=5, user_id=7, space_id=10, file_id=100, read_at=now)

    assert state.reads == [(5, 7, 10, 100, now)]
    assert state.behavior_versions == [(5, 7)]


@pytest.mark.asyncio
async def test_interest_top50_merges_current_query_with_es_and_uses_title_tag_summary_weights():
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    state = _StateRepository()
    telemetry = _TelemetryRepository(now)
    service = PortalRecommendationBehaviorService(state_repository=state, telemetry_repository=telemetry)

    entries = await service.build_interest_top50(
        tenant_id=5,
        user_id=7,
        current_query="STEEL",
        searched_at=now,
        now=now,
    )

    assert {query.query for query in telemetry.received_queries} == {"steel", "safety"}
    assert entries[0][0] == "10:100"
    assert entries[0][1] > entries[1][1] > 0
    assert state.interests[:2] == (5, 7)
    assert state.interests[3] == 30 * 60
