"""用隔离 Lua 运行时检查并发更新保护和跨槽单键脚本。"""

import subprocess
import sys
from pathlib import Path


def test_scan_pipeline_and_compare_delete_preserve_new_value():
    script = r"""
import asyncio, pickle
from fakeredis.aioredis import FakeRedis
from bisheng.core.cache.redis_conn import RedisClient
async def run():
    raw = FakeRedis()
    redis = object.__new__(RedisClient)
    redis.async_connection = raw
    for i in range(405):
        await raw.set(f'admin_scope:{i}', pickle.dumps(5))
    found = []
    async for batch in redis.ascan_batches('admin_scope:*', batch_size=200):
        assert len(batch) <= 200
        found.extend(batch)
    assert len(set(found)) == 405
    keys = ['admin_scope:0', 'missing', 'admin_scope:1']
    values = await redis.aget_raw_many(keys)
    assert values[1] is None
    await raw.set(keys[0], pickle.dumps(6))
    assert await redis.adelete_unchanged_many([(keys[0], values[0]), (keys[2], values[2])]) == 1
    assert pickle.loads(await raw.get(keys[0])) == 6
    assert await raw.get(keys[2]) is None
    await raw.aclose()
asyncio.run(run())
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=Path(__file__).parents[2], capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stdout + result.stderr
