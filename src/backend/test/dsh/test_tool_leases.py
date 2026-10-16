"""AC-27, AC-29, AC-30: isolated real Redis atomic admission across clients."""

import asyncio
import shutil
import socket
import subprocess

import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from bisheng.common.errcode.dsh import DshToolConcurrencyExceededError, DshToolServiceUnavailableError
from bisheng.dsh.infrastructure.tool_leases import ToolLeases


@pytest.fixture
async def lease_redis(tmp_path):
    binary = shutil.which("redis-server")
    if not binary:
        pytest.skip("redis-server is required for the isolated real-Redis lease test")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [
            binary,
            "--bind",
            "127.0.0.1",
            "--port",
            str(port),
            "--save",
            "",
            "--appendonly",
            "no",
            "--dir",
            str(tmp_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    client = Redis(host="127.0.0.1", port=port)
    try:
        for _ in range(100):
            try:
                await client.ping()
                break
            except (OSError, RedisConnectionError):
                await asyncio.sleep(0.02)
        else:
            pytest.fail("Isolated Redis did not start")
        yield client
    finally:
        await client.aclose()
        process.terminate()
        process.wait(timeout=5)


async def test_atomic_cap_and_owner_cleanup(lease_redis):
    """AC-27, AC-30: distinct service instances share one capacity bucket."""
    first, second = ToolLeases(lease_redis), ToolLeases(lease_redis)
    await first.initialize(2, "search")
    outcomes = await asyncio.gather(
        *(service.acquire(2, "search", 2) for service in (first, second, first, second)), return_exceptions=True
    )
    owners = [result for result in outcomes if isinstance(result, str)]
    assert len(owners) == 2
    assert all(isinstance(result, (str, DshToolConcurrencyExceededError)) for result in outcomes)
    await first.release(2, "search", "not-an-owner")
    with pytest.raises(DshToolConcurrencyExceededError):
        await second.acquire(2, "search", 1)
    for owner in owners:
        await second.release(2, "search", owner)
    owner = await first.acquire(2, "search", 1)
    await first.release(2, "search", owner)


async def test_missing_state_cooldown_does_not_extend(lease_redis):
    """AC-30: losing existing admission state is not an empty-capacity assumption."""
    service = ToolLeases(lease_redis)
    with pytest.raises(DshToolServiceUnavailableError):
        await service.acquire(3, "search", 1)
    marker = await lease_redis.hget(service.key(3, "search"), "ready_after")
    with pytest.raises(DshToolServiceUnavailableError):
        await service.acquire(3, "search", 1)
    assert await lease_redis.hget(service.key(3, "search"), "ready_after") == marker
    await lease_redis.hset(service.key(3, "search"), "ready_after", "0")
    owner = await service.acquire(3, "search", 1)
    await lease_redis.hset(service.key(3, "search"), owner, "0")
    replacement = await service.acquire(3, "search", 1)
    await service.release(3, "search", owner)
    with pytest.raises(DshToolConcurrencyExceededError):
        await service.acquire(3, "search", 1)
    await service.release(3, "search", replacement)
