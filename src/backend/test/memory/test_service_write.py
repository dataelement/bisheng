"""remember / correct / forget (AC-04, AC-21, AC-23–AC-26, AC-44, AC-91, AC-92, AC-97, AC-98, AC-101)."""

import asyncio

import pytest
from sqlmodel import select

from bisheng.common.errcode.memory import MemoryContentSensitiveError, MemoryItemNotFoundError
from bisheng.memory.domain.models.memory_item import (
    INDEX_OK,
    INDEX_PENDING,
    STATUS_ACTIVE,
    STATUS_DELETED,
    STATUS_SUPERSEDED,
    MemoryItem,
)
from bisheng.memory.domain.models.memory_turn_record import MemoryTurnRecord
from bisheng.memory.domain.repositories import _db
from bisheng.memory.domain.services import metrics as m
from test.memory.conftest import USER_2, counter


async def _all_items():
    async with _db.async_session() as s:
        return list((await s.exec(select(MemoryItem))).all())


async def _turn_rows():
    async with _db.async_session() as s:
        return list((await s.exec(select(MemoryTurnRecord))).all())


async def test_ac24_remember_readable_immediately(service, make_ctx):
    """AC-24: a remembered item is readable at once by the same user (other sessions included)."""
    ctx = make_ctx()
    res = await service.write(ctx, "remember", content="用户 2026-11-17 有一个重要会议", type="fact")
    assert res.ok and res.item_id
    assert [i.content for i in await service.list(make_ctx(chat_id="another-chat"))] == [
        "用户 2026-11-17 有一个重要会议"
    ]
    assert await service.list(make_ctx(user_id=USER_2)) == []


async def test_ac04_ac98_source_mark_and_app_name_snapshot(service, make_ctx):
    """AC-04/AC-98: scene, app, chat and write mode are recorded; the app name is a snapshot."""
    ctx = make_ctx(scene="assistant", app_id="asst-1", app_name="差旅助手", chat_id="c-9")
    res = await service.write(ctx, "remember", content="用户常驻上海办公室", type="fact")
    item = (await _all_items())[0]
    assert (item.source_scene, item.source_app_id, item.source_app_name, item.source_chat_id, item.origin) == (
        "assistant",
        "asst-1",
        "差旅助手",
        "c-9",
        "explicit",
    )
    assert item.id == res.item_id  # the name stays even if the app is renamed or deleted later


async def test_explicit_fact_and_preference_are_resident_first_experience_is_not(service, make_ctx):
    ctx = make_ctx()
    a = await service.write(ctx, "remember", content="用户偏好简洁回答", type="preference")
    b = await service.write(ctx, "remember", content="用户在华东区工作", type="fact")
    c = await service.write(ctx, "remember", content="做竞品分析时先列维度再填数据效果好", type="experience")
    items = {i.id: i for i in await _all_items()}
    assert items[a.item_id].pinned and items[b.item_id].pinned and not items[c.item_id].pinned
    assert items[b.item_id].pin_order < items[a.item_id].pin_order  # newest first


async def test_ac25_ac92_correct_supersedes_and_keeps_old_row(service, make_ctx, index):
    ctx = make_ctx()
    old = await service.write(ctx, "remember", content="用户的汇报对象是张总", type="fact")
    new = await service.write(ctx, "correct", content="用户的汇报对象是李总", target_id=old.item_id)
    items = {i.id: i for i in await _all_items()}
    assert items[new.item_id].status == STATUS_ACTIVE
    assert items[old.item_id].status == STATUS_SUPERSEDED
    assert items[old.item_id].superseded_by == new.item_id
    assert new.related_item_id == old.item_id
    assert old.item_id not in index.docs and new.item_id in index.docs
    assert [i.id for i in await service.list(ctx)] == [new.item_id]  # AC-91


async def test_ac26_forget_makes_item_unreadable(service, make_ctx, index):
    ctx = make_ctx()
    res = await service.write(ctx, "remember", content="用户养了一只猫", type="fact")
    await service.write(ctx, "forget", target_id=res.item_id)
    assert await service.list(ctx) == []
    assert (await _all_items())[0].status == STATUS_DELETED
    assert res.item_id not in index.docs


