"""edit / add / delete / clear / undo (AC-22, AC-89, AC-93, AC-101, AC-102)."""

import pytest
from sqlmodel import select

from bisheng.common.errcode.memory import (
    MemoryContentTooLongError,
    MemoryUndoAlreadyDoneError,
    MemoryUndoChangedError,
    MemoryUndoClearedError,
)
from bisheng.memory.domain.models.memory_item import (
    ORIGIN_MANUAL,
    STATUS_ACTIVE,
    STATUS_DELETED,
    STATUS_SUPERSEDED,
    MemoryItem,
)
from bisheng.memory.domain.models.memory_resident_snapshot import MemoryResidentSnapshot
from bisheng.memory.domain.models.memory_session_cursor import MemorySessionCursor
from bisheng.memory.domain.models.memory_turn_record import MemoryTurnRecord
from bisheng.memory.domain.repositories import _db
from bisheng.memory.domain.services import metrics as m
from bisheng.memory.domain.services.turn_record import TurnRecordService
from test.memory.conftest import TENANT_B, USER_2, counter


async def _items():
    async with _db.async_session() as s:
        return {i.id: i for i in (await s.exec(select(MemoryItem))).all()}


async def test_ac89_edit_supersedes_and_keeps_source(service, make_ctx):
    ctx = make_ctx(scene="assistant", app_id="a1", app_name="助手")
    old = await service.write(ctx, "remember", content="用户喜欢喝茶", type="preference")
    mgmt = make_ctx(scene="manual")
    new = await service.edit(mgmt, old.item_id, "用户喜欢喝咖啡")
    items = await _items()
    assert items[old.item_id].status == STATUS_SUPERSEDED
    assert items[new.item_id].status == STATUS_ACTIVE and items[new.item_id].content == "用户喜欢喝咖啡"
    assert items[new.item_id].origin == ORIGIN_MANUAL and items[new.item_id].source_app_name == "助手"


async def test_ac89_manual_add_source_is_manual_and_validated(service, make_ctx):
    res = await service.add_manual(make_ctx(scene="manual"), "用户的常用城市是成都", "fact")
    item = (await _items())[res.item_id]
    assert (item.origin, item.source_scene, item.source_app_id) == ("manual", "manual", None)
    with pytest.raises(MemoryContentTooLongError):
        await service.add_manual(make_ctx(), "长" * 201, "fact")


async def test_delete_single_item(service, make_ctx):
    ctx = make_ctx()
    res = await service.write(ctx, "remember", content="用户的车牌尾号是 7", type="fact")
    await service.delete(ctx, res.item_id)
    assert await service.list(ctx) == []
    assert (await _items())[res.item_id].status == STATUS_DELETED


async def _undo_last(service, ctx):
    rows = (await TurnRecordService.get_for_owner(ctx, turn_id=ctx.turn_id))["writes"]
    return await service.undo(ctx, rows[-1]["record_id"])


async def test_ac22_undo_remember_deletes(service, make_ctx, index):
    ctx = make_ctx(turn_id="t1")
    res = await service.write(ctx, "remember", content="用户 2026-12-01 出差北京", type="fact")
    await _undo_last(service, ctx)
    assert await service.list(ctx) == []
    assert res.item_id not in index.docs


async def test_ac22_undo_correct_restores_old(service, make_ctx, index):
    ctx = make_ctx(turn_id="t1")
    old = await service.write(ctx, "remember", content="用户的组长是王工", type="fact")
    new = await service.write(ctx, "correct", content="用户的组长是赵工", target_id=old.item_id)
    await _undo_last(service, ctx)
    items = await _items()
    assert items[new.item_id].status == STATUS_DELETED
    assert items[old.item_id].status == STATUS_ACTIVE and items[old.item_id].superseded_by is None
    assert old.item_id in index.docs  # re-indexed


async def test_ac22_undo_forget_restores(service, make_ctx, index):
    ctx = make_ctx(turn_id="t1")
    res = await service.write(ctx, "remember", content="用户对花生过敏", type="fact")
    await service.write(ctx, "forget", target_id=res.item_id)
    await _undo_last(service, ctx)
    assert [i.id for i in await service.list(ctx)] == [res.item_id]
    assert res.item_id in index.docs


async def test_undo_fails_after_clear(service, make_ctx):
    ctx = make_ctx(turn_id="t1")
    await service.write(ctx, "remember", content="用户住在南京", type="fact")
    record_id = (await TurnRecordService.get_for_owner(ctx, turn_id="t1"))["writes"][0]["record_id"]
    await service.clear(ctx)
    with pytest.raises(MemoryUndoClearedError):
        await service.undo(ctx, record_id)


async def test_undo_correct_fails_when_new_item_changed_again(service, make_ctx):
    ctx = make_ctx(turn_id="t1")
    old = await service.write(ctx, "remember", content="用户用 Windows", type="fact")
    new = await service.write(ctx, "correct", content="用户用 Mac", target_id=old.item_id)
    rec = (await TurnRecordService.get_for_owner(ctx, turn_id="t1"))["writes"][-1]["record_id"]
    await service.write(make_ctx(turn_id="t2"), "correct", content="用户用 Linux", target_id=new.item_id)
    with pytest.raises(MemoryUndoChangedError):
        await service.undo(ctx, rec)
    items = await _items()
    assert items[old.item_id].status == STATUS_SUPERSEDED  # no partial restore


async def test_undo_twice_fails(service, make_ctx):
    ctx = make_ctx(turn_id="t1")
    await service.write(ctx, "remember", content="用户的母语是粤语", type="fact")
    rec = (await TurnRecordService.get_for_owner(ctx, turn_id="t1"))["writes"][0]["record_id"]
    await service.undo(ctx, rec)
    with pytest.raises(MemoryUndoAlreadyDoneError):
        await service.undo(ctx, rec)


