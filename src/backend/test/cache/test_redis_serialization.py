"""Authenticate cache data before any pickle evaluation; no Redis service required."""

import base64

# conftest pre-mocks the canonical module; load the actual adapter under a private
# test name without changing sys.modules or weakening its serialization boundary.
import importlib.util
import json
import pickle
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import rsa
from cryptography.fernet import Fernet

from bisheng.core.cache import serialization as codec
from bisheng.core.config.secret_crypto import get_keyring

_spec = importlib.util.spec_from_file_location(
    "tested_redis_adapter", Path(__file__).resolve().parents[2] / "bisheng/core/cache/redis_conn.py"
)
_adapter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_adapter)
RedisClient = _adapter.RedisClient


@pytest.fixture(autouse=True)
def keyring(tmp_path, monkeypatch):
    keys = [Fernet.generate_key(), Fernet.generate_key()]
    path = tmp_path / "keys.json"
    path.write_text(json.dumps({"version": 1, "keys": [k.decode() for k in keys]}))
    path.chmod(0o600)
    monkeypatch.setenv("BS_SECRET_KEYS_FILE", str(path))
    get_keyring.cache_clear()
    yield keys
    get_keyring.cache_clear()


@pytest.mark.parametrize("value", [None, True, 12, b"bytes", {"a": [1, 2]}, datetime(2026, 11, 18)])
def test_types_roundtrip(value):
    assert codec.decode_redis_value("a", codec.encode_redis_value("a", value)) == value


def test_rsa_pair_roundtrip():
    pair = rsa.newkeys(512)
    assert codec.decode_redis_value("rsa", codec.encode_redis_value("rsa", pair)) == pair


@pytest.mark.parametrize(
    "kind",
    ["raw", "empty", "crosskey", "wrongkey", "oldreader", "credential", "domain", "version", "duplicate", "base64"],
)
def test_reject_before_pickle(kind, keyring, monkeypatch):
    valid = codec.encode_redis_value("a", "ok")
    doc = {
        "domain": "bisheng.redis.object",
        "version": 1,
        "key": "a",
        "payload": base64.b64encode(pickle.dumps("marker")).decode(),
    }
    key = "a"
    if kind == "raw":
        value = pickle.dumps("marker")
    elif kind == "empty":
        value = b""
    elif kind == "crosskey":
        value, key = valid, "b"
    elif kind in {"oldreader", "wrongkey"}:
        f = Fernet(keyring[1] if kind == "oldreader" else Fernet.generate_key())
        value = codec._PREFIX + f.encrypt(json.dumps(doc).encode())
    elif kind == "credential":
        value = get_keyring().encrypt("credential")
    else:
        if kind == "domain":
            doc["domain"] = "credentials"
        if kind == "version":
            doc["version"] = 2
        if kind == "base64":
            doc["payload"] = "!invalid"
        text = json.dumps(doc)
        if kind == "duplicate":
            text = text[:-1] + ',"version":1}'
        value = codec._PREFIX + get_keyring().encrypt(text)
    loads = Mock(side_effect=AssertionError("untrusted pickle reached evaluator"))
    monkeypatch.setattr(codec.pickle, "loads", loads)
    with pytest.raises(codec.RedisSerializationError):
        codec.decode_redis_value(key, value)
    loads.assert_not_called()


def client(raw):
    c = RedisClient.__new__(RedisClient)
    c.connection = SimpleNamespace(
        get=Mock(return_value=raw), mget=Mock(return_value=[raw]), set=Mock(return_value=True)
    )
    c.async_connection = SimpleNamespace(
        get=AsyncMock(return_value=raw),
        mget=AsyncMock(return_value=[raw]),
        blpop=AsyncMock(return_value=(b"a", raw)),
        lrange=AsyncMock(return_value=[raw]),
    )
    return c


async def test_all_adapter_readers_drop_unsigned_as_cache_miss(monkeypatch):
    """Managed mode must not unpickle raw values; treat them as a miss and delete."""
    c = client(pickle.dumps("safe marker"))
    c.connection.delete = Mock(return_value=1)
    c.async_connection.delete = AsyncMock(return_value=1)
    loads = Mock(side_effect=AssertionError("raw reducer would run"))
    monkeypatch.setattr(codec.pickle, "loads", loads)
    assert c.get("a") is None
    assert c.mget(["a"]) == []
    assert await c.aget("a") is None
    assert await c.amget(["a"]) == []
    assert await c.ablpop("a") is None
    assert await c.alrange("a") == []
    loads.assert_not_called()
    assert c.connection.delete.call_count >= 1
    assert c.async_connection.delete.await_count >= 1


async def test_owned_redis_adapter_roundtrip_when_enabled():
    import os
    from uuid import uuid4

    url = os.getenv("TEST_TASK_REDIS_URL")
    if not url:
        pytest.skip("disposable Redis runner supplies TEST_TASK_REDIS_URL")
    c = RedisClient(url)
    prefix = "crypto-test:" + uuid4().hex
    keys = [prefix + suffix for suffix in (":object", ":queue", ":raw", ":bulk")]
    try:
        c.set(keys[0], b"payload")
        assert c.get(keys[0]) == b"payload"
        assert await c.aget(keys[0]) == b"payload"
        assert await c.asetNx(keys[0], "loser", expiration=1) is False
        assert c.get(keys[0]) == b"payload"
        await c.arpush(keys[1], {"id": 1})
        await c.alpush(keys[1], {"id": 0})
        assert await c.ablpop(keys[1], timeout=1) == {"id": 0}
        assert await c.alrange(keys[1]) == [{"id": 1}]
        assert await c.alrem(keys[1], {"id": 1}) == 1
        c.rpush(keys[2], '{"raw":true}')
        assert c.lpop(keys[2]) == b'{"raw":true}'
        await c.amset({keys[3]: datetime(2026, 11, 18)})
        assert await c.amget([prefix + ":missing", keys[3]]) == [datetime(2026, 11, 18)]
    finally:
        c.connection.delete(*keys)
        c.close()
        await c.aclose()


def test_sync_nx_atomic_and_key_bound():
    c = client(None)
    assert c.setNx("a", "candidate", expiration=17)
    args, kwargs = c.connection.set.call_args
    assert args[0] == "a" and codec.decode_redis_value("a", args[1]) == "candidate"
    assert kwargs == {"nx": True, "ex": 17}


async def test_randomized_removal_uses_stored_ciphertext():
    values = [codec.encode_redis_value("a", "same") for _ in range(2)]
    assert values[0] != values[1]
    c = client(None)
    c.async_connection.lrange.return_value = values
    c.async_connection.lrem = AsyncMock(return_value=1)
    assert await c.alrem("a", "same") == 2
    assert [call.args[2] for call in c.async_connection.lrem.call_args_list] == values


async def test_broadcast_rejects_before_pickle(monkeypatch):
    from bisheng.linsight.domain.services.task_message_broadcast import task_message_subscription

    class Subscription:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        subscribe = AsyncMock()
        get_message = AsyncMock(
            side_effect=[{"type": "subscribe"}, {"type": "message", "data": pickle.dumps("marker")}]
        )

    raw = SimpleNamespace(pubsub=lambda: Subscription(), eval=AsyncMock())
    loads = Mock(side_effect=AssertionError("raw broadcast evaluator"))
    monkeypatch.setattr(codec.pickle, "loads", loads)
    async with task_message_subscription(raw, "a") as stream:
        with pytest.raises(codec.RedisSerializationError):
            await anext(stream)
    loads.assert_not_called()