@pytest.mark.parametrize("action", ["correct", "forget"])
async def test_ac33_target_missing_or_changed_fails_without_new_item(service, make_ctx, action):
    ctx = make_ctx()
    with pytest.raises(MemoryItemNotFoundError):
        await service.write(ctx, action, content="新内容", target_id="no-such-id")
    gone = await service.write(ctx, "remember", content="用户住在杭州", type="fact")
    await service.write(ctx, "forget", target_id=gone.item_id)
    with pytest.raises(MemoryItemNotFoundError):
        await service.write(ctx, action, content="用户住在苏州", target_id=gone.item_id)
    other = await service.write(make_ctx(user_id=USER_2), "remember", content="乙的条目", type="fact")
    with pytest.raises(MemoryItemNotFoundError):
        await service.write(ctx, action, content="篡改", target_id=other.item_id)
    assert len(await _all_items()) == 2


async def test_long_body_goes_to_detail_object(service, make_ctx, details):
    ctx = make_ctx()
    body = "完整的复盘：" + "第一步收集需求。" * 80
    res = await service.write(
        ctx, "remember", content="项目复盘的结论：需求阶段要先对齐验收口径", type="experience", detail=body
    )
    item = (await _all_items())[0]
    assert item.detail_object_key == f"memory/{ctx.tenant_id}/{ctx.user_id}/{res.item_id}.md"
    assert details.objects[item.detail_object_key] == body
    assert item.detail_sha256 and len(item.content) <= 200


async def test_ac44_concurrent_writes_both_kept(service, make_ctx):
    ctx = make_ctx()
    await asyncio.gather(
        service.write(ctx, "remember", content="用户喜欢喝美式", type="preference"),
        service.write(make_ctx(chat_id="c-2"), "remember", content="用户喜欢早上开会", type="preference"),
    )
    assert len(await service.list(ctx)) == 2


async def test_ac21_ac101_success_produces_turn_record_audit_metric(service, make_ctx, audit_rows, kv):
    ctx = make_ctx(turn_id="t-1")
    a = await service.write(ctx, "remember", content="用户的生日是 1990-05-01", type="fact")
    await service.write(ctx, "correct", content="用户的生日是 1990-06-01", target_id=a.item_id)
    rows = await _turn_rows()
    assert [(r.kind, r.op) for r in rows] == [("write", "remember"), ("write", "correct")]
    assert rows[1].related_item_id == a.item_id
    assert [r["action"] for r in audit_rows.rows] == ["memory.item.remember", "memory.item.correct"]
    assert await counter(kv, ctx.tenant_id, m.ADDED_EXPLICIT) == 2
    assert await counter(kv, ctx.tenant_id, m.SUPERSEDED) == 1


async def test_ac23_failure_produces_no_record_audit_or_metric(service, make_ctx, audit_rows, kv):
    ctx = make_ctx(turn_id="t-1")
    with pytest.raises(MemoryContentSensitiveError):
        await service.write(ctx, "remember", content="我的密码是 abc12345", type="fact")
    with pytest.raises(MemoryItemNotFoundError):
        await service.write(ctx, "forget", target_id="missing")
    assert await _turn_rows() == [] and audit_rows.rows == [] and await _all_items() == []
    assert await counter(kv, ctx.tenant_id, m.ADDED_EXPLICIT) == 0


@pytest.mark.parametrize("failure", ["write_fail", "write_timeout"])
async def test_index_failure_keeps_write_and_marks_pending(service, make_ctx, index, failure):
    setattr(index, failure, True)
    res = await service.write(make_ctx(), "remember", content="用户负责数据平台", type="fact")
    item = (await _all_items())[0]
    assert res.ok and item.index_state == INDEX_PENDING


async def test_index_success_records_model(service, make_ctx):
    await service.write(make_ctx(), "remember", content="用户负责数据平台", type="fact")
    item = (await _all_items())[0]
    assert item.index_state == INDEX_OK and item.index_model_id == "emb-1"


async def test_ac97_items_survive_source_chat_deletion(service, make_ctx, memory_db):
    from bisheng.database.models.session import MessageSession

    ctx = make_ctx(chat_id="c-del")
    with memory_db.session() as s:
        s.add(MessageSession(chat_id="c-del", flow_id="", flow_type=15, user_id=ctx.user_id, name="x", is_delete=True))
        s.commit()
    await service.write(ctx, "remember", content="用户在做 3.1 版本规划", type="fact")
    assert len(await service.list(make_ctx())) == 1


async def test_rev_increments_on_each_change(service, make_ctx):
    from bisheng.memory.domain.repositories.setting_repository import SettingRepository

    ctx = make_ctx()
    a = await service.write(ctx, "remember", content="用户用 Mac 办公", type="fact")
    await service.write(ctx, "forget", target_id=a.item_id)
    assert (await SettingRepository.get(ctx)).rev == 2
