"""Regression tests for the connection-pool / row-lock leak triggered during
stress testing.

Root cause (see incident on the 109 DaMeng deployment):
1. ``async_session`` caught ``Exception`` for its rollback path, but
   ``asyncio.CancelledError`` is a ``BaseException`` (Py3.8+). A cancelled
   request therefore skipped rollback, leaving an open transaction that held a
   row lock ("idle in transaction") and stalled the whole pool.
2. ``MessageSessionDao.touch_session`` did ``UPDATE ... (await) ... COMMIT`` —
   the window between acquiring the row lock and committing could be cut by a
   cancellation, leaking the lock. Running the bump in AUTOCOMMIT removes the
   window: the DB releases the lock the instant the statement executes.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from bisheng.core.database.connection import DatabaseConnectionManager


def _sqlite_async_engine(url: str = "sqlite+aiosqlite://"):
    return create_async_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)


# ---------------------------------------------------------------------------
# Fix #1 — async_session must roll back on CancelledError (BaseException)
# ---------------------------------------------------------------------------


async def test_async_session_rolls_back_on_cancellederror():
    engine = _sqlite_async_engine()
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
# Fix #2 — autocommit helper persists immediately (no lingering transaction)
# ---------------------------------------------------------------------------


async def test_async_execute_autocommit_commits(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'lock_safety.db'}"
    setup_engine = create_async_engine(url)
    async with setup_engine.begin() as conn:
        await conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, v INTEGER)"))
        await conn.execute(text("INSERT INTO t (id, v) VALUES (1, 0)"))
    await setup_engine.dispose()

    mgr = DatabaseConnectionManager(url)
    await mgr.async_execute_autocommit(text("UPDATE t SET v = 42 WHERE id = 1"))

    # A brand-new engine guarantees a separate connection: under file SQLite it
    # only sees the row if the helper actually committed.
    verify_engine = create_async_engine(url)
    async with verify_engine.connect() as conn:
        value = (await conn.execute(text("SELECT v FROM t WHERE id = 1"))).scalar()
    await verify_engine.dispose()

    assert value == 42


# ---------------------------------------------------------------------------
# Fix #2 — touch_session delegates to the autocommit helper, not session+commit
# ---------------------------------------------------------------------------


async def test_touch_session_uses_autocommit(monkeypatch):
    from bisheng.database.models import session as session_module

    captured: dict = {}

    async def _fake_autocommit(statement):
        captured["statement"] = statement

    monkeypatch.setattr(session_module, "async_execute_autocommit", _fake_autocommit)

    await session_module.MessageSessionDao.touch_session("chat-abc")

    compiled = str(captured["statement"]).lower()
    assert "message_session" in compiled
    assert "update_time" in compiled
