"""扫描恢复必须跨交付去重、限制重试, 且拒绝过期执行者。"""

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ISOLATED = os.environ.get("PROJECTION_SCAN_STATE_TEST") == "1"
if _ISOLATED:
    import fakeredis.aioredis

    # 单独加载状态模块, 避免 worker 包导入整套运行时。
    name = "bisheng.worker.knowledge._projection_scan_state"
    path = Path(__file__).resolve().parents[2] / "bisheng/worker/knowledge/_projection_scan_state.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)


@pytest.fixture
async def state():
    if not _ISOLATED:
        pytest.skip("真实 Redis 协议用例在隔离进程执行")
    from bisheng.worker.knowledge._projection_scan_state import ProjectionScanState

    redis = fakeredis.aioredis.FakeRedis()
    clock = [1000.0]
    state = ProjectionScanState(redis, 7, now=lambda: clock[0])
    state.clock = clock
    yield state
    await redis.aclose()


async def test_reservation_is_atomic_and_old_delivery_cannot_take_over(state):
    tickets = await asyncio.gather(*[state.reserve("approval", 91, "v1", max_attempts=4) for _ in range(8)])
    old = next(ticket for ticket in tickets if ticket)
    assert sum(ticket is not None for ticket in tickets) == 1
    state.clock[0] += 1801
    new = await state.reserve("approval", 91, "v1", max_attempts=4)
    assert new and new != old
    assert not await state.start(old)
    assert await state.start(new)
    assert not await state.start(new)
    assert not await state.finish(old)
    assert await state.renew(new)


@pytest.mark.parametrize("kind", ["approval", "rollback", "retirement"])
async def test_budget_and_backoff_survive_new_state_instance(state, kind):
    from bisheng.worker.knowledge._projection_scan_state import ProjectionScanState

    for _ in range(4):
        ticket = await state.reserve(kind, 91, "v1", max_attempts=4)
        assert ticket
        assert await state.start(ticket)
        assert await state.finish(ticket, error="still pending")
        assert await state.reserve(kind, 91, "v1", max_attempts=4) is None
        state.clock[0] += 3601
    restarted = ProjectionScanState(state.redis, 7, now=state.now)
    assert await restarted.reserve(kind, 91, "v1", max_attempts=4) is None
    assert await state.redis.ttl(state.key(kind, 91)) == -1
    record = json.loads(await state.redis.get(state.key(kind, 91)))
    assert record["status"] == "exhausted"
    assert record["attempts"] == 4
    assert await restarted.reserve(kind, 91, "v2", max_attempts=4)


async def test_retirement_progress_resets_stall_budget_but_identical_progress_does_not(state):
    for digest in ["a", "b", "b", "b", "b", "b"]:
        ticket = await state.reserve("retirement", 91, "v1", max_attempts=4)
        if ticket is None:
            break
        await state.start(ticket)
        await state.finish(ticket, progress=digest)
        state.clock[0] += 3601
    assert await state.reserve("retirement", 91, "v1", max_attempts=4) is None
    record = json.loads(await state.redis.get(state.key("retirement", 91)))
    assert record["attempts"] == 4


async def test_no_expiry_reset_and_tenant_isolation(state):
    from bisheng.worker.knowledge._projection_scan_state import ProjectionScanState

    ticket = await state.reserve("projection", 91, "v1")
    other = ProjectionScanState(state.redis, 8, now=state.now)
    assert await other.reserve("projection", 91, "v1")
    with pytest.raises(ValueError, match="tenant"):
        await other.start(ticket)


async def test_lost_running_lease_stops_work(state, monkeypatch):
    from bisheng.worker.knowledge._projection_scan_state import run_reserved

    cancelled = asyncio.Event()

    async def work(active, progress):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    original_sleep = asyncio.sleep

    async def no_sleep(seconds):
        await original_sleep(0)

    async def lose_lease(ticket):
        return False

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    monkeypatch.setattr(state, "renew", lose_lease)
    ticket = await state.reserve("rollback", 91, "v1", max_attempts=4)
    result = await run_reserved(state, [ticket], work)
    assert result["status"] == "failed"
    assert "lease lost" in result["error"]
    assert cancelled.is_set()


async def test_first_claims_are_renewed_while_remaining_claims_are_pending(state, monkeypatch):
    from bisheng.worker.knowledge._projection_scan_state import run_reserved

    tickets = [await state.reserve("projection", value, "v1") for value in (91, 92)]
    renewed = asyncio.Event()
    original_start, original_renew, original_sleep = state.start, state.renew, asyncio.sleep

    async def start(ticket):
        result = await original_start(ticket)
        if ticket["object_id"] == 92:
            await asyncio.wait_for(renewed.wait(), timeout=1)
        return result

    async def renew(ticket):
        result = await original_renew(ticket)
        renewed.set()
        return result

    async def no_sleep(seconds):
        await original_sleep(0)

    async def work(active, progress):
        return {"ids": sorted(ticket["object_id"] for ticket in active)}

    monkeypatch.setattr(state, "start", start)
    monkeypatch.setattr(state, "renew", renew)
    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    assert await run_reserved(state, tickets, work) == {"ids": [91, 92]}


def test_redis_state_protocol_in_isolated_process():
    if _ISOLATED:
        return
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--noconftest",
            "-o",
            "asyncio_mode=auto",
            __file__,
            "-q",
            "-k",
            "not isolated_process",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "PROJECTION_SCAN_STATE_TEST": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
