"""F004 AC-39: an exclusive submit (Open API daily chat) only ever starts a new run.

The Open API response must carry the answer of its own message, so that
message never joins the inbox and never becomes the answer of a waiting run.
"""

import json

import fakeredis.aioredis
import pytest

from bisheng.workstation.domain.services import run_dispatch as rd
from bisheng.workstation.domain.services import run_lease as rl
from bisheng.workstation.domain.services.run_dispatch import RunDispatchService
from bisheng.workstation.domain.services.run_lease import RunLeaseService

CID = "conv-x"


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


def msg(text: str, **extra) -> dict:
    return {"text": text, "task_mode": False, "user_id": 7, "tenant_id": 3, **extra}


@pytest.fixture
def redis():
    return fakeredis.aioredis.FakeRedis()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def relays():
    return []


@pytest.fixture
def svc(redis, clock, relays):
    async def enqueue(item: dict) -> None:
        relays.append(item)

    async def on_expired(_cid: str, _run_id: str) -> None:
        return None

    return RunDispatchService(redis=redis, clock=clock, enqueue_relay=enqueue, on_run_expired=on_expired)


@pytest.fixture
def lease(redis, clock):
    return RunLeaseService(redis=redis, clock=clock)


async def inbox(redis) -> list[dict]:
    return [json.loads(raw) for raw in await redis.lrange(rd.inbox_key(CID), 0, -1)]


async def test_exclusive_starts_a_run_on_an_idle_conversation(svc, lease):
    res = await svc.submit(CID, msg("hello"), exclusive=True)

    assert res.kind == rd.KIND_NEW_RUN
    assert (await lease.get_state(CID)).run_id == res.run_id


async def test_exclusive_is_busy_while_a_run_holds_the_conversation(svc, lease, redis):
    first = await svc.submit(CID, msg("hello"))

    res = await svc.submit(CID, msg("second", message_id="m-2"), exclusive=True)

    assert res.kind == rd.KIND_BUSY
    assert res.run_id == first.run_id
    # Nothing was queued and the running run is untouched.
    assert await inbox(redis) == []
    state = await lease.get_state(CID)
    assert state.status == rl.STATUS_RUNNING and state.run_id == first.run_id


async def test_exclusive_never_answers_a_waiting_run(svc, lease, redis):
    first = await svc.submit(CID, msg("research", task_mode=True))
    assert await lease.park(CID, first.run_id) is True

    res = await svc.submit(CID, msg("not an answer"), exclusive=True)

    assert res.kind == rd.KIND_BUSY
    assert (await lease.get_state(CID)).status == rl.STATUS_WAITING
    assert await inbox(redis) == []


async def test_exclusive_starts_the_relay_of_unread_messages_and_waits(svc, lease, redis, clock, relays):
    old = await svc.submit(CID, msg("hello"))
    await svc.submit(CID, msg("unread", message_id="m-old"))
    clock.now += rl.LEASE_SECONDS + 1

    res = await svc.submit(CID, msg("open api", message_id="m-api"), exclusive=True)

    # The older message is answered by a relay run; this one stays out of the inbox.
    assert res.kind == rd.KIND_BUSY
    assert res.expired_run_id == old.run_id
    assert [m["message_id"] for m in await inbox(redis)] == ["m-old"]
    assert len(relays) == 1 and relays[0]["run_id"] == res.run_id

    # Once the relay run is done, the exclusive submit starts its own run.
    # (the relay run drains the inbox before it finishes)
    await redis.delete(rd.inbox_key(CID))
    await svc.on_run_finished(CID, res.run_id)
    again = await svc.submit(CID, msg("open api", message_id="m-api"), exclusive=True)
    assert again.kind == rd.KIND_NEW_RUN


async def test_exclusive_after_the_run_finished_starts_a_new_run(svc, lease):
    first = await svc.submit(CID, msg("hello"))
    assert (await svc.submit(CID, msg("next"), exclusive=True)).kind == rd.KIND_BUSY

    await svc.on_run_finished(CID, first.run_id)

    assert (await svc.submit(CID, msg("next"), exclusive=True)).kind == rd.KIND_NEW_RUN
