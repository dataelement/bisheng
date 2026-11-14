"""Memory search (AC-58, AC-59, AC-61, AC-62)."""

import pytest
from sqlmodel import select

from bisheng.common.errcode.memory import MemorySearchUnavailableError
from bisheng.memory.domain.models.memory_item import MemoryItem
from bisheng.memory.domain.ports import IndexHit, build_scope_filter
from bisheng.memory.domain.repositories import _db
from bisheng.memory.domain.services import metrics as m
from bisheng.memory.domain.services.search import SearchService, render_hits, rrf_fuse
from test.memory.conftest import TENANT_B, USER_2, counter


@pytest.fixture
def search(index, details, kv):
    return SearchService(index=index, details=details, metrics=m.MemoryMetrics(kv))


async def test_ac58_only_own_active_items(service, search, make_ctx):
    me = make_ctx()
    a = await service.write(me, "remember", content="用户喜欢川菜", type="preference")
    b = await service.write(me, "remember", content="用户喜欢粤菜", type="preference")
    await service.write(me, "forget", target_id=b.item_id)
    await service.write(make_ctx(user_id=USER_2), "remember", content="乙喜欢川菜", type="preference")
    await service.write(make_ctx(tenant_id=TENANT_B), "remember", content="B 租户喜欢川菜", type="preference")
    hits = await search.search(me, "喜欢川菜")
    assert [h.item_id for h in hits] == [a.item_id]


async def test_ac59_fields_and_detail_on_request(service, search, make_ctx):
    ctx = make_ctx()
    res = await service.write(
        ctx,
        "remember",
        content="季度复盘的结论：先对齐口径",
        type="experience",
        event_time="2026-12-01",
        detail="复盘全文",
    )
    hit = (await search.search(ctx, "季度复盘"))[0]
    assert (hit.content, hit.type, hit.event_time.strftime("%Y-%m-%d")) == (
        "季度复盘的结论：先对齐口径",
        "experience",
        "2026-12-01",
    )
    assert hit.recorded_at and hit.detail is None and hit.has_detail
    # The model is told which item has a detail and how to fetch it.
    assert f"id={res.item_id}" in render_hits([hit]) and "有详情" in render_hits([hit])
    hit = (await search.search(ctx, "季度复盘", detail_ids=[res.item_id]))[0]
    assert hit.detail == "复盘全文"
    rendered = render_hits([hit])
    assert "复盘全文" in rendered and "以上为详情全文" in rendered and "有详情，" not in rendered


async def test_pending_items_appended(service, search, make_ctx, index):
    ctx = make_ctx()
    index.write_fail = True
    pending = await service.write(ctx, "remember", content="用户下个季度去成都", type="fact")
    index.write_fail = False
    indexed = await service.write(ctx, "remember", content="用户在学吉他", type="fact")
    hits = await search.search(ctx, "吉他")
    assert [h.item_id for h in hits] == [indexed.item_id, pending.item_id]


@pytest.mark.parametrize("down", ["keyword_down", "vector_down"])
async def test_one_path_down_degrades(service, search, make_ctx, index, kv, down):
    ctx = make_ctx()
    a = await service.write(ctx, "remember", content="用户的专业是建筑学", type="fact")
    setattr(index, down, True)
    assert [h.item_id for h in await search.search(ctx, "建筑学")] == [a.item_id]
    assert await counter(kv, ctx.tenant_id, m.SEARCH_DEGRADED) == 1


async def test_ac61_both_paths_down_raise_and_count(service, search, make_ctx, index, kv):
    ctx = make_ctx()
    index.keyword_down = index.vector_down = True
    with pytest.raises(MemorySearchUnavailableError):
        await search.search(ctx, "任何")
    assert await counter(kv, ctx.tenant_id, m.SEARCH_FAILED) == 1


async def test_no_embedding_is_keyword_only_without_failure(service, search, make_ctx, index, kv):
    ctx = make_ctx()
    a = await service.write(ctx, "remember", content="用户的家乡是大理", type="fact")
    index.vector_unconfigured = True
    assert [h.item_id for h in await search.search(ctx, "家乡大理")] == [a.item_id]
    assert await counter(kv, ctx.tenant_id, m.SEARCH_DEGRADED) == 0
    assert await counter(kv, ctx.tenant_id, m.SEARCH_FAILED) == 0


async def test_stale_index_entry_filtered_by_table_check(service, search, make_ctx, index):
    ctx = make_ctx()
    a = await service.write(ctx, "remember", content="用户喜欢爬山", type="preference")
    async with _db.async_session() as s:
        item = await s.get(MemoryItem, a.item_id)
        item.status = "deleted"
        s.add(item)
        await s.commit()
    assert a.item_id in index.docs
    assert await search.search(ctx, "爬山") == []


async def test_ac62_detail_read_failure_falls_back(service, search, make_ctx, details, kv):
    ctx = make_ctx()
    res = await service.write(ctx, "remember", content="迁移方案要点", type="experience", detail="迁移方案全文")
    details.read_fail = True
    hit = (await search.search(ctx, "迁移方案", detail_ids=[res.item_id]))[0]
    assert hit.detail is None and hit.content == "迁移方案要点"
    assert await counter(kv, ctx.tenant_id, m.DETAIL_READ_FAILED) == 1


async def test_scope_filter_used_by_both_paths(service, search, make_ctx, index):
    ctx = make_ctx()
    await service.write(ctx, "remember", content="用户喜欢冰美式", type="preference")
    await search.search(ctx, "冰美式")
    assert {p for p, _ in index.filters} == {"keyword", "vector"}
    assert all(f == build_scope_filter(ctx) for _, f in index.filters)


async def test_ac53_ac94_non_resident_and_past_event_items_are_searchable(service, search, make_ctx):
    ctx = make_ctx()
    a = await service.write(
        ctx, "remember", content="用户 2020-01-01 参加过马拉松", type="fact", event_time="2020-01-01"
    )
    async with _db.async_session() as s:
        item = await s.get(MemoryItem, a.item_id)
        item.pinned = False
        s.add(item)
        await s.commit()
    assert [h.item_id for h in await search.search(ctx, "马拉松")] == [a.item_id]


async def test_returned_items_marked_read_and_counted(service, search, make_ctx, kv):
    ctx = make_ctx()
    a = await service.write(ctx, "remember", content="用户的猫叫团子", type="fact")
    await search.search(ctx, "团子")
    await search.metrics.flush()
    async with _db.async_session() as s:
        assert (await s.get(MemoryItem, a.item_id)).last_read_at is not None
    assert await counter(kv, ctx.tenant_id, m.RETRIEVED) == 0  # drained by flush
    async with _db.async_session() as s:
        from bisheng.memory.domain.models.memory_metric_daily import MemoryMetricDaily

        rows = (await s.exec(select(MemoryMetricDaily).where(MemoryMetricDaily.metric == m.RETRIEVED))).all()
    assert sum(r.value for r in rows) == 1


def test_rrf_order():
    kw = [IndexHit("a", 9), IndexHit("b", 5), IndexHit("c", 1)]
    vec = [IndexHit("c", 0.9), IndexHit("a", 0.8)]
    assert rrf_fuse([kw, vec]) == ["a", "c", "b"]


async def test_limit_respected(service, search, make_ctx):
    ctx = make_ctx()
    for i in range(5):
        await service.write(ctx, "remember", content=f"用户的爱好之{i}是摄影", type="preference")
    assert len(await search.search(ctx, "摄影", limit=3)) == 3
