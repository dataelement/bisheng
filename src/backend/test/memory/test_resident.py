"""Resident memory (AC-52–AC-57, AC-91, AC-94, AC-96)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlmodel import select

from bisheng.memory.domain.config import MemoryRuntimeConfig
from bisheng.memory.domain.models.memory_item import STATUS_ACTIVE, MemoryItem
from bisheng.memory.domain.models.memory_resident_snapshot import MemoryResidentSnapshot
from bisheng.memory.domain.repositories import _db
from bisheng.memory.domain.services import metrics as m
from bisheng.memory.domain.services.resident import RESIDENT_HEADER, ResidentService
from test.memory.conftest import counter


@pytest.fixture
def resident(kv):
    return ResidentService(kv=kv, metrics=m.MemoryMetrics(kv))


def _limits(monkeypatch, **kw):
    cfg = MemoryRuntimeConfig(**kw)

    async def _load():
        return cfg

    monkeypatch.setattr("bisheng.memory.domain.services.resident.aget_memory_config", _load)


async def test_ac52_item_and_char_limits_first_reached_wins(service, resident, make_ctx, monkeypatch, kv):
    ctx = make_ctx()
    for i in range(5):
        await service.write(ctx, "remember", content=f"用户的第{i}条事实" + "字" * 20, type="fact")
    _limits(monkeypatch, resident_max_items=3, resident_max_chars=10000)
    assert len((await resident.resident(ctx, "chat")).item_ids) == 3
    kv.data.clear()  # a config change applies once the cached block expires
    _limits(monkeypatch, resident_max_items=60, resident_max_chars=60)
    block = await resident.resident(make_ctx(), "chat")
    assert len(block.item_ids) == 2  # 27 chars each: the third would pass 60


async def test_ac53_no_truncation_and_overflow_items_stay_active(service, resident, make_ctx, monkeypatch):
    ctx = make_ctx()
    ids = [
        (await service.write(ctx, "remember", content="很长的内容" * 8 + str(i), type="fact")).item_id for i in range(3)
    ]
    _limits(monkeypatch, resident_max_items=60, resident_max_chars=90)
    block = await resident.resident(ctx, "chat")
    for item in await service.get_items(ctx, block.item_ids):
        assert item.content in block.text  # whole content, never cut
    async with _db.async_session() as s:
        statuses = {i.id: i.status for i in (await s.exec(select(MemoryItem))).all()}
    assert all(statuses[i] == STATUS_ACTIVE for i in ids)


async def test_ac91_superseded_and_deleted_not_injected(service, resident, make_ctx):
    ctx = make_ctx()
    a = await service.write(ctx, "remember", content="用户住在广州", type="fact")
    await service.write(ctx, "correct", content="用户住在深圳", target_id=a.item_id)
    b = await service.write(ctx, "remember", content="用户有一辆车", type="fact")
    await service.write(ctx, "forget", target_id=b.item_id)
    text = (await resident.resident(ctx, "chat")).text
    assert "深圳" in text and "广州" not in text and "车" not in text


async def test_ac54_experience_not_in_chat_resident(service, resident, make_ctx):
    ctx = make_ctx()
    await service.write(ctx, "remember", content="写周报时先列结论再列细节效果好", type="experience")
    await service.write(ctx, "remember", content="用户偏好表格", type="preference")
    text = (await resident.resident(ctx, "chat")).text
    assert "表格" in text and "周报" not in text


async def test_ac55_experience_injection_has_own_limit_and_order(service, resident, make_ctx, monkeypatch):
    ctx = make_ctx()
    ids = []
    for i in range(4):
        ids.append(
            (await service.write(ctx, "remember", content=f"经验{i}：先确认数据口径", type="experience")).item_id
        )
    async with _db.async_session() as s:
        item = await s.get(MemoryItem, ids[0])
        item.last_read_at = datetime.now()
        s.add(item)
        await s.commit()
    _limits(monkeypatch, experience_max_items=2, experience_max_chars=2000)
    block = await resident.experience(ctx)
    assert block.item_ids[0] == ids[0]  # most recently read first
    assert len(block.item_ids) == 2


async def test_ac56_detail_not_injected(service, resident, make_ctx):
    ctx = make_ctx()
    await service.write(ctx, "remember", content="用户的年度目标概括", type="fact", detail="详细目标全文" * 20)
    text = (await resident.resident(ctx, "chat")).text
    assert "用户的年度目标概括" in text and "详细目标全文" not in text


async def test_ac57_header_and_recorded_date(service, resident, make_ctx):
    ctx = make_ctx()
    await service.write(ctx, "remember", content="用户的工号是 A100", type="fact")
    lines = (await resident.resident(ctx, "chat")).text.splitlines()
    assert lines[0] == RESIDENT_HEADER
    assert datetime.now().strftime("%Y-%m-%d") in lines[1]


async def test_empty_resident_is_empty_text(resident, make_ctx, memory_db):
    assert (await resident.resident(make_ctx(), "chat")).text == ""


async def test_ac94_past_event_not_injected_but_still_active(service, resident, make_ctx):
    ctx = make_ctx(timezone="Asia/Shanghai")
    yesterday = (datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(days=1)).strftime("%Y-%m-%d")
    tomorrow = (datetime.now(ZoneInfo("Asia/Shanghai")) + timedelta(days=1)).strftime("%Y-%m-%d")
    past = await service.write(ctx, "remember", content=f"用户 {yesterday} 有评审会", type="fact", event_time=yesterday)
    await service.write(ctx, "remember", content=f"用户 {tomorrow} 有评审会", type="fact", event_time=tomorrow)
    text = (await resident.resident(ctx, "chat")).text
    assert tomorrow in text and yesterday not in text
    assert [i.id for i in await service.get_items(ctx, [past.item_id])] == [past.item_id]


async def test_cache_key_follows_rev(service, resident, make_ctx, kv):
    ctx = make_ctx()
    await service.write(ctx, "remember", content="用户喜欢猫", type="preference")
    first = await resident.resident(ctx, "chat")
    assert any(k.startswith("memory:resident:") for k in kv.data)
    await service.write(ctx, "remember", content="用户喜欢狗", type="preference")
    second = await resident.resident(ctx, "chat")
    assert "狗" in second.text and second.rev == first.rev + 1


async def test_ac96_old_unread_items_are_not_removed(service, resident, make_ctx):
    ctx = make_ctx()
    res = await service.write(ctx, "remember", content="用户十年前的爱好是集邮", type="preference")
    async with _db.async_session() as s:
        item = await s.get(MemoryItem, res.item_id)
        item.recorded_at = datetime(2016, 1, 1)
        s.add(item)
        await s.commit()
    await resident.resident(ctx, "chat")
    assert [i.id for i in await service.list(ctx)] == [res.item_id]


async def test_cache_miss_writes_snapshot_and_counts(service, resident, make_ctx, kv):
    ctx = make_ctx()
    a = await service.write(ctx, "remember", content="用户来自西安", type="fact")
    block = await resident.resident(ctx, "chat")
    await resident.resident(ctx, "chat")  # cache hit
    async with _db.async_session() as s:
        snaps = (await s.exec(select(MemoryResidentSnapshot))).all()
    assert len(snaps) == 1 and snaps[0].item_ids == [a.item_id] and snaps[0].rev == block.rev
    assert await counter(kv, ctx.tenant_id, m.INJECTED) == 2
