"""F004 per-conversation run state: short lease, renew, park, stop flag.

Design: features/v3.1.0-beta2/004-unified-agent-runtime/design.md, 决策 3 / 决策 9.
All run state lives in Redis (constitution C8); nothing is kept in process
memory, so any API node or worker sees the same state (AC-33).

Redis contract (also read and written by the Lua scripts in ``run_dispatch``)
-----------------------------------------------------------------------------

``bisheng:run:state:{<conversation_id>}`` -- HASH, one per conversation.
The literal braces are the Redis Cluster hash tag (design K8): every key of one
conversation (state, inbox, events, snapshot) carries the same ``{<cid>}`` so a
Lua script may touch them together.

    status          "idle" | "running" | "waiting".  A missing key or missing
                    field means "idle".
    run_id          id of the run holding the conversation ("" when idle).
                    Kept while "waiting": the answer resumes that same run.
    profile         "direct" | "planned" ("" when idle).
    lease_until     lease deadline, integer epoch MILLISECONDS, decimal string.
                    "0" when idle or waiting (a parked run holds no lease,
                    AC-22).  The lease is valid iff status == "running" and
                    lease_until > now_ms.
    updated_at      epoch milliseconds of the last write (diagnostics only).

    The whole hash gets ``EXPIRE STATE_TTL_SECONDS`` on every write, so an
    abandoned conversation does not leak keys.  Lua scripts that write the hash
    must refresh the same TTL.

    Time is the CALLER's clock, passed into every script as ARGV ``now_ms``
    (never Redis ``TIME``), so all writers agree on one time base and tests can
    inject a clock.  Nodes are assumed NTP-synchronised; the 30 s lease leaves
    ample margin for ordinary skew.

    Lease rules: LEASE_SECONDS = 30; the running coroutine renews every
    RENEW_INTERVAL_SECONDS = 10.  A lapsed lease cannot be renewed: once
    expired, another caller may already have marked the run failed (决策 3).

``bisheng:run:stop:{<run_id>}`` -- STRING "1", TTL STOP_FLAG_TTL_SECONDS.
    Stop request for one run, polled once a second by the running coroutine
    (AC-29).  Keyed by run id because ``should_stop(run_id)`` has only the run
    id; it is never touched by a multi-key Lua script, so its own hash tag is
    safe on Cluster.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from loguru import logger

STATE_KEY_PREFIX = "bisheng:run:state:"
STOP_KEY_PREFIX = "bisheng:run:stop:"

FIELD_STATUS = "status"
FIELD_RUN_ID = "run_id"
FIELD_PROFILE = "profile"
FIELD_LEASE_UNTIL = "lease_until"
FIELD_UPDATED_AT = "updated_at"

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_WAITING = "waiting"

LEASE_SECONDS = 30
RENEW_INTERVAL_SECONDS = 10
STOP_FLAG_TTL_SECONDS = 60 * 60
# Long enough to keep a run parked on ask_user across a weekend.
STATE_TTL_SECONDS = 7 * 24 * 60 * 60


def state_key(conversation_id: str) -> str:
    return f"{STATE_KEY_PREFIX}{{{conversation_id}}}"


def stop_key(run_id: str) -> str:
    return f"{STOP_KEY_PREFIX}{{{run_id}}}"


# KEYS[1]=state  ARGV: run_id, profile, now_ms, lease_ms, state_ttl
# Returns {acquired(0/1), status_before, run_id_before, expired_run_id}
_ACQUIRE_LUA = """
local st = redis.call('HMGET', KEYS[1], 'status', 'run_id', 'lease_until')
local status = st[1] or 'idle'
local holder = st[2] or ''
local lease_until = tonumber(st[3] or '0') or 0
local now = tonumber(ARGV[3])
local expired = ''
if status == 'running' then
  if lease_until > now then
    return {0, status, holder, ''}
  end
  expired = holder
elseif status == 'waiting' then
  if holder ~= ARGV[1] then
    return {0, status, holder, ''}
  end
end
redis.call('HSET', KEYS[1], 'status', 'running', 'run_id', ARGV[1], 'profile', ARGV[2],
  'lease_until', tostring(now + tonumber(ARGV[4])), 'updated_at', ARGV[3])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[5]))
return {1, status, holder, expired}
"""

# KEYS[1]=state  ARGV: run_id, now_ms, lease_ms, state_ttl
_RENEW_LUA = """
local st = redis.call('HMGET', KEYS[1], 'status', 'run_id', 'lease_until')
local now = tonumber(ARGV[2])
if st[1] ~= 'running' or st[2] ~= ARGV[1] or (tonumber(st[3] or '0') or 0) <= now then
  return 0
end
redis.call('HSET', KEYS[1], 'lease_until', tostring(now + tonumber(ARGV[3])), 'updated_at', ARGV[2])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[4]))
return 1
"""

# KEYS[1]=state  ARGV: run_id, now_ms, state_ttl, required_status
_RELEASE_LUA = """
local st = redis.call('HMGET', KEYS[1], 'status', 'run_id')
if st[2] ~= ARGV[1] or (ARGV[4] ~= '' and st[1] ~= ARGV[4]) then
  return 0
end
redis.call('HSET', KEYS[1], 'status', 'idle', 'run_id', '', 'profile', '', 'lease_until', '0',
  'updated_at', ARGV[2])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
return 1
"""

# KEYS[1]=state  ARGV: run_id, now_ms, state_ttl
_PARK_LUA = """
local st = redis.call('HMGET', KEYS[1], 'status', 'run_id')
if st[1] ~= 'running' or st[2] ~= ARGV[1] then
  return 0
