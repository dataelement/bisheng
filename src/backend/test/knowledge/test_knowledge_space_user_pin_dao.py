"""F037 — KnowledgeSpaceUserPinDao: per-user space pin storage, decoupled from membership.

Exercises the real async DAO against an in-memory SQLite engine (get_async_db_session
patched to the test engine), matching the F011 / session-lock test patterns.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_space_user_pin import (
    KnowledgeSpaceUserPinDao,
)

_DDL = """
CREATE TABLE IF NOT EXISTS knowledge_space_user_pin (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    space_id INTEGER NOT NULL,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    UNIQUE (user_id, space_id)
)
"""


@pytest.fixture()
async def pin_db(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.execute(text(_DDL))

    @asynccontextmanager
    async def _fake_session():
        session = AsyncSession(bind=engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_space_user_pin.get_async_db_session",
        _fake_session,
    )
    yield engine
    await engine.dispose()


async def test_pin_then_list_returns_space_id(pin_db):
    await KnowledgeSpaceUserPinDao.pin(user_id=1, space_id=100)
    assert await KnowledgeSpaceUserPinDao.list_pinned_space_ids(1) == {100}


async def test_pin_is_idempotent(pin_db):
    await KnowledgeSpaceUserPinDao.pin(user_id=1, space_id=100)
    # Pinning the same space again must not raise nor create a duplicate.
    await KnowledgeSpaceUserPinDao.pin(user_id=1, space_id=100)
    assert await KnowledgeSpaceUserPinDao.list_pinned_space_ids(1) == {100}


async def test_unpin_removes_the_pin(pin_db):
    await KnowledgeSpaceUserPinDao.pin(user_id=1, space_id=100)
    await KnowledgeSpaceUserPinDao.unpin(user_id=1, space_id=100)
    assert await KnowledgeSpaceUserPinDao.list_pinned_space_ids(1) == set()


async def test_unpin_missing_is_noop(pin_db):
    # Unpinning a space that was never pinned must be a safe no-op.
    await KnowledgeSpaceUserPinDao.unpin(user_id=1, space_id=999)
    assert await KnowledgeSpaceUserPinDao.list_pinned_space_ids(1) == set()


async def test_list_is_scoped_to_user(pin_db):
    await KnowledgeSpaceUserPinDao.pin(user_id=1, space_id=100)
    await KnowledgeSpaceUserPinDao.pin(user_id=2, space_id=200)
    assert await KnowledgeSpaceUserPinDao.list_pinned_space_ids(1) == {100}
    assert await KnowledgeSpaceUserPinDao.list_pinned_space_ids(2) == {200}
