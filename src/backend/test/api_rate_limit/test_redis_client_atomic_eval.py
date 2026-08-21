import subprocess
import sys


def test_aeval_routes_by_first_key_and_passes_keys_before_args():
    script = r"""
import asyncio
from unittest.mock import AsyncMock
from bisheng.core.cache.redis_conn import RedisClient

async def main():
    client = object.__new__(RedisClient)
    client.acluster_nodes = AsyncMock()
    client.async_connection = AsyncMock()
    client.async_connection.eval.return_value = [1, 0, 0]
    result = await client.aeval(
        "return {1, 0, 0}",
        keys=["limit:{same-slot}:second", "limit:{same-slot}:minute"],
        args=[10, 30],
    )
    client.acluster_nodes.assert_awaited_once_with("limit:{same-slot}:second")
    client.async_connection.eval.assert_awaited_once_with(
        "return {1, 0, 0}", 2,
        "limit:{same-slot}:second", "limit:{same-slot}:minute", 10, 30,
    )
    assert result == [1, 0, 0]

asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
