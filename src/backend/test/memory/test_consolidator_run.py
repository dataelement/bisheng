"""Consolidation scheduling semantics (AC-39, AC-41, AC-44, AC-45; decision 7)."""

import asyncio
from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from bisheng.common.errcode.memory import MemoryNoModelError
from bisheng.database.models.session import MessageSession
from bisheng.memory.domain.models.memory_item import MemoryItem
from bisheng.memory.domain.models.memory_session_cursor import MemorySessionCursor
from bisheng.memory.domain.repositories import _db
from bisheng.memory.domain.services import metrics as m
from bisheng.memory.domain.services.consolidator import Consolidator, lock_key
from bisheng.memory.domain.services.llm import MemoryLLMCallError
from bisheng.user.domain.models.user import User
from test.memory.conftest import TENANT_A, USER_1, USER_2, counter, make_message

LONG_AGO = datetime.now() - timedelta(hours=2)


def _seed_chat(memory_db, chat_id, user_id=USER_1, messages=2, deleted=False, flow_type=15):
    with memory_db.session() as s:
        if s.get(User, user_id) is None:
            s.add(User(user_id=user_id, user_name=f"u{user_id}", password="x"))
        s.add(
            MessageSession(
                chat_id=chat_id, flow_id="", flow_type=flow_type, user_id=user_id, name="c", is_delete=deleted
            )
        )
        ids = []
        for i in range(messages):
            msg = make_message(chat_id, user_id, f"第{i}条")
            s.add(msg)
            s.flush()
            ids.append(msg.id)
        s.add(
            MemorySessionCursor(
                chat_id=chat_id,
                tenant_id=TENANT_A,
                user_id=user_id,
                state="pending",
                last_activity_at=LONG_AGO,
                last_message_id=ids[-1] if ids else 0,
                watermark_message_id=0,
            )
        )
        s.commit()
    return ids


def _cursor(memory_db, chat_id):
    with memory_db.session() as s:
        return s.get(MemorySessionCursor, chat_id)


class FakeContent:
    """Returns one 'add' per call; records what it saw."""

    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    async def __call__(self, ctx, cursor, end_id):
        self.calls.append((cursor.chat_id, cursor.watermark_message_id, end_id))
        if self.fail:
            raise self.fail
        return [{"op": "add", "content": f"来自{cursor.chat_id}的结论", "type": "fact"}]


@pytest.fixture
def make_consolidator(service, kv):
    def _make(content):
        return Consolidator(service=service, kv=kv, metrics=m.MemoryMetrics(kv), content_fn=content)

    return _make


async def _items():
    async with _db.async_session() as s:
        return list((await s.exec(select(MemoryItem))).all())


async def test_processes_all_due_sessions_of_user(memory_db, make_consolidator):
    a = _seed_chat(memory_db, "c1")
    _seed_chat(memory_db, "c2")
    content = FakeContent()
    await make_consolidator(content).consolidate_user(TENANT_A, USER_1)
    assert sorted(c[0] for c in content.calls) == ["c1", "c2"]
    assert _cursor(memory_db, "c1").watermark_message_id == a[-1]
    assert _cursor(memory_db, "c1").state == "idle"
    items = await _items()
    assert len(items) == 2 and all(i.origin == "auto" for i in items)


async def test_lock_held_elsewhere_skips_without_changes(memory_db, make_consolidator, kv):
    _seed_chat(memory_db, "c1")
    await kv.acquire(lock_key(TENANT_A, USER_1), "other-node", 600)
    content = FakeContent()
    await make_consolidator(content).consolidate_user(TENANT_A, USER_1)
    assert content.calls == [] and _cursor(memory_db, "c1").state == "pending"
    assert await kv.get(lock_key(TENANT_A, USER_1)) == "other-node"  # not released by us


async def test_lock_released_after_run(memory_db, make_consolidator, kv):
    _seed_chat(memory_db, "c1")
    await make_consolidator(FakeContent()).consolidate_user(TENANT_A, USER_1)
    assert await kv.get(lock_key(TENANT_A, USER_1)) is None


async def test_ac39_rerun_does_not_duplicate(memory_db, make_consolidator):
    _seed_chat(memory_db, "c1")
    c = make_consolidator(FakeContent())
    await c.consolidate_user(TENANT_A, USER_1)
    with memory_db.session() as s:  # force due again without new messages
        row = s.get(MemorySessionCursor, "c1")
        row.state = "pending"
        s.add(row)
        s.commit()
    content = FakeContent()
    await make_consolidator(content).consolidate_user(TENANT_A, USER_1)
    assert len(await _items()) == 1
    assert content.calls == []  # nothing new after the watermark


async def test_crash_mid_transaction_leaves_no_items_and_retries(memory_db, make_consolidator, monkeypatch):
    _seed_chat(memory_db, "c1")
    from bisheng.memory.domain.repositories import cursor_repository

    original = cursor_repository.CursorRepository.finish_stmt.__func__

    def boom(cls, chat_id, end_id):
        raise RuntimeError("crash before commit")

    monkeypatch.setattr(cursor_repository.CursorRepository, "finish_stmt", classmethod(boom))
    await make_consolidator(FakeContent()).consolidate_user(TENANT_A, USER_1)
    assert await _items() == []
    row = _cursor(memory_db, "c1")
    assert row.state == "pending" and row.fail_count == 1 and row.next_run_at is not None
    monkeypatch.setattr(cursor_repository.CursorRepository, "finish_stmt", classmethod(original))
    with memory_db.session() as s:
        row = s.get(MemorySessionCursor, "c1")
        row.next_run_at = None
        s.add(row)
        s.commit()
    await make_consolidator(FakeContent()).consolidate_user(TENANT_A, USER_1)
    assert len(await _items()) == 1


