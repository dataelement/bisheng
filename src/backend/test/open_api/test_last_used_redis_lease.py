"""A rejected NX acquisition must not renew last-used telemetry's throttle."""

import pickle
from types import SimpleNamespace
from unittest.mock import AsyncMock


async def exercise_real_adapter():
    from bisheng.core.cache.redis_conn import RedisClient

    writes = []
    clock = [0]
    lease = [None]

    async def atomic_set(key, value, *, nx, ex):
        writes.append((key, pickle.loads(value), nx, ex))
        if lease[0] is not None and clock[0] < lease[0]:
            return False
        lease[0] = clock[0] + ex
        return True

    redis = SimpleNamespace(acluster_nodes=AsyncMock(), async_connection=SimpleNamespace(set=atomic_set))
    assert await RedisClient.asetNx(redis, "last-used", 1, expiration=60)
    for clock[0] in [15, 30, 59]:
        assert not await RedisClient.asetNx(redis, "last-used", 1, expiration=60)
    clock[0] = 61
    assert await RedisClient.asetNx(redis, "last-used", 1, expiration=60)
    assert writes == [("last-used", 1, True, 60)] * 5


def test_nx_and_expiry_are_atomic_and_failed_calls_do_not_extend_ttl():
    import os
    import subprocess
    import sys
    from pathlib import Path

    # The repository conftest intentionally pre-mocks redis_conn. Exercise the
    # real production adapter in a fresh process without loading that conftest.
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])},
    )
    assert result.returncode == 0, result.stderr


if __name__ == "__main__":
    import asyncio

    asyncio.run(exercise_real_adapter())
