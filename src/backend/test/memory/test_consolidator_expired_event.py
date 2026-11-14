"""P1: items whose event date has passed are rewritten in past tense (AC-95)."""

import json
from datetime import datetime, timedelta

from sqlmodel import select

from bisheng.memory.domain.models.memory_item import STATUS_ACTIVE, STATUS_SUPERSEDED, MemoryItem
from bisheng.memory.domain.repositories import _db
from bisheng.memory.domain.services.consolidation_content import ExpiredEventRewrite
from test.memory.conftest import TENANT_A, USER_1


async def _items():
    async with _db.async_session() as s:
        return {i.id: i for i in (await s.exec(select(MemoryItem))).all()}


async def test_ac95_past_event_superseded_by_past_tense_with_date(service, llm, make_ctx):
    past = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    future = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
    old = await service.write(
        make_ctx(), "remember", content=f"用户 {past} 要参加信创评审", type="fact", event_time=past
    )
    keep = await service.write(make_ctx(), "remember", content=f"用户 {future} 要出差", type="fact", event_time=future)
    llm.answers = [
        json.dumps({"rewrites": [{"id": old.item_id, "content": f"用户在 {past} 参加了信创评审"}]}, ensure_ascii=False)
    ]
    await ExpiredEventRewrite(service=service, llm=llm)(TENANT_A, USER_1)
    items = await _items()
    assert items[old.item_id].status == STATUS_SUPERSEDED
    new = items[items[old.item_id].superseded_by]
    assert new.status == STATUS_ACTIVE and past in new.content and new.rewritten
    assert new.event_time.strftime("%Y-%m-%d") == past
    assert items[keep.item_id].status == STATUS_ACTIVE
    assert old.item_id in llm.prompts[0] and keep.item_id not in llm.prompts[0]


async def test_same_item_not_rewritten_twice(service, llm, make_ctx):
    past = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    old = await service.write(make_ctx(), "remember", content=f"用户 {past} 有述职", type="fact", event_time=past)
    llm.answers = [
        json.dumps({"rewrites": [{"id": old.item_id, "content": f"用户在 {past} 做过述职"}]}, ensure_ascii=False)
    ]
    step = ExpiredEventRewrite(service=service, llm=llm)
    await step(TENANT_A, USER_1)
    await step(TENANT_A, USER_1)
    assert len(llm.prompts) == 1


async def test_invalid_rewrite_is_dropped(service, llm, make_ctx):
    past = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    old = await service.write(make_ctx(), "remember", content=f"用户 {past} 有评审", type="fact", event_time=past)
    llm.answers = [json.dumps({"rewrites": [{"id": old.item_id, "content": "用户昨天参加了评审"}]}, ensure_ascii=False)]
    await ExpiredEventRewrite(service=service, llm=llm)(TENANT_A, USER_1)
    assert (await _items())[old.item_id].status == STATUS_ACTIVE


async def test_rewrite_keeps_source_mark_and_rejected_rewrite_is_not_retried(service, llm, make_ctx):
    """AC-04 / AC-98: the rewritten item keeps the original source; a rejected rewrite costs one call only."""
    past = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    src = make_ctx(scene="assistant", app_id="asst-1", app_name="差旅助手", chat_id="c-src")
    kept = await service.write(src, "remember", content=f"用户 {past} 去了上海出差", type="fact", event_time=past)
    bad = await service.write(make_ctx(), "remember", content=f"用户 {past} 有周会", type="fact", event_time=past)
    llm.answers = [
        json.dumps(
            {
                "rewrites": [
                    {"id": kept.item_id, "content": f"用户在 {past} 去过上海出差"},
                    {"id": bad.item_id, "content": "用户昨天开过周会"},
                ]
            },
            ensure_ascii=False,
        )
    ]
    step = ExpiredEventRewrite(service=service, llm=llm)
    await step(TENANT_A, USER_1)
    items = await _items()
    new = items[items[kept.item_id].superseded_by]
    assert (new.source_scene, new.source_app_id, new.source_app_name, new.source_chat_id, new.origin) == (
        "assistant",
        "asst-1",
        "差旅助手",
        "c-src",
        "explicit",
    )
    assert items[bad.item_id].status == STATUS_ACTIVE
    await step(TENANT_A, USER_1)
    assert len(llm.prompts) == 1


async def test_rewrite_carries_the_detail_over(service, llm, make_ctx):
    """A tense rewrite is the same memory: its detail moves to the rewritten item."""
    past = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    old = await service.write(
        make_ctx(), "remember", content=f"用户 {past} 去杭州出差", type="fact", event_time=past, detail="- 拜访客户 A"
    )
    llm.answers = [
        json.dumps({"rewrites": [{"id": old.item_id, "content": f"用户在 {past} 去过杭州出差"}]}, ensure_ascii=False)
    ]
    await ExpiredEventRewrite(service=service, llm=llm)(TENANT_A, USER_1)
    new_id = (await _items())[old.item_id].superseded_by
    assert await service.get_detail(make_ctx(), new_id) == "- 拜访客户 A"
