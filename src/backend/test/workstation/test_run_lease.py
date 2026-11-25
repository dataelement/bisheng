"""F004 T013: per-conversation run state, 30 s lease, stop flag, park to waiting.

Covers AC-22 (a parked run holds no lease), AC-29 (stop flag seen within 1 s)
and AC-33 (all state lives in Redis, so a second service instance built on the
same Redis sees exactly what the first one wrote).
"""

import asyncio

import fakeredis.aioredis
import pytest

from bisheng.workstation.domain.services import run_lease as rl
from bisheng.workstation.domain.services.run_lease import RunLeaseService


class FakeClock:
    def __init__(self, start: float = 1_800_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


CID = "conv-1"


@pytest.fixture
def redis():
    return fakeredis.aioredis.FakeRedis()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def svc(redis, clock):
    return RunLeaseService(redis=redis, clock=clock)


def test_key_names_share_conversation_hash_tag():
    assert rl.state_key("abc") == "bisheng:run:state:{abc}"
    assert rl.stop_key("r1") == "bisheng:run:stop:{r1}"


async def test_acquire_is_exclusive(svc, redis, clock):
    first = await svc.acquire(CID, "run-1", "direct")
    assert first.acquired is True

    second = await svc.acquire(CID, "run-2", "planned")
    assert second.acquired is False
    assert second.status == rl.STATUS_RUNNING
    assert second.run_id == "run-1"

    # A second service instance on the same Redis (another node) agrees.
    other_node = RunLeaseService(redis=redis, clock=clock)
    third = await other_node.acquire(CID, "run-3", "direct")
    assert third.acquired is False

    state = await other_node.get_state(CID)
    assert state.status == rl.STATUS_RUNNING
    assert state.run_id == "run-1"
    assert state.profile == "direct"
    assert state.lease_until_ms == int((clock.now + rl.LEASE_SECONDS) * 1000)

    # Another conversation is independent.
    assert (await svc.acquire("conv-2", "run-9", "direct")).acquired is True


async def test_renew_extends(svc, clock):
    await svc.acquire(CID, "run-1", "direct")
    clock.advance(20)
    assert await svc.renew(CID, "run-1") is True
    state = await svc.get_state(CID)
    assert state.lease_until_ms == int((clock.now + rl.LEASE_SECONDS) * 1000)

    # 20 s after renewal: past the original 30 s, still inside the renewed lease.
    clock.advance(20)
    assert await svc.is_lease_valid(CID) is True
    assert (await svc.acquire(CID, "run-2", "direct")).acquired is False

    # Only the holder can renew.
    assert await svc.renew(CID, "run-x") is False


async def test_expires_without_renew(svc, clock):
    await svc.acquire(CID, "run-1", "direct")
    clock.advance(rl.LEASE_SECONDS - 1)
    assert await svc.is_lease_valid(CID) is True

    clock.advance(2)
    assert await svc.is_lease_valid(CID) is False
    # The holder cannot revive a lapsed lease: others may already treat it as dead.
    assert await svc.renew(CID, "run-1") is False

    # A newcomer takes over and learns which run lapsed, so it can mark it failed.
    taken = await svc.acquire(CID, "run-2", "planned")
    assert taken.acquired is True
    assert taken.expired_run_id == "run-1"
    state = await svc.get_state(CID)
    assert state.run_id == "run-2"
    assert state.profile == "planned"


async def test_stop_flag_visible(svc, redis, clock):
    assert await svc.should_stop("run-1") is False
    await svc.request_stop("run-1")

    # Another node polls the flag (the running coroutine checks once a second).
    other_node = RunLeaseService(redis=redis, clock=clock)
    assert await asyncio.wait_for(other_node.should_stop("run-1"), timeout=1) is True
    assert await other_node.should_stop("run-2") is False

    ttl = await redis.ttl(rl.stop_key("run-1"))
    assert 0 < ttl <= rl.STOP_FLAG_TTL_SECONDS


async def test_stop_parked_run_goes_idle(svc):
    await svc.acquire(CID, "run-1", "planned")
    assert await svc.park(CID, "run-1") is True

    result = await svc.request_stop("run-1", conversation_id=CID)
    assert result.parked_run_released is True
    state = await svc.get_state(CID)
    assert state.status == rl.STATUS_IDLE
    assert state.run_id is None


async def test_park_releases_lease(svc, clock):
    await svc.acquire(CID, "run-1", "planned")
    assert await svc.park(CID, "run-x") is False  # not the holder

    assert await svc.park(CID, "run-1") is True
    state = await svc.get_state(CID)
    assert state.status == rl.STATUS_WAITING
    assert state.run_id == "run-1"
    assert state.profile == "planned"
    assert state.lease_until_ms == 0
    assert await svc.is_lease_valid(CID) is False

    # A parked run is not renewed by anyone; time passing does not fail it.
    clock.advance(3600)
    assert await svc.renew(CID, "run-1") is False
    assert (await svc.get_state(CID)).status == rl.STATUS_WAITING

    # A different run cannot take the conversation while it waits for an answer.
    blocked = await svc.acquire(CID, "run-2", "direct")
    assert blocked.acquired is False
    assert blocked.status == rl.STATUS_WAITING

    # The answer resumes the same run id and takes a fresh lease.
    resumed = await svc.acquire(CID, "run-1", "planned")
    assert resumed.acquired is True
    state = await svc.get_state(CID)
    assert state.status == rl.STATUS_RUNNING
    assert state.lease_until_ms == int((clock.now + rl.LEASE_SECONDS) * 1000)


async def test_release_returns_to_idle(svc):
    await svc.acquire(CID, "run-1", "direct")
    assert await svc.release(CID, "run-x") is False
    assert await svc.release(CID, "run-1") is True
    state = await svc.get_state(CID)
    assert state.status == rl.STATUS_IDLE
    assert state.run_id is None
    assert (await svc.acquire(CID, "run-2", "direct")).acquired is True


async def test_state_key_has_ttl(svc, redis):
    await svc.acquire(CID, "run-1", "direct")
    ttl = await redis.ttl(rl.state_key(CID))
    assert 0 < ttl <= rl.STATE_TTL_SECONDS


async def test_renew_loop_stops_when_lease_lost(svc, clock):
    await svc.acquire(CID, "run-1", "direct")
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.advance(seconds)
        if len(sleeps) == 3:
            # Simulate a takeover after the lease was released elsewhere.
            await svc.release(CID, "run-1")

    lost = await svc.renew_loop(CID, "run-1", sleep=fake_sleep)
    assert lost is True
    assert sleeps == [rl.RENEW_INTERVAL_SECONDS] * 3


async def test_reclaim_only_while_the_state_still_names_the_run(svc, clock):
    """A lapsed run may end itself only when nobody declared it dead (F004 review M2)."""
    await svc.acquire(CID, "run-1", "direct")
    clock.advance(rl.LEASE_SECONDS + 1)
    assert await svc.renew(CID, "run-1") is False

    # Lapsed, but the state still says "running" for run-1: nobody took over.
    assert await svc.reclaim(CID, "run-1") is True
    assert await svc.is_lease_valid(CID)

    # Another run took the lapsed conversation: run-1 gets nothing back.
    clock.advance(rl.LEASE_SECONDS + 1)
    assert (await svc.acquire(CID, "run-2", "direct")).expired_run_id == "run-1"
    assert await svc.reclaim(CID, "run-1") is False
    assert (await svc.get_state(CID)).run_id == "run-2"

    # Neither a parked nor an idle conversation can be reclaimed.
    assert await svc.park(CID, "run-2")
    assert await svc.reclaim(CID, "run-2") is False
    await svc.request_stop("run-2", CID)
    assert await svc.reclaim(CID, "run-2") is False


def test_parked_stream_outlives_the_waiting_state():
    """The answer to a parked run needs the run's stream for as long as "waiting" lasts (review M4)."""
    from bisheng.linsight.domain.services import run_event_stream

    assert run_event_stream.PARKED_TTL_SECONDS >= rl.STATE_TTL_SECONDS
