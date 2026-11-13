"""Activity registration and watermark (AC-37, AC-38, AC-40, AC-41; decision 7)."""

from datetime import datetime, timedelta

from bisheng.memory.domain.models.memory_session_cursor import MemorySessionCursor
from bisheng.memory.domain.repositories.cursor_repository import CursorRepository
from bisheng.memory.domain.services.activity import MemoryActivity
from test.memory.conftest import TENANT_A, USER_1

QUIET = timedelta(minutes=30)
LOCK = timedelta(minutes=10)


def _seed(memory_db, chat_id="c1", **kw):
    kw.setdefault("last_message_id", 10)
    kw.setdefault("watermark_message_id", 10)
    with memory_db.session() as s:
        s.add(MemorySessionCursor(chat_id=chat_id, tenant_id=TENANT_A, user_id=USER_1, **kw))
        s.commit()


def _row(memory_db, chat_id="c1"):
    with memory_db.session() as s:
        return s.get(MemorySessionCursor, chat_id)


async def test_ac37_end_turn_enabled_marks_pending(memory_db):
    _seed(memory_db)
    await MemoryActivity.end_turn("c1", 15, True)
    row = _row(memory_db)
    assert (row.state, row.last_message_id, row.watermark_message_id) == ("pending", 15, 10)


async def test_ac40_ac41_end_turn_disabled_advances_watermark(memory_db):
    _seed(memory_db)
    await MemoryActivity.end_turn("c1", 15, False)
    row = _row(memory_db)
    assert row.watermark_message_id == 15 and row.state == "idle"


async def test_watermark_never_goes_back(memory_db):
    _seed(memory_db, last_message_id=30, watermark_message_id=30)
    await MemoryActivity.end_turn("c1", 20, False)
    await CursorRepository.finish("c1", 25)
    row = _row(memory_db)
    assert row.watermark_message_id == 30 and row.last_message_id == 30


async def test_new_message_during_consolidation_keeps_pending(memory_db):
    _seed(memory_db, state="running", last_message_id=40)
    await MemoryActivity.end_turn("c1", 45, True)  # arrives while running
    await CursorRepository.finish("c1", 40)
    row = _row(memory_db)
    assert row.watermark_message_id == 40 and row.state == "pending"


async def test_ac38_quiet_period_and_backoff_and_stale_running(memory_db):
    now = datetime(2026, 11, 13, 12)
    _seed(memory_db, "recent", state="pending", last_activity_at=now - timedelta(minutes=5))
    _seed(memory_db, "quiet", state="pending", last_activity_at=now - timedelta(minutes=31))
    _seed(memory_db, "backoff", state="pending", last_activity_at=now - timedelta(hours=1), next_run_at=now + timedelta(minutes=5))
    _seed(memory_db, "stale", state="running", locked_at=now - timedelta(minutes=11), last_activity_at=now - timedelta(hours=1))
    _seed(memory_db, "fresh_running", state="running", locked_at=now - timedelta(minutes=2), last_activity_at=now - timedelta(hours=1))
    rows = await CursorRepository.list_due_for_user(TENANT_A, USER_1, now, QUIET, LOCK)
    assert sorted(r.chat_id for r in rows) == ["quiet", "stale"]
    assert await MemoryActivity.due_users(now, QUIET, LOCK) == [(TENANT_A, USER_1)]


async def test_ac38_new_turn_restarts_quiet_period(memory_db):
    now = datetime.now()
    _seed(memory_db, state="pending", last_activity_at=now - timedelta(hours=1))
    await MemoryActivity.end_turn("c1", 12, True, now=now)
    assert await CursorRepository.list_due_for_user(TENANT_A, USER_1, now, QUIET, LOCK) == []


async def test_sync_and_async_equivalent(memory_db):
    _seed(memory_db, "a")
    _seed(memory_db, "b")
    now = datetime(2026, 11, 13, 9)
    await MemoryActivity.end_turn("a", 20, True, now=now)
    MemoryActivity.end_turn_sync("b", 20, True, now=now)
    a, b = _row(memory_db, "a"), _row(memory_db, "b")
    assert (a.state, a.last_message_id, a.last_activity_at) == (b.state, b.last_message_id, b.last_activity_at)


async def test_unregistered_chat_is_noop(memory_db):
    await MemoryActivity.end_turn("nope", 3, True)
    assert _row(memory_db, "nope") is None
