"""F004 send entry: decide atomically whether a message starts a run or joins the inbox.

Design: features/v3.1.0-beta2/004-unified-agent-runtime/design.md, 决策 9 (and
决策 3 for the lapsed lease). The decision runs as one Lua script
(``run_dispatch.lua``) so that a message is either read by the current run or
starts a new one (AC-17), on any node (AC-33).

This module decides; it does NOT execute agents. ``submit`` returns the
disposition and, for a new run, what the caller needs to start it.

Redis contract
--------------

``bisheng:run:state:{<cid>}`` -- owned by ``run_lease.py`` (same fields, same
TTL, same "caller's clock" rule).

``bisheng:run:inbox:{<cid>}`` -- LIST, oldest message first. Each element is a
JSON object with exactly ``INBOX_FIELDS``. The first message of a run is the
run's input and never enters the inbox; only messages sent while a run holds
the conversation do.

Branches of ``submit`` (``SubmitResult.kind``)
----------------------------------------------

* ``new_run``  idle -> the conversation is taken for a new ``run_id``;
  disposition ``started``. The caller starts the run. The state already says
  "running" with a lease, so the runner must use ``RunLeaseService.renew`` /
  ``renew_loop`` and must NOT call ``acquire`` again.
* ``steer``    running with a valid lease -> the message is appended to the
  inbox; disposition ``queued``; ``run_id`` is the running run.
* ``answer``   waiting for the user's answer -> the message is the answer;
  disposition ``started``; ``run_id`` is the parked run, which takes the lease
  back inside the script. The caller resumes that run with the message text.
* running with a lapsed lease -> the old run is reported through
  ``on_run_expired`` (mark it failed, emit ``run_failed``), then the idle rule
  applies. ``SubmitResult.expired_run_id`` names the old run.
* ``relay``    idle but the inbox still holds unread messages (the run that
  should have read them died). Those messages are older than the new one, so
  the new message joins the inbox behind them and ONE relay run is handed to
  the worker queue; disposition ``queued``.

Leases: a run that executes right away (``direct``) gets ``LEASE_SECONDS``. A
run that first waits in the worker queue (``planned``, and every relay run)
gets ``QUEUED_LEASE_SECONDS``; the worker that picks it up calls ``renew`` and
from then on keeps the normal 30 s lease.

Finish: the runner calls ``on_run_finished`` (not ``RunLeaseService.release``)
when a run ends for any reason. One Lua script sets the conversation idle, or,
when the inbox is not empty, hands the conversation straight to a relay run
whose profile comes from the FIRST inbox message. The relay item goes to the
worker queue through the injected ``enqueue_relay`` and carries ``tenant_id``.
The inbox is left intact: the relay run reads it (``drain_inbox`` or the inbox
middleware), so a lost queue item loses no message.

Waiting runs (design §7 item 4)
-------------------------------

``bisheng:run:pending:{<cid>}`` -- LIST of worker-queue items (JSON, each with
``run_id``), oldest first. A deep-research run submitted through an entry that
does not go through ``submit`` (Open API task mode, ``/workbench/start-execute``)
reaches the worker while another run holds the conversation: ``claim_or_wait``
either gives it the conversation or appends its queue item here, in one script.
The finish script hands the conversation to the first waiting item when the
inbox is empty (outcome ``pending``) and the item returns to the worker queue
through ``enqueue_item``. Paths that free a conversation without the finish
script call ``promote_pending``.

``bisheng:run:pending_index`` -- SET of conversation ids that have (or had)
waiting items. Not hash-tagged and never used inside a script. The worker's
``sweep_pending`` walks it, so a waiting run whose holder died is still started
after the holder's lease lapsed, without anyone opening the conversation.

Stop (design §7 item 6)
-----------------------

A run that ends because the user stopped it does not relay: the runner calls
``discard_inbox`` before it writes ``run_stopped`` and puts the removed
messages into that event. A message that arrives after that call was sent
after the stop and starts a relay run as usual.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from bisheng.workstation.domain.services.run_lease import LEASE_SECONDS, STATE_TTL_SECONDS, state_key

INBOX_KEY_PREFIX = "bisheng:run:inbox:"
PENDING_KEY_PREFIX = "bisheng:run:pending:"
PENDING_INDEX_KEY = "bisheng:run:pending_index"
# Same lifetime as the state hash: an inbox must not outlive or die before it.
INBOX_TTL_SECONDS = STATE_TTL_SECONDS
# Lease of a run that sits in the worker queue before a worker renews it. Same
# bound as the 4-hour run lock it replaces: a deep-research run may wait behind
# other runs for a long time, and its queue item is not lost while it waits.
QUEUED_LEASE_SECONDS = 4 * 60 * 60

INBOX_FIELDS = (
    "message_id",
    "text",
    "task_mode",
    "tools",
    "skills",
    "knowledge",
    "files",
    "user_id",
    "tenant_id",
    "ts",
)

PROFILE_DIRECT = "direct"
PROFILE_PLANNED = "planned"

DISPOSITION_STARTED = "started"
DISPOSITION_QUEUED = "queued"

KIND_NEW_RUN = "new_run"
KIND_STEER = "steer"
KIND_ANSWER = "answer"
KIND_RELAY = "relay"

OUTCOME_IDLE = "idle"
OUTCOME_RELAY = "relay"
OUTCOME_STALE = "stale"
OUTCOME_PENDING = "pending"

# ``reason`` of the run_failed event emitted for a run whose lease lapsed.
EXPIRED_REASON = "lease_expired"

EnqueueRelay = Callable[[dict], Awaitable[None]]
# Puts the queue item of a run that waited for the conversation back into the worker queue.
EnqueueItem = Callable[[dict], Awaitable[None]]
OnRunExpired = Callable[[str, str], Awaitable[None]]
QueuePosition = Callable[[str, str, dict], Awaitable[int | None]]
# ``on_queued(result, message)``: persist the question row of a message that joined the inbox.
OnQueued = Callable[["SubmitResult", dict], Awaitable[None]]


def inbox_key(conversation_id: str) -> str:
    return f"{INBOX_KEY_PREFIX}{{{conversation_id}}}"


def pending_key(conversation_id: str) -> str:
    return f"{PENDING_KEY_PREFIX}{{{conversation_id}}}"


def unread_view(messages: list[dict]) -> list[dict]:
    """Inbox messages as the client gets them back after a stop (``unread_messages``)."""
    return [
        {
            "message_id": str(message.get("message_id") or ""),
            "text": message.get("text") or "",
            "files": message.get("files") or [],
        }
        for message in messages
    ]


def profile_of(message: dict) -> str:
    return PROFILE_PLANNED if message.get("task_mode") is True else PROFILE_DIRECT


def _load_scripts() -> dict[str, str]:
    """Split run_dispatch.lua into its named scripts (``-- @@script <name>``)."""
    scripts: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in (Path(__file__).parent / "run_dispatch.lua").read_text(encoding="utf-8").splitlines():
        if line.startswith("-- @@script "):
            current = scripts.setdefault(line[len("-- @@script ") :].strip(), [])
            continue
        if current is not None:
            current.append(line)
    return {name: "\n".join(lines) for name, lines in scripts.items()}


_SCRIPTS = _load_scripts()
_DISPATCH_LUA = _SCRIPTS["dispatch"]
_FINISH_LUA = _SCRIPTS["finish"]
_CLAIM_LUA = _SCRIPTS["claim"]
_PROMOTE_LUA = _SCRIPTS["promote"]


def _s(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


@dataclass(frozen=True)
class SubmitResult:
    run_id: str
    disposition: str
    message_id: str
    kind: str
    profile: str
    # Run whose lease had lapsed and was declared dead by this call.
    expired_run_id: str | None = None
    # Inbox length after this call (0 when the message did not enter the inbox).
    inbox_length: int = 0
    # Position in the worker queue when a planned run has no free slot (AC-36).
    queue_position: int | None = None
    # Events the caller must append to the run's event stream after run_started.
    events: list[dict] = field(default_factory=list)
    # Queue item of the relay run started by this call (kind == "relay").
    relay: dict | None = None

    def as_response(self) -> dict:
        """The body of the send endpoint under ``X-BS-Run-Protocol: 2`` (design §4.3)."""
        return {"run_id": self.run_id, "disposition": self.disposition, "message_id": self.message_id}


@dataclass(frozen=True)
class FinishResult:
    outcome: str
    # Relay run id (outcome "relay"), current holder (outcome "stale"), else None.
    run_id: str | None = None
    profile: str | None = None
    relay: dict | None = None
    # Set only by ``recover_expired``.
    expired_run_id: str | None = None
    # Queue item of the waiting run that took the conversation (outcome "pending").
    item: dict | None = None


@dataclass(frozen=True)
class ClaimResult:
    # True: the run holds the conversation. False: its queue item waits in the pending list.
    held: bool
    # Holder seen before the call.
    holder_run_id: str | None = None
    # Run whose lapsed lease this call took over; the caller reports it as failed.
    expired_run_id: str | None = None


class RunDispatchService:
    """Atomic send-entry decision and finish/relay rule for one Redis.

    ``redis`` is a redis-py asyncio client (``RedisClient.async_connection`` in
    production, ``fakeredis.aioredis.FakeRedis`` in tests). ``clock`` returns
    epoch seconds and must be the same clock ``RunLeaseService`` uses.

    ``enqueue_relay(item)`` puts a relay run into the worker queue.
    ``on_run_expired(conversation_id, run_id)`` marks a dead run failed and
    emits ``run_failed``; the default only emits the event.
    ``queue_position(conversation_id, run_id, message)`` returns the queue
    position of a new planned run, or None when a slot is free.
    ``enqueue_item(item)`` puts the queue item of a run that waited for the
    conversation back into the worker queue.
    """

    def __init__(
        self,
        redis: Any,
        clock: Callable[[], float] = time.time,
        *,
        enqueue_relay: EnqueueRelay | None = None,
        on_run_expired: OnRunExpired | None = None,
        queue_position: QueuePosition | None = None,
        enqueue_item: EnqueueItem | None = None,
        run_id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
    ):
        self._redis = redis
        self._clock = clock
        self._enqueue_relay = enqueue_relay
        self._on_run_expired = on_run_expired
        self._queue_position = queue_position
        self._enqueue_item = enqueue_item
        self._new_run_id = run_id_factory

    @classmethod
    async def create(cls, **kwargs: Any) -> RunDispatchService:
        from bisheng.core.cache.redis_manager import get_redis_client

        client = await get_redis_client()
        return cls(redis=client.async_connection, **kwargs)

    def _now_ms(self) -> int:
        return int(self._clock() * 1000)

    # ------------------------------------------------------------------ submit

    def _normalize(self, message: dict) -> dict:
        if message.get("tenant_id") is None:
            raise ValueError("a submitted message must carry tenant_id")
        if message.get("user_id") is None:
            raise ValueError("a submitted message must carry user_id")
        return {
            "message_id": str(message.get("message_id") or uuid.uuid4().hex),
            "text": message.get("text") or "",
            "task_mode": message.get("task_mode") is True,
            "tools": message.get("tools") or [],
            "skills": message.get("skills") or [],
            "knowledge": message.get("knowledge") or [],
            "files": message.get("files") or [],
            "user_id": message["user_id"],
            "tenant_id": message["tenant_id"],
            "ts": int(message.get("ts") or self._now_ms()),
        }

    async def _eval_dispatch(self, conversation_id: str, mode: str, run_id: str, payload: str, profile: str) -> list:
        return await self._redis.eval(
            _DISPATCH_LUA,
            2,
            state_key(conversation_id),
            inbox_key(conversation_id),
            mode,
            run_id,
            payload,
            profile,
            self._now_ms(),
            LEASE_SECONDS * 1000,
            QUEUED_LEASE_SECONDS * 1000,
            STATE_TTL_SECONDS,
            INBOX_TTL_SECONDS,
        )

    async def submit(self, conversation_id: str, message: dict, *, on_queued: OnQueued | None = None) -> SubmitResult:
        """Decide what one sent message does. See the module docstring for the branches.

        Input safety checks (AC-38) are the caller's job and run BEFORE this.

        ``on_queued(result, message)`` is awaited when the message joined the
        inbox (disposition ``queued``), before ``steer_accepted`` is emitted: the
        caller writes the message's question row there (AC-13).
        """
        msg = self._normalize(message)
        profile = profile_of(msg)
        res = await self._eval_dispatch(
            conversation_id, "submit", self._new_run_id(), json.dumps(msg, ensure_ascii=False), profile
        )
        branch, run_id, run_profile = _s(res[0]), _s(res[1]), _s(res[2])
        expired = _s(res[3]) or None
        inbox_length = int(res[4])

        if expired:
            await self._handle_expired(conversation_id, expired)

        if branch == "started":
            position = None
            events: list[dict] = []
            if run_profile == PROFILE_PLANNED and self._queue_position is not None:
                position = await self._queue_position(conversation_id, run_id, msg)
                if position is not None:
                    events.append({"type": "queued", "run_id": run_id, "data": {"position": position}})
            result = SubmitResult(
                run_id=run_id,
                disposition=DISPOSITION_STARTED,
                message_id=msg["message_id"],
                kind=KIND_NEW_RUN,
                profile=run_profile,
                expired_run_id=expired,
                queue_position=position,
                events=events,
            )
        elif branch == "answer":
            result = SubmitResult(
                run_id=run_id,
                disposition=DISPOSITION_STARTED,
                message_id=msg["message_id"],
                kind=KIND_ANSWER,
                profile=run_profile,
                inbox_length=inbox_length,
            )
        elif branch == "queued":
            result = SubmitResult(
                run_id=run_id,
                disposition=DISPOSITION_QUEUED,
                message_id=msg["message_id"],
                kind=KIND_STEER,
                profile=run_profile,
                inbox_length=inbox_length,
            )
            await self._on_message_queued(conversation_id, result, msg, on_queued)
        elif branch == "relay":
            item = self._relay_item(conversation_id, run_id, run_profile, _s(res[5]))
            result = SubmitResult(
                run_id=run_id,
                disposition=DISPOSITION_QUEUED,
                message_id=msg["message_id"],
                kind=KIND_RELAY,
                profile=run_profile,
                expired_run_id=expired,
                inbox_length=inbox_length,
                relay=item,
            )
            await self._on_message_queued(conversation_id, result, msg, on_queued)
            await self._enqueue(conversation_id, item)
        else:
            raise RuntimeError(f"run_dispatch.lua returned an unknown branch: {branch!r}")

        logger.info(
            "run dispatch conversation={} message={} kind={} disposition={} run={} profile={} expired_run={}",
            conversation_id,
            result.message_id,
            result.kind,
            result.disposition,
            result.run_id,
            result.profile,
            expired,
        )
        return result

    async def _on_message_queued(
        self, conversation_id: str, result: SubmitResult, message: dict, on_queued: OnQueued | None
    ) -> None:
        """A message entered the inbox (AC-13): question row first, then ``steer_accepted``.

        The message is already in the inbox and will be read whatever happens
        here, so neither step may fail the send: an error is logged, and the user
        is not told to send the same message again.

        ``steer_accepted`` goes to the stream of the run that holds the
        conversation. A relay run has not written ``run_started`` yet and that
        event clears the stream, so nothing is emitted for it; the row's
        "queued" mark is what a reader of the history sees.
        """
        if on_queued is not None:
            try:
                await on_queued(result, message)
            except Exception:
                logger.exception(
                    "could not save the question row of queued message={} conversation={}",
                    result.message_id,
                    conversation_id,
                )
        if result.kind != KIND_STEER:
            return
        from bisheng.linsight.domain.services.run_event_stream import RunEventStream

        try:
            await RunEventStream(self._redis).append(
                conversation_id,
                {"type": "steer_accepted", "run_id": result.run_id, "data": {"message_id": result.message_id}},
            )
        except Exception:
            logger.exception(
                "could not emit steer_accepted for message={} conversation={}", result.message_id, conversation_id
            )

    # ------------------------------------------------------------------ finish

    async def on_run_finished(self, conversation_id: str, run_id: str | None = None) -> FinishResult:
        """A run ended (finished, failed or stopped): go idle or start the relay run.

        Pass ``run_id`` so a run that lost its lease to a newer run cannot reset
        that newer run's state (outcome ``stale``). Raises when the relay item
        cannot be enqueued; the inbox is kept and the relay lease then lapses,
        so the next access to the conversation recovers it.
        """
        res = await self._redis.eval(
            _FINISH_LUA,
            3,
            state_key(conversation_id),
            inbox_key(conversation_id),
            pending_key(conversation_id),
            run_id or "",
            self._new_run_id(),
            self._now_ms(),
            QUEUED_LEASE_SECONDS * 1000,
            STATE_TTL_SECONDS,
        )
        outcome = _s(res[0])
        if outcome == OUTCOME_IDLE:
            if _s(res[4]):
                logger.error(
                    "conversation={}: a waiting queue item without a run id was dropped: {!r}",
                    conversation_id,
                    _s(res[4]),
                )
            return FinishResult(outcome=OUTCOME_IDLE)
        if outcome == OUTCOME_PENDING:
            waiting_run_id = _s(res[1])
            logger.info(
                "run={} finished on conversation={}; waiting run={} takes the conversation",
                run_id,
                conversation_id,
                waiting_run_id,
            )
            item = await self._enqueue_waiting(conversation_id, waiting_run_id, _s(res[4]))
            return FinishResult(outcome=OUTCOME_PENDING, run_id=waiting_run_id, profile=PROFILE_PLANNED, item=item)
        if outcome == OUTCOME_STALE:
            logger.warning(
                "run={} finished on conversation={} but run={} holds it now; state left untouched",
                run_id,
                conversation_id,
                _s(res[1]),
            )
            return FinishResult(outcome=OUTCOME_STALE, run_id=_s(res[1]) or None)
        if outcome != OUTCOME_RELAY:
            raise RuntimeError(f"run_dispatch.lua finish returned an unknown outcome: {outcome!r}")

        relay_run_id, profile = _s(res[1]), _s(res[2])
        item = self._relay_item(conversation_id, relay_run_id, profile, _s(res[4]))
        logger.info(
            "run={} finished on conversation={} with {} unread message(s); relay run={} profile={}",
            run_id,
            conversation_id,
            int(res[3]),
            relay_run_id,
            profile,
        )
        await self._enqueue(conversation_id, item)
        return FinishResult(outcome=OUTCOME_RELAY, run_id=relay_run_id, profile=profile, relay=item)

    async def recover_expired(self, conversation_id: str) -> FinishResult | None:
        """Handle a lapsed lease when the conversation is accessed without a message.

        Called e.g. when a client subscribes to the events (决策 3). Returns None
        when there is nothing to recover. Otherwise the dead run is reported
        through ``on_run_expired`` and the conversation goes idle, or, with
        unread inbox messages, to a relay run.
        """
        res = await self._eval_dispatch(conversation_id, "recover", self._new_run_id(), "", "")
        branch = _s(res[0])
        if branch == "noop":
            return None
        expired = _s(res[3]) or None
        if expired:
            await self._handle_expired(conversation_id, expired)
        if branch == "idle":
            promoted = await self.promote_pending(conversation_id)
            if promoted is not None:
                return FinishResult(
                    outcome=OUTCOME_PENDING,
                    run_id=promoted.run_id,
                    profile=promoted.profile,
                    item=promoted.item,
                    expired_run_id=expired,
                )
            return FinishResult(outcome=OUTCOME_IDLE, expired_run_id=expired)
        if branch == "relay":
            run_id, profile = _s(res[1]), _s(res[2])
            item = self._relay_item(conversation_id, run_id, profile, _s(res[5]))
            await self._enqueue(conversation_id, item)
            return FinishResult(
                outcome=OUTCOME_RELAY, run_id=run_id, profile=profile, relay=item, expired_run_id=expired
            )
        raise RuntimeError(f"run_dispatch.lua recover returned an unknown branch: {branch!r}")

    # ------------------------------------------------------------ waiting runs

    async def claim_or_wait(self, conversation_id: str, run_id: str, profile: str, item: dict) -> ClaimResult:
        """Take the conversation for a run the worker dequeued, or make the run wait for it.

        ``item`` is the worker-queue item that starts this run again; it is
        stored with ``run_id`` so the conversation can be reserved for it. The
        run holds the conversation when it is idle, reserved for this ``run_id``,
        parked on this ``run_id``, or held by a run whose lease lapsed.
        """
        waiting_item = {**item, "run_id": run_id}
        res = await self._redis.eval(
            _CLAIM_LUA,
            2,
            state_key(conversation_id),
            pending_key(conversation_id),
            run_id,
            profile,
            self._now_ms(),
            LEASE_SECONDS * 1000,
            STATE_TTL_SECONDS,
            json.dumps(waiting_item, ensure_ascii=False),
            INBOX_TTL_SECONDS,
        )
        held = _s(res[0]) == "held"
        holder, expired = _s(res[1]) or None, _s(res[2]) or None
        if not held:
            # After the push: an index entry without a list is removed by the sweep.
            await self._redis.sadd(PENDING_INDEX_KEY, conversation_id)
            logger.info(
                "run={} waits for conversation={} held by run={}; {} run(s) waiting",
                run_id,
                conversation_id,
                holder,
                int(res[3]),
            )
        elif expired:
            logger.warning(
                "run lease of run={} on conversation={} had lapsed; taken over by run={}",
                expired,
                conversation_id,
                run_id,
            )
        return ClaimResult(held=held, holder_run_id=holder, expired_run_id=expired)

    async def promote_pending(self, conversation_id: str) -> FinishResult | None:
        """Give an idle conversation with an empty inbox to its first waiting run.

        Returns None when nothing was started. Call it after a path that frees
        the conversation without ``on_run_finished``.
        """
        res = await self._redis.eval(
            _PROMOTE_LUA,
            3,
            state_key(conversation_id),
            inbox_key(conversation_id),
            pending_key(conversation_id),
            self._now_ms(),
            QUEUED_LEASE_SECONDS * 1000,
            STATE_TTL_SECONDS,
        )
        outcome = _s(res[0])
        if outcome == "dropped":
            logger.error(
                "conversation={}: a waiting queue item without a run id was dropped: {!r}", conversation_id, _s(res[2])
            )
            return None
        if outcome != OUTCOME_PENDING:
            return None
        run_id = _s(res[1])
        item = await self._enqueue_waiting(conversation_id, run_id, _s(res[2]))
        return FinishResult(outcome=OUTCOME_PENDING, run_id=run_id, profile=PROFILE_PLANNED, item=item)

    async def pending_length(self, conversation_id: str) -> int:
        return int(await self._redis.llen(pending_key(conversation_id)))

    async def sweep_pending(self) -> int:
        """Start waiting runs whose conversation was freed without the finish script.

        Walks ``PENDING_INDEX_KEY``: a lapsed lease is reported
        (``recover_expired``), then an idle conversation goes to its first
        waiting run. Returns how many runs were started. One conversation that
        fails does not stop the sweep.
        """
        started = 0
        for raw in await self._redis.smembers(PENDING_INDEX_KEY):
            conversation_id = _s(raw)
            try:
                if await self._redis.llen(pending_key(conversation_id)) == 0:
                    await self._redis.srem(PENDING_INDEX_KEY, conversation_id)
                    # A run may have started waiting between the two commands.
                    if await self._redis.llen(pending_key(conversation_id)) > 0:
                        await self._redis.sadd(PENDING_INDEX_KEY, conversation_id)
                    continue
                recovered = await self.recover_expired(conversation_id)
                if recovered is not None and recovered.outcome == OUTCOME_PENDING:
                    started += 1
                    continue
                if await self.promote_pending(conversation_id) is not None:
                    started += 1
            except Exception:
                logger.exception("pending sweep failed for conversation={}", conversation_id)
        return started

    async def _enqueue_waiting(self, conversation_id: str, run_id: str, item_json: str) -> dict:
        """Put the queue item of the run that now holds the conversation into the worker queue.

        When that fails the item goes back to the head of the pending list and
        the conversation is freed, so the sweep starts the run later; the error
        is raised.
        """
        item = json.loads(item_json)
        try:
            if self._enqueue_item is None:
                raise RuntimeError("RunDispatchService was built without enqueue_item")
            await self._enqueue_item(item)
        except Exception:
            logger.exception(
                "could not enqueue waiting run={} of conversation={}; it stays in the pending list",
                run_id,
                conversation_id,
            )
            from bisheng.workstation.domain.services.run_lease import RunLeaseService

            await self._redis.lpush(pending_key(conversation_id), item_json)
            await self._redis.expire(pending_key(conversation_id), INBOX_TTL_SECONDS)
            await self._redis.sadd(PENDING_INDEX_KEY, conversation_id)
            await RunLeaseService(self._redis, clock=self._clock).release(conversation_id, run_id)
            raise
        return item

    # ------------------------------------------------------------------- inbox

    async def drain_inbox(self, conversation_id: str) -> list[dict]:
        """Take every inbox message, oldest first, exactly once (AC-16)."""
        key = inbox_key(conversation_id)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.lrange(key, 0, -1)
            pipe.delete(key)
            raw, _ = await pipe.execute()
        return [json.loads(_s(item)) for item in raw]

    async def discard_inbox(self, conversation_id: str) -> list[dict]:
        """Take the unread messages of a run the user stopped (design §7 item 6).

        Same atomic take as ``drain_inbox``; the caller returns the messages to
        the client instead of giving them to a run.
        """
        messages = await self.drain_inbox(conversation_id)
        if messages:
            logger.info(
                "conversation={}: {} unread message(s) removed from the inbox on stop: {}",
                conversation_id,
                len(messages),
                [message.get("message_id") for message in messages],
            )
        return messages

    async def inbox_length(self, conversation_id: str) -> int:
        return int(await self._redis.llen(inbox_key(conversation_id)))

    # ----------------------------------------------------------------- helpers

    @staticmethod
    def _relay_item(conversation_id: str, run_id: str, profile: str, head_json: str) -> dict:
        """Worker-queue item of a relay run; settings come from the first inbox message."""
        head = json.loads(head_json)
        return {
            "conversation_id": conversation_id,
            "run_id": run_id,
            "profile": profile,
            "relay": True,
            "tenant_id": head["tenant_id"],
            "user_id": head["user_id"],
            "message_id": head["message_id"],
            "task_mode": head.get("task_mode") is True,
            "tools": head.get("tools") or [],
            "skills": head.get("skills") or [],
            "knowledge": head.get("knowledge") or [],
            "files": head.get("files") or [],
        }

    async def _enqueue(self, conversation_id: str, item: dict) -> None:
        if self._enqueue_relay is None:
            raise RuntimeError(
                f"relay run {item['run_id']} of conversation {conversation_id} needs a worker queue, "
                "but RunDispatchService was built without enqueue_relay"
            )
        try:
            await self._enqueue_relay(item)
        except Exception:
            logger.exception(
                "could not enqueue relay run={} of conversation={}; the inbox is kept and the relay lease will lapse",
                item["run_id"],
                conversation_id,
            )
            raise

    async def _handle_expired(self, conversation_id: str, run_id: str) -> None:
        logger.warning("run={} on conversation={} lost its lease; marking it failed", run_id, conversation_id)
        if self._on_run_expired is not None:
            await self._on_run_expired(conversation_id, run_id)
            return
        # Default: only the event. Marking the run's database record failed needs
        # the run record, which the caller wires in through on_run_expired.
        from bisheng.linsight.domain.services.run_event_stream import RunEventStream

        await RunEventStream(self._redis).append(
            conversation_id,
            {
                "type": "run_failed",
                "run_id": run_id,
                "data": {
                    "code": None,
                    "reason": EXPIRED_REASON,
                    "detail": "The run stopped renewing its lease; the process that executed it is gone.",
                    "reference_id": run_id,
                },
            },
        )