async def test_undo_other_users_record_is_refused(service, make_ctx):
    ctx = make_ctx(turn_id="t1")
    await service.write(ctx, "remember", content="用户在学日语", type="fact")
    rec = (await TurnRecordService.get_for_owner(ctx, turn_id="t1"))["writes"][0]["record_id"]
    with pytest.raises(MemoryUndoClearedError):
        await service.undo(make_ctx(user_id=USER_2), rec)
    assert len(await service.list(ctx)) == 1


async def test_ac93_clear_removes_everything_of_this_user_only(service, make_ctx, index, details, memory_db):
    me = make_ctx(turn_id="t1")
    a = await service.write(me, "remember", content="用户的部门是财务部", type="fact", detail="完整说明" * 10)
    await service.write(me, "correct", content="用户的部门是审计部", target_id=a.item_id)
    await TurnRecordService.save_snapshot(me, 1, "2026-11-13", "chat", [a.item_id])
    other_user = make_ctx(user_id=USER_2)
    other_tenant = make_ctx(tenant_id=TENANT_B)
    await service.write(other_user, "remember", content="乙的条目", type="fact")
    await service.write(other_tenant, "remember", content="B 租户的条目", type="fact")
    with memory_db.session() as s:
        s.add(
            MemorySessionCursor(
                chat_id="c-me",
                tenant_id=me.tenant_id,
                user_id=me.user_id,
                last_message_id=50,
                watermark_message_id=10,
                state="pending",
            )
        )
        s.commit()
    await service.clear(me)
    items = await _items()
    assert sorted(i.user_id * 10 + i.tenant_id for i in items.values()) == sorted(
        [other_user.user_id * 10 + other_user.tenant_id, other_tenant.user_id * 10 + other_tenant.tenant_id]
    )
    assert not [k for k in details.objects if k.startswith(f"memory/{me.tenant_id}/{me.user_id}/")]
    assert not [d for d in index.docs.values() if (d["tenant_id"], d["user_id"]) == (me.tenant_id, me.user_id)]
    async with _db.async_session() as s:
        assert not [
            r
            for r in (await s.exec(select(MemoryTurnRecord))).all()
            if r.user_id == me.user_id and r.tenant_id == me.tenant_id
        ]
        assert (await s.exec(select(MemoryResidentSnapshot))).all() == []
        cursor = await s.get(MemorySessionCursor, "c-me")
    assert cursor.watermark_message_id == 50 and cursor.state == "idle"


async def test_ac93_clear_is_reentrant_after_partial_failure(service, make_ctx, details):
    ctx = make_ctx()
    await service.write(ctx, "remember", content="用户的工位在 5 楼", type="fact", detail="详细" * 5)

    async def boom(key):
        raise ConnectionError("minio down")

    original = details.delete
    details.delete = boom
    with pytest.raises(ConnectionError):
        await service.clear(ctx)
    details.delete = original
    await service.clear(ctx)
    assert await service.list(ctx) == [] and await _items() == {}


async def test_ac101_ac102_each_operation_audited_and_counted(service, make_ctx, audit_rows, kv):
    ctx = make_ctx(turn_id="t1")
    a = await service.add_manual(ctx, "用户喜欢跑步", "preference")
    b = await service.edit(ctx, a.item_id, "用户喜欢游泳")
    await service.delete(ctx, b.item_id)
    c = await service.write(ctx, "remember", content="用户的球队是湖人", type="preference")
    await _undo_last(service, ctx)
    await service.clear(ctx)
    assert [r["action"] for r in audit_rows.rows] == [
        "memory.item.add",
        "memory.item.edit",
        "memory.item.delete",
        "memory.item.remember",
        "memory.item.undo",
        "memory.item.clear",
    ]
    assert c.ok
    assert await counter(kv, ctx.tenant_id, m.ADDED_MANUAL) == 2
    assert await counter(kv, ctx.tenant_id, m.UNDO) == 1
    assert await counter(kv, ctx.tenant_id, m.DELETED) >= 2  # counts survive the clear


async def test_minio_detail_store_keys_and_roundtrip(make_ctx):
    """The MinIO DetailStore writes immutable objects under the per-user prefix."""
    from bisheng.memory.domain.services.detail_store import MinioDetailStore

    class FakeObj:
        def __init__(self, name):
            self.object_name = name

    class FakeStorage:
        bucket = "bisheng"

        def __init__(self):
            self.objects = {}
            outer = self

            class Client:
                def list_objects(self, bucket, prefix, recursive):
                    async def gen():
                        for k in list(outer.objects):
                            if k.startswith(prefix):
                                yield FakeObj(k)

                    return gen()

            self.minio_client = Client()

        async def put_object(self, object_name, file, content_type):
            self.objects[object_name] = file

        async def get_object(self, object_name):
            return self.objects.get(object_name)

        async def remove_object(self, object_name):
            self.objects.pop(object_name, None)

    storage = FakeStorage()
    store = MinioDetailStore(storage)
    ctx = make_ctx()
    key = await store.put(ctx, "item-1", "正文")
    assert key == f"memory/{ctx.tenant_id}/{ctx.user_id}/item-1.md"
    assert await store.get(key) == "正文"
    await store.put(make_ctx(user_id=USER_2), "item-2", "别人的")
    await store.delete_user(ctx)
    assert list(storage.objects) == [f"memory/{ctx.tenant_id}/{USER_2}/item-2.md"]
