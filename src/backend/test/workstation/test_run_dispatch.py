"""F004 T015: the atomic send-entry decision and the finish/relay rule (design 决策 9).

Covers AC-16 (interjections kept in send order, none lost), AC-17 (a message is
either read by the current run or starts a new one), AC-20 / AC-21 (a message
sent while the run waits is the answer and resumes that same run), AC-33 (all
state in Redis: a second service instance sees the same thing) and AC-36 (a
planned run without a free slot reports its queue position).
"""

import asyncio
import json

import fakeredis.aioredis
import pytest

from bisheng.workstation.domain.services import run_dispatch as rd
from bisheng.workstation.domain.services import run_lease as rl
from bisheng.workstation.domain.services.run_dispatch import RunDispatchService
from bisheng.workstation.domain.services.run_lease import RunLeaseService

CID = "conv-1"


class FakeClock:
    def __init__(self, start: float = 1_800_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Recorder:
    """Stands in for the worker queue and for the expired-run handler."""

    def __init__(self):
        self.relays: list[dict] = []
        self.expired: list[tuple[str, str]] = []

    async def enqueue(self, item: dict) -> None:
        self.relays.append(item)

    async def on_expired(self, conversation_id: str, run_id: str) -> None:
        self.expired.append((conversation_id, run_id))


def msg(text: str, *, task_mode: bool = False, **extra) -> dict:
    base = {
        "text": text,
        "task_mode": task_mode,
        "tools": [{"id": 1}],
        "skills": [],
        "knowledge": [],
        "files": [],
        "user_id": 7,
        "tenant_id": 3,
    }
    base.update(extra)
    return base


@pytest.fixture
def redis():
    return fakeredis.aioredis.FakeRedis()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def rec():
    return Recorder()


@pytest.fixture
def svc(redis, clock, rec):
    return RunDispatchService(redis=redis, clock=clock, enqueue_relay=rec.enqueue, on_run_expired=rec.on_expired)


@pytest.fixture
def lease(redis, clock):
    return RunLeaseService(redis=redis, clock=clock)


async def inbox(redis) -> list[dict]:
    return [json.loads(raw) for raw in await redis.lrange(rd.inbox_key(CID), 0, -1)]


def test_inbox_key_shares_conversation_hash_tag():
    assert rd.inbox_key("abc") == "bisheng:run:inbox:{abc}"


async def test_idle_starts_run(svc, lease, redis, clock):
    res = await svc.submit(CID, msg("hello"))

    assert res.disposition == "started"
    assert res.kind == rd.KIND_NEW_RUN
    assert res.run_id and res.message_id
    assert res.profile == "direct"
    assert res.as_response() == {"run_id": res.run_id, "disposition": "started", "message_id": res.message_id}

    state = await lease.get_state(CID)
    assert state.status == rl.STATUS_RUNNING
    assert state.run_id == res.run_id
    assert state.profile == "direct"
    assert state.lease_until_ms == int(clock.now * 1000) + rl.LEASE_SECONDS * 1000
    assert await redis.ttl(rl.state_key(CID)) > 0
    # The first message is the run's input, it does not go through the inbox.
    assert await inbox(redis) == []
    # The holder can renew the lease it got from submit().
    assert await lease.renew(CID, res.run_id) is True


async def test_running_enqueues(svc, lease, redis, rec):
    first = await svc.submit(CID, msg("hello"))
    second = await svc.submit(CID, msg("also do X", task_mode=True, message_id="m-2"))

    assert second.disposition == "queued"
    assert second.kind == rd.KIND_STEER
    assert second.run_id == first.run_id
    assert second.message_id == "m-2"
    assert second.inbox_length == 1

    items = await inbox(redis)
    assert len(items) == 1
    assert set(items[0]) == set(rd.INBOX_FIELDS)
    assert items[0]["message_id"] == "m-2"
    assert items[0]["text"] == "also do X"
    assert items[0]["task_mode"] is True
    assert items[0]["tenant_id"] == 3
    assert items[0]["user_id"] == 7
    assert isinstance(items[0]["ts"], int)
    assert await redis.ttl(rd.inbox_key(CID)) > 0

    # The running run is untouched.
    state = await lease.get_state(CID)
    assert state.run_id == first.run_id and state.profile == "direct"
    assert rec.relays == [] and rec.expired == []


async def test_waiting_treated_as_answer(svc, lease, redis, rec):
    first = await svc.submit(CID, msg("research this", task_mode=True))
    assert await lease.park(CID, first.run_id) is True

    answer = await svc.submit(CID, msg("option B"))

    assert answer.disposition == "started"
    assert answer.kind == rd.KIND_ANSWER
    assert answer.run_id == first.run_id  # the same run resumes, no new run
    assert answer.profile == "planned"  # the parked run's profile, not the message's
    assert await inbox(redis) == []

    state = await lease.get_state(CID)
    assert state.status == rl.STATUS_RUNNING
    assert state.run_id == first.run_id
    assert await lease.is_lease_valid(CID) is True

    # A second message right behind the answer is an interjection, not a second answer.
    third = await svc.submit(CID, msg("and one more thing"))
    assert third.disposition == "queued"
    assert third.run_id == first.run_id
    assert rec.relays == [] and rec.expired == []


async def test_expired_lease_fails_old_run(svc, lease, redis, clock, rec):
    old = await svc.submit(CID, msg("hello"))
    clock.advance(rl.LEASE_SECONDS + 1)  # the process died, nobody renewed

    new = await svc.submit(CID, msg("anyone there?"))

    assert new.disposition == "started"
    assert new.kind == rd.KIND_NEW_RUN
    assert new.run_id != old.run_id
    assert new.expired_run_id == old.run_id
    # The old run is reported exactly once so the handler can mark it failed and emit run_failed.
    assert rec.expired == [(CID, old.run_id)]

    state = await lease.get_state(CID)
    assert state.run_id == new.run_id
    assert await lease.is_lease_valid(CID) is True
    # The dead run can no longer renew or finish on top of the new run.
    assert await lease.renew(CID, old.run_id) is False
    stale = await svc.on_run_finished(CID, old.run_id)
    assert stale.outcome == rd.OUTCOME_STALE
    assert (await lease.get_state(CID)).run_id == new.run_id


async def test_expired_lease_default_handler_emits_run_failed(redis, clock):
    from bisheng.linsight.domain.services.run_event_stream import RunEventStream

    svc = RunDispatchService(redis=redis, clock=clock)
    old = await svc.submit(CID, msg("hello"))
    clock.advance(rl.LEASE_SECONDS + 1)
    await svc.submit(CID, msg("again"))

    events = [e async for e in _read_all(RunEventStream(redis), CID)]
    failed = [e for e in events if e["type"] == "run_failed"]
    assert len(failed) == 1
    assert failed[0]["run_id"] == old.run_id
    assert set(failed[0]["data"]) == {"code", "reason", "detail", "reference_id"}
    assert failed[0]["data"]["reason"] == rd.EXPIRED_REASON


async def _read_all(stream, conversation_id):
    raw = await stream._redis.xrange(f"bisheng:run:events:{{{conversation_id}}}")
    for _entry_id, fields in raw:
        f = {k.decode(): v.decode() for k, v in fields.items()}
        yield {"type": f["type"], "run_id": f["run_id"], "data": json.loads(f["data"])}


async def test_expired_lease_with_unread_inbox_relays_in_order(svc, lease, redis, clock, rec):
    old = await svc.submit(CID, msg("hello"))
    await svc.submit(CID, msg("unread interjection", task_mode=True, message_id="m-old"))
    clock.advance(rl.LEASE_SECONDS + 1)

    res = await svc.submit(CID, msg("newer message", message_id="m-new"))

    # The older unread message must be handled first: the new one joins the
    # inbox behind it and one relay run takes the whole inbox.
    assert res.disposition == "queued"
    assert res.kind == rd.KIND_RELAY
    assert res.expired_run_id == old.run_id
    assert rec.expired == [(CID, old.run_id)]
    assert [m["message_id"] for m in await inbox(redis)] == ["m-old", "m-new"]
    assert len(rec.relays) == 1
    assert rec.relays[0]["run_id"] == res.run_id
    assert rec.relays[0]["profile"] == "planned"
    assert rec.relays[0]["tenant_id"] == 3
    assert (await lease.get_state(CID)).run_id == res.run_id


async def test_recover_expired_without_a_message(svc, lease, redis, clock, rec):
    assert await svc.recover_expired(CID) is None  # idle: nothing to do

    old = await svc.submit(CID, msg("hello"))
    assert await svc.recover_expired(CID) is None  # lease valid: nothing to do
    clock.advance(rl.LEASE_SECONDS + 1)

    res = await svc.recover_expired(CID)  # e.g. called when a client subscribes
    assert res is not None and res.expired_run_id == old.run_id
    assert res.outcome == rd.OUTCOME_IDLE
    assert rec.expired == [(CID, old.run_id)]
    assert (await lease.get_state(CID)).status == rl.STATUS_IDLE
    assert await svc.recover_expired(CID) is None  # reported once only


async def test_concurrent_send_single_run(redis, clock, rec):
    # Two service instances on one Redis stand for two API nodes (AC-33).
    nodes = [
        RunDispatchService(redis=redis, clock=clock, enqueue_relay=rec.enqueue, on_run_expired=rec.on_expired),
        RunDispatchService(redis=redis, clock=clock, enqueue_relay=rec.enqueue, on_run_expired=rec.on_expired),
    ]
    results = await asyncio.gather(*[nodes[i % 2].submit(CID, msg(f"m{i}", message_id=f"id-{i}")) for i in range(20)])

    started = [r for r in results if r.disposition == "started"]
    queued = [r for r in results if r.disposition == "queued"]
    assert len(started) == 1
    assert len(queued) == 19
    assert {r.run_id for r in results} == {started[0].run_id}

    submit_order = [f"id-{i}" for i in range(20) if f"id-{i}" != started[0].message_id]
    assert [m["message_id"] for m in await inbox(redis)] == submit_order
    assert sorted(r.inbox_length for r in queued) == list(range(1, 20))


async def test_finish_with_inbox_starts_relay(svc, lease, redis, clock, rec):
    first = await svc.submit(CID, msg("quick question"))  # direct run in the API process
    await svc.submit(
        CID,
        msg("now research it", task_mode=True, message_id="m-1", tools=[{"id": 9}], knowledge=[{"id": 5}]),
    )
    await svc.submit(CID, msg("and be brief", task_mode=False, message_id="m-2"))

    fin = await svc.on_run_finished(CID, first.run_id)

    assert fin.outcome == rd.OUTCOME_RELAY
    assert fin.run_id and fin.run_id != first.run_id
    # Settings come from the FIRST inbox message, not the last one.
    assert fin.profile == "planned"

    assert len(rec.relays) == 1  # into the worker queue, although the finished run was direct
    item = rec.relays[0]
    assert item["conversation_id"] == CID
    assert item["run_id"] == fin.run_id
    assert item["profile"] == "planned"
    assert item["relay"] is True
    assert item["tenant_id"] == 3
    assert item["user_id"] == 7
    assert item["message_id"] == "m-1"
    assert item["task_mode"] is True
    assert item["tools"] == [{"id": 9}]
    assert item["knowledge"] == [{"id": 5}]
    json.dumps(item)  # a queue item must be plain JSON

    # The conversation stays held by the relay run: no gap in which another run could start.
    state = await lease.get_state(CID)
    assert state.status == rl.STATUS_RUNNING
    assert state.run_id == fin.run_id
    assert state.profile == "planned"
    assert state.lease_until_ms == int(clock.now * 1000) + rd.QUEUED_LEASE_SECONDS * 1000
    late = await svc.submit(CID, msg("late", message_id="m-3"))
    assert late.disposition == "queued" and late.run_id == fin.run_id

    # The relay run takes the whole inbox, in send order, exactly once (AC-16).
    drained = await svc.drain_inbox(CID)
    assert [m["message_id"] for m in drained] == ["m-1", "m-2", "m-3"]
    assert await svc.drain_inbox(CID) == []

    # The worker that picks the relay run up keeps the lease alive with renew().
    assert await lease.renew(CID, fin.run_id) is True


async def test_finish_empty_goes_idle(svc, lease, redis, rec):
    first = await svc.submit(CID, msg("hello"))

    fin = await svc.on_run_finished(CID, first.run_id)

    assert fin.outcome == rd.OUTCOME_IDLE
    assert fin.run_id is None
    assert rec.relays == []
    state = await lease.get_state(CID)
    assert state.status == rl.STATUS_IDLE and state.run_id is None

    # AC-17: a message that arrives after the run ended starts a new run.
    nxt = await svc.submit(CID, msg("next"))
    assert nxt.disposition == "started" and nxt.run_id != first.run_id


async def test_finish_relay_enqueue_failure_is_raised(redis, clock):
    async def boom(item):
        raise RuntimeError("queue down")

    svc = RunDispatchService(redis=redis, clock=clock, enqueue_relay=boom)
    first = await svc.submit(CID, msg("hello"))
    await svc.submit(CID, msg("more", message_id="m-1"))

    with pytest.raises(RuntimeError):
        await svc.on_run_finished(CID, first.run_id)
    # Nothing is lost: the message is still in the inbox and the lapsed relay
    # lease is recovered by the next access to the conversation.
    assert [m["message_id"] for m in await inbox(redis)] == ["m-1"]


async def test_planned_queue_position(redis, clock, rec):
    calls = []

    async def probe(conversation_id, run_id, message):
        calls.append((conversation_id, run_id, message["task_mode"]))
        return 3

    svc = RunDispatchService(redis=redis, clock=clock, enqueue_relay=rec.enqueue, queue_position=probe)

    res = await svc.submit(CID, msg("research", task_mode=True))

    assert res.disposition == "started"
    assert res.profile == "planned"
    assert res.queue_position == 3
    assert res.events == [{"type": "queued", "run_id": res.run_id, "data": {"position": 3}}]
    assert calls == [(CID, res.run_id, True)]
    # A planned run sits in the worker queue first, so it gets the longer pickup lease.
    lease = RunLeaseService(redis=redis, clock=clock)
    assert (await lease.get_state(CID)).lease_until_ms == int(clock.now * 1000) + rd.QUEUED_LEASE_SECONDS * 1000

    # A direct run never asks for a slot.
    direct = await svc.submit("conv-2", msg("hi"))
    assert direct.queue_position is None and direct.events == []
    assert len(calls) == 1


async def test_planned_with_free_slot_has_no_queued_event(redis, clock):
    async def probe(conversation_id, run_id, message):
        return None

    svc = RunDispatchService(redis=redis, clock=clock, queue_position=probe)
    res = await svc.submit(CID, msg("research", task_mode=True))
    assert res.queue_position is None and res.events == []


async def test_submit_requires_tenant_id(svc):
    bad = msg("x")
    del bad["tenant_id"]
    with pytest.raises(ValueError):
        await svc.submit(CID, bad)
