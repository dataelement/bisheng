"""``sync_enqueue_lock`` tests — duplicate "run now" submissions.

Uses an in-memory async Redis stub (same style as the WeCom provider tests) so
the NX semantics and the token-matched release are exercised without a broker.
"""

from __future__ import annotations

import pytest

from bisheng.org_sync.domain.services import sync_enqueue_lock as mod


class _Conn:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.set_calls: list[tuple] = []

    async def set(self, key, value, nx=False, ex=None):
        self.set_calls.append((key, value, nx, ex))
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        return 1 if self.store.pop(key, None) is not None else 0


class _Client:
    def __init__(self, conn: _Conn) -> None:
        self.async_connection = conn


@pytest.fixture()
def fake_redis(monkeypatch):
    conn = _Conn()

    async def _get():
        return _Client(conn)

    monkeypatch.setattr(mod, "get_redis_client", _get)
    return conn


async def test_second_acquire_is_rejected_until_released(fake_redis):
    first = await mod.acquire_enqueue_lock(7)
    assert first.acquired is True
    assert first.token

    second = await mod.acquire_enqueue_lock(7)
    assert second.acquired is False
    assert second.token is None

    await mod.release_enqueue_lock(7, first.token)

    third = await mod.acquire_enqueue_lock(7)
    assert third.acquired is True


async def test_release_ignores_a_foreign_token(fake_redis):
    held = await mod.acquire_enqueue_lock(7)

    # A stale worker (TTL expired, lock re-taken) must not free the new run.
    await mod.release_enqueue_lock(7, "not-our-token")
    assert fake_redis.store[mod.KEY_TEMPLATE.format(config_id=7)] == held.token

    await mod.release_enqueue_lock(7, None)  # degraded-mode no-op
    assert mod.KEY_TEMPLATE.format(config_id=7) in fake_redis.store


async def test_lock_carries_a_ttl(fake_redis):
    await mod.acquire_enqueue_lock(7)
    _, _, nx, ex = fake_redis.set_calls[-1]
    assert nx is True
    assert ex == mod.DEFAULT_TTL_SECONDS


async def test_redis_failure_degrades_to_db_guard(monkeypatch):
    async def _boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(mod, "get_redis_client", _boom)

    lock = await mod.acquire_enqueue_lock(7)

    # Fail-open: the DB CAS in pull_sync_service is still authoritative.
    assert lock.acquired is True
    assert lock.token is None
    await mod.release_enqueue_lock(7, lock.token)  # must not raise
