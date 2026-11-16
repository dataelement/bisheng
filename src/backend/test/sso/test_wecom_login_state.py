"""F120 — one-time OAuth state store."""

import json

import pytest
from redis.exceptions import RedisError

from bisheng.common.errcode.sso_sync import WeComSsoStateInvalidError
from bisheng.sso_sync.domain.services import wecom_login_state as mod


class _FakeConnection:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.down = False

    async def set(self, key, value, ex=None):
        if self.down:
            raise RedisError("redis down")
        self.store[key] = value

    async def eval(self, script, numkeys, key):
        if self.down:
            raise RedisError("redis down")
        return self.store.pop(key, None)


class _FakeClient:
    def __init__(self, conn: _FakeConnection) -> None:
        self.async_connection = conn


@pytest.fixture
def fake_redis(monkeypatch):
    conn = _FakeConnection()
    client = _FakeClient(conn)

    async def _get_redis_client():
        return client

    monkeypatch.setattr(mod, "get_redis_client", _get_redis_client)
    return conn


async def test_put_then_consume_returns_state_and_removes_it(fake_redis):
    await mod.WeComLoginStateStore.put(
        "abc",
        mode="qr",
        return_to="https://app.example.com/",
        ttl=300,
    )
    key = mod.STATE_KEY_FMT.format(state="abc")
    assert json.loads(fake_redis.store[key]) == {
        "mode": "qr",
        "return_to": "https://app.example.com/",
    }

    state = await mod.WeComLoginStateStore.consume("abc")
    assert state.mode == "qr"
    assert state.return_to == "https://app.example.com/"
    # Consumed exactly once: a replayed callback cannot log in twice.
    assert key not in fake_redis.store
    with pytest.raises(WeComSsoStateInvalidError):
        await mod.WeComLoginStateStore.consume("abc")


async def test_empty_state_is_rejected(fake_redis):
    with pytest.raises(WeComSsoStateInvalidError):
        await mod.WeComLoginStateStore.consume("")


async def test_redis_outage_fails_closed(fake_redis):
    await mod.WeComLoginStateStore.put("abc", mode="silent", return_to="https://a/", ttl=300)
    fake_redis.down = True
    with pytest.raises(WeComSsoStateInvalidError):
        await mod.WeComLoginStateStore.consume("abc")


async def test_unreadable_payload_is_rejected(fake_redis):
    fake_redis.store[mod.STATE_KEY_FMT.format(state="abc")] = "not-json"
    with pytest.raises(WeComSsoStateInvalidError):
        await mod.WeComLoginStateStore.consume("abc")
