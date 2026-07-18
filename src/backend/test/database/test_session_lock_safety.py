"""Regression tests for the connection-pool / row-lock leak triggered during
stress testing.

Root cause (109 DaMeng deployment):
1. ``async_session`` caught ``Exception`` for its rollback path, but
   ``asyncio.CancelledError`` is a ``BaseException`` (Py3.8+). A cancelled
   request therefore skipped rollback, leaving an open transaction that held a
   row lock ("idle in transaction") and stalled the whole pool.
2. ``MessageSessionDao.touch_session`` did ``UPDATE ... (await) ... COMMIT`` —
   a cancellation between acquiring the row lock and committing leaked the
   lock. The write is now shielded so it always runs to completion.

   (AUTOCOMMIT was tried first but the dmAsync dialect cannot reset the
   isolation level on connection checkin while a transaction is open
   -> [CODE:-6510], so ``asyncio.shield`` is used instead.)
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from bisheng.core.database.connection import DatabaseConnectionManager


# ---------------------------------------------------------------------------
# Fix #1 — async_session must roll back on CancelledError (BaseException)
# ---------------------------------------------------------------------------


async def test_async_session_rolls_back_on_cancellederror():
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    mgr = DatabaseConnectionManager("sqlite+aiosqlite://")
    mgr._async_engine = engine

    rollback_calls: list[bool] = []

    with pytest.raises(asyncio.CancelledError):
        async with mgr.async_session() as session:
            original_rollback = session.rollback

            async def _spy():
                rollback_calls.append(True)
                await original_rollback()

            session.rollback = _spy
            raise asyncio.CancelledError()

    assert rollback_calls == [True], "rollback must run when the body is cancelled"
    await engine.dispose()


# ---------------------------------------------------------------------------
# Fix #2 — touch_session's write must complete even if the caller is cancelled
# ---------------------------------------------------------------------------


async def test_touch_session_completes_write_despite_cancellation(monkeypatch):
    from bisheng.database.models import session as session_module

    events: list[str] = []

    class _FakeSession:
        async def exec(self, statement):
            events.append("exec")

        async def commit(self):
            await asyncio.sleep(0)  # suspension point a cancel could hit
            events.append("commit")

    @asynccontextmanager
    async def _fake_get_async_db_session():
        yield _FakeSession()

    monkeypatch.setattr(session_module, "get_async_db_session", _fake_get_async_db_session)

    task = asyncio.ensure_future(session_module.MessageSessionDao.touch_session("chat-abc"))
    await asyncio.sleep(0)  # let the shielded write start
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # The shielded write must still finish committing despite the cancellation.
    await asyncio.sleep(0.05)
    assert events == ["exec", "commit"]
