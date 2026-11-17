"""Per-turn memory records and resident snapshots (AC-08, AC-09; decision 15)."""

from datetime import datetime, timedelta

from sqlalchemy import update
from sqlmodel import select

from bisheng.memory.domain.models.memory_resident_snapshot import MemoryResidentSnapshot
from bisheng.memory.domain.models.memory_turn_record import MemoryTurnRecord
from bisheng.memory.domain.repositories import _db
from bisheng.memory.domain.services.turn_record import TurnRecordService
from test.memory.conftest import TENANT_B, USER_2


async def _write(ctx, op="remember", item_id="i1", related=None):
    async with _db.async_session() as s:
        await TurnRecordService.add_write(s, ctx, op, item_id, related)
        await s.commit()


async def test_three_kinds_round_trip_by_turn_id(memory_db, make_ctx):
    ctx = make_ctx(turn_id="t-1")
    await _write(ctx)
    await TurnRecordService.add_retrieved(ctx, ["i2", "i3"])
    await TurnRecordService.add_retrieved(ctx, ["i3", "i4"])
    await TurnRecordService.add_summary(ctx, resident_rev=3, resident_day="2026-11-13", scene_class="chat")
    await TurnRecordService.add_summary(ctx, resident_rev=3, resident_day="2026-11-13", scene_class="chat")
    got = await TurnRecordService.get_for_owner(ctx, turn_id="t-1")
    assert [w["op"] for w in got["writes"]] == ["remember"]
    assert got["retrieved_item_ids"] == ["i2", "i3", "i4"]
    assert got["summary"]["resident_rev"] == 3
    async with _db.async_session() as s:
        kinds = [r.kind for r in (await s.exec(select(MemoryTurnRecord))).all()]
    assert sorted(kinds) == ["retrieved", "summary", "write"]  # one row per kind


async def test_bind_turn_async_and_sync_equivalent(memory_db, make_ctx):
    a = make_ctx(turn_id="t-a")
    b = make_ctx(turn_id="t-b")
    await _write(a)
    await _write(b)
    await TurnRecordService.bind_turn(a, 11)
    TurnRecordService.bind_turn_sync(b, 12)
    assert (await TurnRecordService.get_for_owner(a, message_id=11))["writes"]
    assert (await TurnRecordService.get_for_owner(b, message_id=12))["writes"]
    assert TurnRecordService.flags_for_chat_sync(a, "chat-1") == {
        11: {"turn_id": "t-a", "has_write": True, "has_attribution": False},
        12: {"turn_id": "t-b", "has_write": True, "has_attribution": False},
    }


async def test_ac08_ac09_only_owner_gets_records(memory_db, make_ctx):
    owner = make_ctx(turn_id="t-1")
    await _write(owner)
    await TurnRecordService.bind_turn(owner, 5)
    other_user = make_ctx(user_id=USER_2)
    other_tenant = make_ctx(tenant_id=TENANT_B)
    super_admin = make_ctx(user_id=1)
    for ctx in (other_user, other_tenant, super_admin):
        assert await TurnRecordService.get_for_owner(ctx, turn_id="t-1") == TurnRecordService.empty()
        assert await TurnRecordService.get_for_owner(ctx, message_id=5) == TurnRecordService.empty()


async def test_snapshot_write_read_idempotent(memory_db, make_ctx):
    ctx = make_ctx()
    await TurnRecordService.save_snapshot(ctx, 2, "2026-11-13", "chat", ["a", "b"])
    await TurnRecordService.save_snapshot(ctx, 2, "2026-11-13", "chat", ["a", "b"])
    assert await TurnRecordService.get_snapshot(ctx, 2, "2026-11-13", "chat") == ["a", "b"]
    assert await TurnRecordService.get_snapshot(make_ctx(user_id=USER_2), 2, "2026-11-13", "chat") == []


async def test_delete_user_removes_records_and_snapshots(memory_db, make_ctx):
    me = make_ctx(turn_id="t-me")
    other = make_ctx(user_id=USER_2, turn_id="t-other")
    for c in (me, other):
        await _write(c)
        await TurnRecordService.save_snapshot(c, 1, "2026-11-13", "chat", ["x"])
    await TurnRecordService.delete_user(me)
    async with _db.async_session() as s:
        turns = (await s.exec(select(MemoryTurnRecord))).all()
        snaps = (await s.exec(select(MemoryResidentSnapshot))).all()
    assert [t.user_id for t in turns] == [USER_2]
    assert [x.user_id for x in snaps] == [USER_2]


async def test_cleanup_orphan_records_older_than_a_day(memory_db, make_ctx):
    old = make_ctx(turn_id="t-old")
    fresh = make_ctx(turn_id="t-fresh")
    bound = make_ctx(turn_id="t-bound")
    for c in (old, fresh, bound):
        await _write(c)
    await TurnRecordService.bind_turn(bound, 9)
    long_ago = datetime.now() - timedelta(days=2)
    async with _db.async_session() as s:
        await s.exec(
            update(MemoryTurnRecord)
            .where(MemoryTurnRecord.turn_id.in_(["t-old", "t-bound"]))
            .values(create_time=long_ago)
        )
        await s.commit()
    removed = await TurnRecordService.cleanup_orphans(older_than=timedelta(days=1))
    assert removed == 1
    async with _db.async_session() as s:
        left = sorted(r.turn_id for r in (await s.exec(select(MemoryTurnRecord))).all())
    assert left == ["t-bound", "t-fresh"]


async def test_ac87_history_flags_attribute_retrieval_only(memory_db, make_ctx):
    """AC-87: resident memory rides along every turn, so a turn that only injected it is not
    attributed in history flags; a turn that retrieved items is."""
    resident_only = make_ctx(turn_id="t-r")
    await TurnRecordService.add_summary(resident_only, resident_rev=3, resident_day="2026-11-13", scene_class="chat")
    await TurnRecordService.bind_turn(resident_only, 21)
    searched = make_ctx(turn_id="t-s")
    await TurnRecordService.add_summary(searched, resident_rev=3, resident_day="2026-11-13", scene_class="chat")
    await TurnRecordService.add_retrieved(searched, ["i9"])
    await TurnRecordService.bind_turn(searched, 22)
    assert await TurnRecordService.flags_for_chat(searched, "chat-1") == {
        21: {"turn_id": "t-r", "has_write": False, "has_attribution": False},
        22: {"turn_id": "t-s", "has_write": False, "has_attribution": True},
    }
