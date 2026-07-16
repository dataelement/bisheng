from datetime import datetime, timedelta, timezone

import pytest

from bisheng.core.config.settings import PortalHotSearchConf
from bisheng.knowledge.domain.repositories.interfaces.portal_hot_search_telemetry_repository import (
    CandidateAggregateResult,
    SearchRecordsResult,
)
from bisheng.knowledge.domain.schemas.portal_hot_search_schema import (
    CandidateQueryStat,
    PortalSearchRecord,
)
from bisheng.knowledge.domain.services.portal_hot_search_filter_service import (
    PortalHotSearchFilterService,
)
from bisheng.knowledge.domain.services.portal_hot_search_intent_service import (
    PortalHotSearchIntentService,
)
from bisheng.knowledge.domain.services.portal_hot_search_pipeline_service import (
    PortalHotSearchPipelineService,
)
from bisheng.knowledge.domain.services.portal_hot_search_rewrite_service import (
    PortalHotSearchRewriteService,
    is_complete_question,
)
from bisheng.knowledge.domain.services.portal_hot_search_scoring_service import (
    PortalHotSearchScoringService,
)

_NOW = datetime(2026, 7, 16, 2, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# T012 rewrite
# --------------------------------------------------------------------------


def test_rewrite_passthrough_for_complete_question():
    q = "环保设备发生故障后应该如何处理？"
    assert is_complete_question(q) is True
    svc = PortalHotSearchRewriteService(llm_invoke=lambda prompt: "should not be called")
    display, source = svc.rewrite(q)
    assert display == q
    assert source == "passthrough"


def test_rewrite_uses_llm_when_valid():
    svc = PortalHotSearchRewriteService(llm_invoke=lambda prompt: "设备检修安全要求有哪些具体规定？")
    display, source = svc.rewrite("设备检修安全要求")
    assert source == "llm"
    assert display.endswith("？")


def test_rewrite_falls_back_when_llm_invalid():
    # returns too-short (< 12 han) -> invalid -> fallback
    svc = PortalHotSearchRewriteService(llm_invoke=lambda prompt: "太短了？")
    display, source = svc.rewrite("设备检修安全要求")
    assert source == "fallback"
    assert display == "设备检修安全要求？"


def test_rewrite_falls_back_when_llm_raises():
    def _boom(prompt):
        raise RuntimeError("llm down")

    svc = PortalHotSearchRewriteService(llm_invoke=_boom)
    _display, source = svc.rewrite("设备检修安全要求")
    assert source == "fallback"


# --------------------------------------------------------------------------
# T014 intent grouping
# --------------------------------------------------------------------------


def test_intent_grouping_parses_llm_json():
    response = (
        '{"groups":[{"intent_id":"g1","canonical_query":"设备检修安全要求",'
        '"members":["设备检修 安全","检修安全要求"]}]}'
    )
    svc = PortalHotSearchIntentService(llm_invoke=lambda prompt: response)
    result = svc.group(["设备检修 安全", "检修安全要求"])
    assert result.degraded is False
    assert len(result.groups) == 1
    assert result.groups[0].canonical_query == "设备检修安全要求"
    assert set(result.groups[0].member_queries) == {"设备检修 安全", "检修安全要求"}


def test_intent_grouping_degrades_on_invalid_json():
    svc = PortalHotSearchIntentService(llm_invoke=lambda prompt: "not json at all")
    result = svc.group(["设备检修安全", "能源管理制度"])
    assert result.degraded is True
    assert {g.canonical_query for g in result.groups} == {"设备检修安全", "能源管理制度"}


def test_intent_grouping_degrades_without_llm():
    svc = PortalHotSearchIntentService(llm_invoke=None)
    result = svc.group(["设备检修安全"])
    assert result.degraded is True
    assert result.groups[0].member_queries == ["设备检修安全"]


# --------------------------------------------------------------------------
# T024 pipeline orchestration
# --------------------------------------------------------------------------


class _FakeTelemetry:
    def __init__(self, records, *, agg_truncated=False, rec_truncated=False, raise_on_agg=False):
        self._records = records
        self._agg_truncated = agg_truncated
        self._rec_truncated = rec_truncated
        self._raise_on_agg = raise_on_agg

    async def aggregate_candidate_queries(self, tenant_id, since, before, **kwargs):
        if self._raise_on_agg:
            raise RuntimeError("es down")
        queries = list(dict.fromkeys(r.normalized_query for r in self._records))
        stats = [CandidateQueryStat(normalized_query=q, doc_count=10, approx_users=5) for q in queries]
        return CandidateAggregateResult(stats=stats, es_pages=1, truncated=self._agg_truncated)

    async def list_candidate_search_records(self, tenant_id, normalized_queries, since, before, **kwargs):
        return SearchRecordsResult(records=list(self._records), es_pages=1, truncated=self._rec_truncated)


class _FakeHotSearchRepo:
    def __init__(self):
        self.batch_runs = []
        self.snapshot = None
        self.candidates = None
        self.purged = 0

    async def insert_batch_run(self, stats, *, window_start, window_end, computed_at):
        self.batch_runs.append(("insert", stats.status))

    async def update_batch_run(self, stats, *, computed_at):
        self.batch_runs.append(("update", stats.status))
        self.last_stats = stats

    async def replace_snapshot(self, items, *, batch_id, computed_at):
        self.snapshot = [i for i in items if i.final_rank is not None]

    async def insert_candidates(self, items, *, batch_id, computed_at, llm_samples=None):
        self.candidates = list(items)
        self.llm_samples = llm_samples or {}

    async def list_home_snapshot(self, *, top_k):
        return []

    async def purge_old_diagnostics(self, *, keep_batches):
        self.purged += 1


class _FakeRedis:
    def __init__(self, *, lock_ok=True):
        self.lock_ok = lock_ok
        self.replaced = None
        self.lock_acquired = False
        self.lock_released = False

    async def acquire_lock(self, tenant_id):
        self.lock_acquired = True
        return self.lock_ok

    async def release_lock(self, tenant_id):
        self.lock_released = True

    async def replace(self, tenant_id, items):
        self.replaced = list(items)

    async def get(self, tenant_id):
        return None


def _qualified_records():
    records = []
    day0 = _NOW
    for uid in range(1, 6):
        records.append(
            PortalSearchRecord(
                user_id=uid,
                query="设备检修安全要求",
                normalized_query="设备检修安全要求",
                searched_at=day0 - timedelta(days=1),
            )
        )
    for uid in range(1, 4):
        records.append(
            PortalSearchRecord(
                user_id=uid,
                query="设备检修安全要求",
                normalized_query="设备检修安全要求",
                searched_at=day0 - timedelta(days=10),
            )
        )
    return records


def _pipeline(telemetry, repo, redis, *, llm_group=None, llm_rewrite=None):
    config = PortalHotSearchConf()
    return PortalHotSearchPipelineService(
        tenant_id=1,
        config=config,
        telemetry_repository=telemetry,
        hot_search_repository=repo,
        redis_repository=redis,
        filter_service=PortalHotSearchFilterService(),
        intent_service=PortalHotSearchIntentService(llm_invoke=llm_group),
        scoring_service=PortalHotSearchScoringService(),
        rewrite_service=PortalHotSearchRewriteService(llm_invoke=llm_rewrite),
    )


async def test_pipeline_success_publishes_snapshot_and_releases_lock():
    telemetry = _FakeTelemetry(_qualified_records())
    repo = _FakeHotSearchRepo()
    redis = _FakeRedis()
    pipeline = _pipeline(telemetry, repo, redis, llm_rewrite=lambda prompt: "设备检修安全要求有哪些具体规定？")

    stats = await pipeline.run(now=_NOW)

    assert stats.status == "success"
    assert stats.qualified_count == 1
    assert repo.snapshot is not None and len(repo.snapshot) == 1
    assert repo.snapshot[0].final_rank == 1
    assert redis.replaced is not None and len(redis.replaced) == 1
    assert redis.lock_acquired and redis.lock_released
    assert repo.purged == 1
    assert ("update", "success") in repo.batch_runs
    # LLM diagnostic sample captured for the ranked intent
    assert repo.llm_samples


async def test_pipeline_marks_degraded_when_truncated():
    telemetry = _FakeTelemetry(_qualified_records(), agg_truncated=True)
    repo = _FakeHotSearchRepo()
    redis = _FakeRedis()
    pipeline = _pipeline(telemetry, repo, redis, llm_rewrite=lambda prompt: "设备检修安全要求有哪些具体规定？")

    stats = await pipeline.run(now=_NOW)
    assert stats.truncated is True
    assert stats.status == "degraded"


async def test_pipeline_skips_when_lock_unavailable():
    telemetry = _FakeTelemetry(_qualified_records())
    repo = _FakeHotSearchRepo()
    redis = _FakeRedis(lock_ok=False)
    pipeline = _pipeline(telemetry, repo, redis)

    stats = await pipeline.run(now=_NOW)
    assert stats.status == "skipped"
    assert repo.snapshot is None
    assert repo.batch_runs == []


async def test_pipeline_records_failed_run_and_keeps_previous_snapshot():
    telemetry = _FakeTelemetry(_qualified_records(), raise_on_agg=True)
    repo = _FakeHotSearchRepo()
    redis = _FakeRedis()
    pipeline = _pipeline(telemetry, repo, redis)

    with pytest.raises(RuntimeError):
        await pipeline.run(now=_NOW)

    assert repo.snapshot is None  # previous snapshot untouched
    assert ("update", "failed") in repo.batch_runs
    assert redis.lock_released is True
    assert redis.replaced is None
