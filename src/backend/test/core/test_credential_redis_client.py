"""AC-04, AC-11, AC-15: single-dict configuration reaches both real runtime adapters."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

# Shared conftest deliberately replaces the normal module with a MagicMock.
# Load this adapter under a private name so these assertions execute real code.
_spec = importlib.util.spec_from_file_location(
    "credential_redis_adapter", Path(__file__).resolve().parents[2] / "bisheng/core/cache/redis_conn.py"
)
redis_conn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(redis_conn)


def test_single_dict_retains_options_and_does_not_mutate_input(monkeypatch):
    sync = MagicMock()
    async_pool = MagicMock()
    monkeypatch.setattr(redis_conn.ConnectionPool, "from_url", sync)
    monkeypatch.setattr(redis_conn.redis.asyncio.ConnectionPool, "from_url", async_pool)
    monkeypatch.setattr(redis_conn.redis, "StrictRedis", MagicMock())
    monkeypatch.setattr(redis_conn.redis.asyncio.Redis, "from_pool", MagicMock())
    conf = {"mode": "single", "url": "rediss://:escaped@redis/1", "ssl_cert_reqs": "required"}
    redis_conn.RedisClient(conf)
    assert conf["mode"] == "single"
    assert sync.call_args.args[0] == conf["url"]
    assert sync.call_args.kwargs["ssl_cert_reqs"] == "required"
    assert async_pool.call_args.kwargs["ssl_cert_reqs"] == "required"
