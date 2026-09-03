"""F051 — ChannelUserPinDao: per-user channel pin storage, decoupled from membership.

Exercises the real async DAO against an in-memory SQLite engine (get_async_db_session
patched to the test engine), mirroring the F044 knowledge-space pin DAO test. Channel
ids are UUID strings, so the pin table keys on a VARCHAR channel_id.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.channel.domain.models.channel_user_pin import ChannelUserPinDao

_DDL = """
CREATE TABLE IF NOT EXISTS channel_user_pin (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    channel_id VARCHAR(36) NOT NULL,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    UNIQUE (user_id, channel_id)
)
"""

_CID_A = "aaaaaaaaaaaa4aaaaaaaaaaaaaaaaaaa"
_CID_B = "bbbbbbbbbbbb4bbbbbbbbbbbbbbbbbbb"


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
        "bisheng.channel.domain.models.channel_user_pin.get_async_db_session",
        _fake_session,
    )
    yield engine
    await engine.dispose()


async def test_pin_then_list_returns_channel_id(pin_db):
    await ChannelUserPinDao.pin(user_id=1, channel_id=_CID_A)
    assert await ChannelUserPinDao.list_pinned_channel_ids(1) == {_CID_A}


async def test_pin_is_idempotent(pin_db):
    await ChannelUserPinDao.pin(user_id=1, channel_id=_CID_A)
    # Pinning the same channel again must not raise nor create a duplicate.
    await ChannelUserPinDao.pin(user_id=1, channel_id=_CID_A)
    assert await ChannelUserPinDao.list_pinned_channel_ids(1) == {_CID_A}


async def test_unpin_removes_the_pin(pin_db):
    await ChannelUserPinDao.pin(user_id=1, channel_id=_CID_A)
    await ChannelUserPinDao.unpin(user_id=1, channel_id=_CID_A)
    assert await ChannelUserPinDao.list_pinned_channel_ids(1) == set()


async def test_unpin_missing_is_noop(pin_db):
    # Unpinning a channel that was never pinned must be a safe no-op.
    await ChannelUserPinDao.unpin(user_id=1, channel_id=_CID_B)
    assert await ChannelUserPinDao.list_pinned_channel_ids(1) == set()


async def test_list_is_scoped_to_user(pin_db):
    await ChannelUserPinDao.pin(user_id=1, channel_id=_CID_A)
    await ChannelUserPinDao.pin(user_id=2, channel_id=_CID_B)
    assert await ChannelUserPinDao.list_pinned_channel_ids(1) == {_CID_A}
    assert await ChannelUserPinDao.list_pinned_channel_ids(2) == {_CID_B}
