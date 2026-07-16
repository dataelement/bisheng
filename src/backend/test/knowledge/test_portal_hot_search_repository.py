from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from bisheng.core.context.tenant import set_current_tenant_id
from bisheng.core.database.tenant_filter import register_tenant_filter_events
from bisheng.knowledge.domain.models.portal_hot_search_snapshot import (
    PortalHotSearchBatchRun,
    PortalHotSearchCandidate,
)
from bisheng.knowledge.domain.repositories.implementations.portal_hot_search_repository_impl import (
    PortalHotSearchRepositoryImpl,
)
from bisheng.knowledge.domain.schemas.portal_hot_search_schema import (
    HotSearchBatchStats,
    HotSearchRankItem,
)

_NOW = datetime(2026, 7, 16, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _tenant():
    register_tenant_filter_events()
    set_current_tenant_id(1)
    yield
    set_current_tenant_id(None)


def _item(rank, canonical, *, qualified=True):
    return HotSearchRankItem(
        intent_key=f"k-{canonical}",
        canonical_query=canonical,
        display_query=f"{canonical}？",
        heat_score=20 - rank,
        unique_users=6,
        search_count_7d=5,
        search_count_8_30d=3,
        qualified=qualified,
        final_rank=rank if qualified else None,
        rewrite_source="fallback",
        member_queries=[canonical],
    )


async def test_batch_run_insert_then_update(async_db_session):
    repo = PortalHotSearchRepositoryImpl(async_db_session)
    stats = HotSearchBatchStats(batch_id="20260716-01", status="running")
    await repo.insert_batch_run(stats, window_start=_NOW, window_end=_NOW, computed_at=_NOW)

    stats.status = "success"
    stats.qualified_count = 3
    stats.truncated = False
    await repo.update_batch_run(stats, computed_at=_NOW)

    result = await async_db_session.exec(select(PortalHotSearchBatchRun))
    rows = result.all()
    assert len(rows) == 1
    assert rows[0].status == "success"
    assert rows[0].qualified_count == 3
    assert rows[0].tenant_id == 1


async def test_replace_snapshot_is_whole_batch(async_db_session):
    repo = PortalHotSearchRepositoryImpl(async_db_session)
    await repo.replace_snapshot(
        [_item(1, "设备检修安全要求"), _item(2, "能源管理制度")],
        batch_id="20260716-01",
        computed_at=_NOW,
    )
    first = await repo.list_home_snapshot(top_k=5)
    assert [i.rank for i in first] == [1, 2]

    # second batch fully replaces the first
    await repo.replace_snapshot(
        [_item(1, "环保设施运行要求")],
        batch_id="20260716-02",
        computed_at=_NOW,
    )
    second = await repo.list_home_snapshot(top_k=5)
    assert len(second) == 1
    assert second[0].query == "环保设施运行要求？"


async def test_insert_candidates_persists_non_ranked(async_db_session):
    repo = PortalHotSearchRepositoryImpl(async_db_session)
    items = [_item(1, "设备检修安全要求"), _item(2, "低分候选", qualified=False)]
    await repo.insert_candidates(
        items,
        batch_id="20260716-01",
        computed_at=_NOW,
        llm_samples={"k-设备检修安全要求": "sample"},
    )
    result = await async_db_session.exec(select(PortalHotSearchCandidate))
    rows = result.all()
    assert len(rows) == 2
    non_ranked = next(r for r in rows if r.qualified == 0)
    assert non_ranked.final_rank is None


async def test_purge_keeps_recent_batches(async_db_session):
    repo = PortalHotSearchRepositoryImpl(async_db_session)
    for idx, batch in enumerate(["20260714-01", "20260715-01", "20260716-01"]):
        stats = HotSearchBatchStats(batch_id=batch, status="success")
        computed = _NOW - timedelta(days=(2 - idx))
        await repo.insert_batch_run(stats, window_start=computed, window_end=computed, computed_at=computed)
        await repo.insert_candidates([_item(1, f"q{idx}")], batch_id=batch, computed_at=computed)

    await repo.purge_old_diagnostics(keep_batches=1)

    runs = (await async_db_session.exec(select(PortalHotSearchBatchRun))).all()
    cands = (await async_db_session.exec(select(PortalHotSearchCandidate))).all()
    assert {r.batch_id for r in runs} == {"20260716-01"}
    assert {c.batch_id for c in cands} == {"20260716-01"}