@pytest.mark.parametrize("error", [MemoryNoModelError(), MemoryLLMCallError("refused")])
async def test_ac45_failure_recorded_with_backoff(memory_db, make_consolidator, kv, error):
    _seed_chat(memory_db, "c1")
    await make_consolidator(FakeContent(fail=error)).consolidate_user(TENANT_A, USER_1)
    row = _cursor(memory_db, "c1")
    assert row.state == "pending" and row.fail_count == 1
    assert row.next_run_at > datetime.now()
    assert await counter(kv, TENANT_A, m.CONSOLIDATE_FAILED) == 1


async def test_failure_log_throttled(memory_db, make_consolidator, kv):
    c = make_consolidator(FakeContent(fail=MemoryNoModelError()))
    assert await c._should_log(TENANT_A, USER_1, "MemoryNoModelError") is True
    assert await c._should_log(TENANT_A, USER_1, "MemoryNoModelError") is False


async def test_ac41_deleted_session_or_switch_off_advances_without_items(memory_db, make_consolidator, make_ctx):
    from bisheng.memory.domain.repositories.setting_repository import SettingRepository

    ids_del = _seed_chat(memory_db, "gone", deleted=True)
    content = FakeContent()
    await make_consolidator(content).consolidate_user(TENANT_A, USER_1)
    assert content.calls == [] and _cursor(memory_db, "gone").watermark_message_id == ids_del[-1]
    ids = _seed_chat(memory_db, "off")
    await SettingRepository.set_enabled(make_ctx(), False)
    await make_consolidator(content).consolidate_user(TENANT_A, USER_1)
    assert content.calls == [] and _cursor(memory_db, "off").watermark_message_id == ids[-1]
    assert await _items() == []


async def test_ac44_users_in_parallel_and_same_user_single_runner(memory_db, make_consolidator, service, make_ctx):
    _seed_chat(memory_db, "u1", user_id=USER_1)
    _seed_chat(memory_db, "u2", user_id=USER_2)
    await asyncio.gather(
        make_consolidator(FakeContent()).consolidate_user(TENANT_A, USER_1),
        make_consolidator(FakeContent()).consolidate_user(TENANT_A, USER_2),
    )
    assert len(await _items()) == 2
    _seed_chat(memory_db, "u1b", user_id=USER_1)
    c1, c2 = FakeContent(), FakeContent()
    await asyncio.gather(
        make_consolidator(c1).consolidate_user(TENANT_A, USER_1),
        make_consolidator(c2).consolidate_user(TENANT_A, USER_1),
        service.write(make_ctx(), "remember", content="用户明确说自己是左撇子", type="fact"),
    )
    assert len(c1.calls) + len(c2.calls) == 1
    contents = {i.content for i in await _items()}
    assert "用户明确说自己是左撇子" in contents and "来自u1b的结论" in contents


async def test_lost_lock_stops_and_hands_rows_back(memory_db, make_consolidator, kv, monkeypatch):
    """Decision 7: when the lock can no longer be renewed, stop and leave the rest pending."""
    _seed_chat(memory_db, "c1")
    _seed_chat(memory_db, "c2")

    async def _lost(key, token, ttl):
        return False

    monkeypatch.setattr(kv, "renew", _lost)
    content = FakeContent()
    await make_consolidator(content).consolidate_user(TENANT_A, USER_1)
    assert content.calls == []
    assert {_cursor(memory_db, c).state for c in ("c1", "c2")} == {"pending"}
    assert await _items() == []


async def test_ac93_clear_during_run_drops_its_results(memory_db, make_consolidator, service, make_ctx):
    """AC-93: a clear that lands while a run is computing must not be undone by that run."""
    _seed_chat(memory_db, "c1")

    class ClearingContent(FakeContent):
        async def __call__(self, ctx, cursor, end_id):
            ops = await super().__call__(ctx, cursor, end_id)
            await service.clear(make_ctx())
            return ops

    await make_consolidator(ClearingContent()).consolidate_user(TENANT_A, USER_1)
    assert await _items() == []


async def test_ac39_truncated_backlog_moves_watermark_only_to_last_read(memory_db, make_consolidator):
    """AC-39: a run that read part of a long backlog leaves the rest for the next run."""
    ids = _seed_chat(memory_db, "c1", messages=4)

    class PartialContent(FakeContent):
        async def __call__(self, ctx, cursor, end_id):
            ops = await super().__call__(ctx, cursor, end_id)
            return ops, ids[1]

    await make_consolidator(PartialContent()).consolidate_user(TENANT_A, USER_1)
    row = _cursor(memory_db, "c1")
    assert row.watermark_message_id == ids[1] and row.state == "pending"