end
redis.call('HSET', KEYS[1], 'status', 'waiting', 'lease_until', '0', 'updated_at', ARGV[2])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
return 1
"""


def _s(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


@dataclass(frozen=True)
class RunState:
    status: str
    run_id: str | None
    profile: str | None
    lease_until_ms: int


@dataclass(frozen=True)
class AcquireResult:
    acquired: bool
    # State seen before the call (status, run id of the then-holder).
    status: str
    run_id: str | None
    # Set when this call took over a "running" state whose lease had lapsed;
    # the caller must mark that run failed and emit run_failed (决策 3).
    expired_run_id: str | None


@dataclass(frozen=True)
class StopResult:
    # True when the run was parked ("waiting") and the conversation was set
    # back to idle by this call; no coroutine exists to observe the flag.
    parked_run_released: bool


class RunLeaseService:
    """Per-conversation run lease backed by Redis.

    ``redis`` is a redis-py asyncio client (``RedisClient.async_connection`` in
    production, ``fakeredis.aioredis.FakeRedis`` in tests).  ``clock`` returns
    epoch seconds.
    """

    def __init__(self, redis: Any, clock: Callable[[], float] = time.time):
        self._redis = redis
        self._clock = clock

    @classmethod
    async def create(cls) -> RunLeaseService:
        from bisheng.core.cache.redis_manager import get_redis_client

        client = await get_redis_client()
        return cls(redis=client.async_connection)

    def _now_ms(self) -> int:
        return int(self._clock() * 1000)

    async def get_state(self, conversation_id: str) -> RunState:
        raw = await self._redis.hmget(
            state_key(conversation_id), FIELD_STATUS, FIELD_RUN_ID, FIELD_PROFILE, FIELD_LEASE_UNTIL
        )
        status = _s(raw[0]) or STATUS_IDLE
        return RunState(
            status=status,
            run_id=_s(raw[1]) or None,
            profile=_s(raw[2]) or None,
            lease_until_ms=int(_s(raw[3]) or 0),
        )

    async def is_lease_valid(self, conversation_id: str) -> bool:
        state = await self.get_state(conversation_id)
        return state.status == STATUS_RUNNING and state.lease_until_ms > self._now_ms()

    async def acquire(self, conversation_id: str, run_id: str, profile: str) -> AcquireResult:
        """Take the conversation for ``run_id``.

        Succeeds when idle, when running with a lapsed lease (takeover), or when
        waiting on this same ``run_id`` (resume after the user's answer).
        """
        res = await self._redis.eval(
            _ACQUIRE_LUA,
            1,
            state_key(conversation_id),
            run_id,
            profile,
            self._now_ms(),
            LEASE_SECONDS * 1000,
            STATE_TTL_SECONDS,
        )
        acquired = int(res[0]) == 1
        expired = _s(res[3]) or None
        if expired:
            logger.warning(
                "run lease of run={} on conversation={} had lapsed; taken over by run={}",
                expired,
                conversation_id,
                run_id,
            )
        return AcquireResult(
            acquired=acquired,
            status=_s(res[1]) or STATUS_IDLE,
            run_id=_s(res[2]) or None,
            expired_run_id=expired,
        )

    async def renew(self, conversation_id: str, run_id: str) -> bool:
        """Extend the lease by LEASE_SECONDS. False = the lease is lost."""
        res = await self._redis.eval(
            _RENEW_LUA,
            1,
            state_key(conversation_id),
            run_id,
            self._now_ms(),
            LEASE_SECONDS * 1000,
            STATE_TTL_SECONDS,
        )
        return int(res) == 1

    async def release(self, conversation_id: str, run_id: str) -> bool:
        """Return the conversation to idle if ``run_id`` still holds it."""
        res = await self._redis.eval(
            _RELEASE_LUA, 1, state_key(conversation_id), run_id, self._now_ms(), STATE_TTL_SECONDS, ""
        )
        return int(res) == 1

    async def park(self, conversation_id: str, run_id: str) -> bool:
        """Running -> waiting for the user's answer; the lease is dropped (AC-22)."""
        res = await self._redis.eval(
            _PARK_LUA, 1, state_key(conversation_id), run_id, self._now_ms(), STATE_TTL_SECONDS
        )
        return int(res) == 1

    async def request_stop(self, run_id: str, conversation_id: str | None = None) -> StopResult:
        """Set the stop flag of ``run_id``.

        When ``conversation_id`` is given and that run is parked ("waiting"),
        the conversation is also set back to idle, since no coroutine is alive
        to see the flag.
        """
        await self._redis.set(stop_key(run_id), "1", ex=STOP_FLAG_TTL_SECONDS)
        released = False
        if conversation_id:
            res = await self._redis.eval(
                _RELEASE_LUA,
                1,
                state_key(conversation_id),
                run_id,
                self._now_ms(),
                STATE_TTL_SECONDS,
                STATUS_WAITING,
            )
            released = int(res) == 1
        logger.info("stop requested for run={} conversation={} parked_released={}", run_id, conversation_id, released)
        return StopResult(parked_run_released=released)

    async def should_stop(self, run_id: str) -> bool:
        return bool(await self._redis.exists(stop_key(run_id)))

    async def renew_loop(
        self,
        conversation_id: str,
        run_id: str,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> bool:
        """Renew every RENEW_INTERVAL_SECONDS until the lease is lost.

        Returns True when the lease was lost (released, parked, taken over or
        lapsed).  The caller cancels this task when the run ends normally.
        """
        while True:
            await sleep(RENEW_INTERVAL_SECONDS)
            if not await self.renew(conversation_id, run_id):
                logger.info("run lease lost for run={} conversation={}", run_id, conversation_id)
                return True
