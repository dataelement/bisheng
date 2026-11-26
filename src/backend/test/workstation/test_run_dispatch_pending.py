"""F004 design §7 item 4: a run that finds its conversation held waits for it.

A deep-research run submitted through the Open API or ``/workbench/start-execute``
is not known to the send entry. When the worker takes it from the queue while
another run holds the conversation, ``claim_or_wait`` stores its queue item in
the conversation's pending list; the finish script hands the conversation to the
first waiting item. All state is in Redis, so the tests use two service
instances where a second node matters.

Also covers ``discard_inbox`` (item 6): a stopped run starts no relay run.
"""

import asyncio
import json

import fakeredis.aioredis
import pytest

from bisheng.workstation.domain.services import run_dispatch as rd
from bisheng.workstation.domain.services import run_lease as rl
from bisheng.workstation.domain.services.run_dispatch import RunDispatchService
from bisheng.workstation.domain.services.run_lease import RunLeaseService

CID = "conv-pending-1"
TENANT = 3


class FakeClock:
    def __init__(self, start: float = 1_800_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now


class Queue:
    """Stands in for the worker queue."""

    def __init__(self):
        self.relays: list[dict] = []
        self.items: list[dict] = []
        self.expired: list[tuple[str, str]] = []
        self.fail_items = False

    async def enqueue_relay(self, item: dict) -> None:
        self.relays.append(item)

    async def enqueue_item(self, item: dict) -> None:
        if self.fail_items:
            raise RuntimeError("redis down")
        self.items.append(item)

    async def on_expired(self, conversation_id: str, run_id: str) -> None:
        self.expired.append((conversation_id, run_id))


def item(svid: str) -> dict:
    """A worker-queue item as ``encode_queue_item`` builds it."""
    return {
        "session_version_id": svid,
        "resume": False,
        "user_input": None,
        "continue_question": None,
        "tenant_id": TENANT,
    }


def msg(text: str, task_mode: bool = False) -> dict:
    return {"text": text, "task_mode": task_mode, "user_id": 7, "tenant_id": TENANT}


@pytest.fixture
def redis():
    return fakeredis.aioredis.FakeRedis()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def queue():
    return Queue()


def _service(redis, clock, queue) -> RunDispatchService:
    return RunDispatchService(
        redis,
        clock=clock,
        enqueue_relay=queue.enqueue_relay,
        enqueue_item=queue.enqueue_item,
        on_run_expired=queue.on_expired,
    )


@pytest.fixture
def svc(redis, clock, queue):
    return _service(redis, clock, queue)


@pytest.fixture
def lease(redis, clock):
    return RunLeaseService(redis, clock=clock)


async def _pending(redis) -> list[dict]:
    return [json.loads(raw) for raw in await redis.lrange(rd.pending_key(CID), 0, -1)]


async def test_idle_conversation_is_taken_at_once(svc, lease, redis):
    result = await svc.claim_or_wait(CID, "run-a", "planned", item("sv-a"))

    assert result.held is True and result.expired_run_id is None
    state = await lease.get_state(CID)
    assert (state.status, state.run_id, state.profile) == (rl.STATUS_RUNNING, "run-a", "planned")
    # The normal short lease, like ``RunLeaseService.acquire``.
    assert state.lease_until_ms == int(svc._clock() * 1000) + rl.LEASE_SECONDS * 1000
    assert await _pending(redis) == []
    assert await redis.scard(rd.PENDING_INDEX_KEY) == 0


async def test_second_run_waits_and_starts_when_the_first_ends(svc, lease, redis, queue):
    assert (await svc.claim_or_wait(CID, "run-a", "planned", item("sv-a"))).held

    waiting = await svc.claim_or_wait(CID, "run-b", "planned", item("sv-b"))

    assert waiting.held is False and waiting.holder_run_id == "run-a"
    # The holder is untouched; the second run's queue item is stored with its run id.
    assert (await lease.get_state(CID)).run_id == "run-a"
    assert await _pending(redis) == [{**item("sv-b"), "run_id": "run-b"}]
    assert await redis.sismember(rd.PENDING_INDEX_KEY, CID)
    assert queue.items == []

    finished = await svc.on_run_finished(CID, "run-a")

    # No idle gap: the conversation goes straight to the waiting run, with the queued lease.
    assert finished.outcome == rd.OUTCOME_PENDING and finished.run_id == "run-b"
    assert queue.items == [{**item("sv-b"), "run_id": "run-b"}]
    state = await lease.get_state(CID)
    assert (state.status, state.run_id, state.profile) == (rl.STATUS_RUNNING, "run-b", "planned")
    assert state.lease_until_ms == int(svc._clock() * 1000) + rd.QUEUED_LEASE_SECONDS * 1000
    assert await _pending(redis) == []

    # The worker that takes the item claims the reservation, then ends normally.
    assert (await svc.claim_or_wait(CID, "run-b", "planned", item("sv-b"))).held
    assert (await svc.on_run_finished(CID, "run-b")).outcome == rd.OUTCOME_IDLE
    assert (await lease.get_state(CID)).status == rl.STATUS_IDLE


async def test_waiting_runs_start_in_arrival_order_on_another_node(redis, clock, queue, lease):
    node_a = _service(redis, clock, queue)
    node_b = _service(redis, clock, queue)
    assert (await node_a.claim_or_wait(CID, "run-a", "planned", item("sv-a"))).held
    assert not (await node_b.claim_or_wait(CID, "run-b", "planned", item("sv-b"))).held
    assert not (await node_a.claim_or_wait(CID, "run-c", "planned", item("sv-c"))).held

    # The holder ends on node A; node B's state is the same Redis state.
    assert (await node_a.on_run_finished(CID, "run-a")).run_id == "run-b"
    assert (await node_b.claim_or_wait(CID, "run-b", "planned", item("sv-b"))).held
    assert (await node_b.on_run_finished(CID, "run-b")).run_id == "run-c"

    assert [queued["run_id"] for queued in queue.items] == ["run-b", "run-c"]


async def test_concurrent_claims_give_the_conversation_to_exactly_one(svc, lease, redis, queue):
    results = await asyncio.gather(*(svc.claim_or_wait(CID, f"run-{n}", "planned", item(f"sv-{n}")) for n in range(8)))

    held = [n for n, result in enumerate(results) if result.held]
    assert len(held) == 1
    assert len(await _pending(redis)) == 7

    # Every waiting run starts exactly once.
    current = f"run-{held[0]}"
    started = [current]
    for _ in range(7):
        finished = await svc.on_run_finished(CID, current)
        assert finished.outcome == rd.OUTCOME_PENDING
        current = finished.run_id
        started.append(current)
    assert (await svc.on_run_finished(CID, current)).outcome == rd.OUTCOME_IDLE
    assert sorted(started) == sorted(f"run-{n}" for n in range(8))


async def test_unread_inbox_is_answered_before_a_waiting_run(svc, lease, redis, queue):
    first = await svc.submit(CID, msg("第一条"))
    await svc.submit(CID, msg("运行中又发了一条"))
    assert not (await svc.claim_or_wait(CID, "run-api", "planned", item("sv-api"))).held

    relay = await svc.on_run_finished(CID, first.run_id)

    # The user's own unread message comes first: a relay run, the waiting run keeps waiting.
    assert relay.outcome == rd.OUTCOME_RELAY
    assert queue.items == [] and len(queue.relays) == 1
    await svc.drain_inbox(CID)
    after_relay = await svc.on_run_finished(CID, relay.run_id)
    assert after_relay.outcome == rd.OUTCOME_PENDING and after_relay.run_id == "run-api"


async def test_run_reserved_by_the_send_entry_claims_its_own_reservation(svc, lease, redis):
    started = await svc.submit(CID, msg("深度研究", task_mode=True))

    result = await svc.claim_or_wait(CID, started.run_id, "planned", item("sv-web"))

    assert result.held is True
    state = await lease.get_state(CID)
    # The queued lease of the reservation became the normal short lease.
    assert state.run_id == started.run_id
    assert state.lease_until_ms == int(svc._clock() * 1000) + rl.LEASE_SECONDS * 1000
    assert await _pending(redis) == []


async def test_parked_run_is_resumed_by_its_own_id_and_blocks_others(svc, lease, redis):
    assert (await svc.claim_or_wait(CID, "run-a", "planned", item("sv-a"))).held
    assert await lease.park(CID, "run-a")

    assert not (await svc.claim_or_wait(CID, "run-b", "planned", item("sv-b"))).held
    resumed = await svc.claim_or_wait(CID, "run-a", "planned", {**item("sv-a"), "resume": True})

    assert resumed.held is True
    assert (await lease.get_state(CID)).status == rl.STATUS_RUNNING


async def test_lapsed_holder_is_taken_over_and_reported(svc, lease, clock):
    assert (await svc.claim_or_wait(CID, "run-dead", "planned", item("sv-dead"))).held
    clock.now += rl.LEASE_SECONDS + 1

    result = await svc.claim_or_wait(CID, "run-b", "planned", item("sv-b"))

    assert result.held is True and result.expired_run_id == "run-dead"
    assert (await lease.get_state(CID)).run_id == "run-b"


async def test_sweep_starts_a_run_whose_holder_died(svc, lease, redis, queue, clock):
    assert (await svc.claim_or_wait(CID, "run-dead", "planned", item("sv-dead"))).held
    assert not (await svc.claim_or_wait(CID, "run-b", "planned", item("sv-b"))).held

    # The holder is alive: the sweep changes nothing.
    assert await svc.sweep_pending() == 0
    assert queue.items == [] and queue.expired == []

    # The holder's process is gone and nobody opens the conversation.
    clock.now += rl.LEASE_SECONDS + 1
    assert await svc.sweep_pending() == 1

    assert queue.expired == [(CID, "run-dead")]
    assert queue.items == [{**item("sv-b"), "run_id": "run-b"}]
    assert (await lease.get_state(CID)).run_id == "run-b"
    # Nothing waits any more: the next sweep drops the index entry.
    assert await svc.sweep_pending() == 0
    assert await redis.scard(rd.PENDING_INDEX_KEY) == 0


async def test_promote_after_a_release_that_skipped_the_finish_script(svc, lease, redis, queue):
    assert (await svc.claim_or_wait(CID, "run-a", "planned", item("sv-a"))).held
    assert not (await svc.claim_or_wait(CID, "run-b", "planned", item("sv-b"))).held

    # Running: nothing to promote.
    assert await svc.promote_pending(CID) is None
    assert await lease.release(CID, "run-a")

    promoted = await svc.promote_pending(CID)

    assert promoted is not None and promoted.run_id == "run-b"
    assert queue.items == [{**item("sv-b"), "run_id": "run-b"}]
    assert (await lease.get_state(CID)).run_id == "run-b"


async def test_failed_enqueue_keeps_the_waiting_run(svc, lease, redis, queue):
    assert (await svc.claim_or_wait(CID, "run-a", "planned", item("sv-a"))).held
    assert not (await svc.claim_or_wait(CID, "run-b", "planned", item("sv-b"))).held
    queue.fail_items = True

    with pytest.raises(RuntimeError):
        await svc.on_run_finished(CID, "run-a")

    # The item is back at the head of the list and the conversation is free, not
    # reserved for a run nobody will start.
    assert await _pending(redis) == [{**item("sv-b"), "run_id": "run-b"}]
    assert (await lease.get_state(CID)).status == rl.STATUS_IDLE

    # The worker queue is back: the sweep starts the run.
    queue.fail_items = False
    assert await svc.sweep_pending() == 1
    assert queue.items == [{**item("sv-b"), "run_id": "run-b"}]


async def test_service_without_a_worker_queue_does_not_lose_the_waiting_run(redis, clock, queue, lease):
    bare = RunDispatchService(redis, clock=clock, enqueue_relay=queue.enqueue_relay)
    assert (await bare.claim_or_wait(CID, "run-a", "planned", item("sv-a"))).held
    assert not (await bare.claim_or_wait(CID, "run-b", "planned", item("sv-b"))).held

    with pytest.raises(RuntimeError):
        await bare.on_run_finished(CID, "run-a")

    assert await _pending(redis) == [{**item("sv-b"), "run_id": "run-b"}]


# ---------------------------------------------------------------- item 6: stop


async def test_discarded_inbox_starts_no_relay_run(svc, lease, redis, queue):
    first = await svc.submit(CID, msg("第一条"))
    queued = await svc.submit(CID, msg("还没被读到的一条", task_mode=False))
    assert queued.disposition == "queued"

    removed = await svc.discard_inbox(CID)
    finished = await svc.on_run_finished(CID, first.run_id)

    assert [message["message_id"] for message in removed] == [queued.message_id]
    assert rd.unread_view(removed) == [{"message_id": queued.message_id, "text": "还没被读到的一条", "files": []}]
    assert finished.outcome == rd.OUTCOME_IDLE
    assert queue.relays == []
    assert await svc.inbox_length(CID) == 0


async def test_message_sent_after_the_discard_still_gets_a_run(svc, lease, redis, queue):
    first = await svc.submit(CID, msg("第一条"))
    await svc.submit(CID, msg("停止前发的"))
    await svc.discard_inbox(CID)
    # Sent after the stop was processed, before the run released the conversation.
    late = await svc.submit(CID, msg("停止后发的"))

    finished = await svc.on_run_finished(CID, first.run_id)

    assert finished.outcome == rd.OUTCOME_RELAY
    assert queue.relays[0]["message_id"] == late.message_id
