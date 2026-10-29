"""Department-scoped concurrent-session leases.

One Redis sorted set per department; every online session is a lease whose
score is its expiry time in milliseconds. A holder keeps its lease alive by
re-asserting it every ``RENEW_INTERVAL_S``; a holder that disappears simply
stops renewing and its lease is swept by the next "ensure" that touches the
key. There is no background sweeper and no cleanup at instance start — all
instances share one counter, so a startup sweep would drop other instances'
live sessions.

This module is intentionally small because it sits on the workstation import
path. Keep imports lightweight and avoid depending on workstation services.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum

from loguru import logger

from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.database.models.department import DepartmentDao, UserDepartmentDao

# Lease lifetime. Browsers throttle background-tab timers (Chrome clamps a
# hidden tab's chained timers to once per minute after 5 minutes), so the TTL
# has to stay above that to avoid dropping a live page.
LEASE_TTL_MS = 120_000
RENEW_INTERVAL_S = 30

_LEASE_ID_RE = re.compile(r"^[0-9a-fA-F]{32}$")

# Request header carrying the page lease on the workbench SSE and the linsight
# submit stream. WebSocket connections pass ``flow_lease_id`` as a query
# parameter instead (browsers cannot set WS headers).
PAGE_LEASE_HEADER = "X-Flow-Lease-Id"


class SlotOutcome(str, Enum):
    """Result of a lease operation.

    All three members are truthy strings — compare against the member, never
    write ``if not outcome``.
    """

    HELD = "held"  # Lease is in Redis
    REJECTED = "rejected"  # Department is full
    SKIPPED = "skipped"  # No limit configured, or Redis unavailable


@dataclass(frozen=True)
class SlotLease:
    """One held lease. Only returned for ``SlotOutcome.HELD``."""

    department_id: int
    user_id: int
    lease_id: str


def normalize_lease_id(value: str | None) -> str | None:
    """Return ``value`` when it is a 32-hex lease id, else ``None``.

    Callers treat ``None`` as "no page lease was supplied". Both
    ``generateUUID(32)`` and ``uuid4().hex`` are lowercase; accepting either
    case avoids dropping a legitimate page lease.
    """
    if not isinstance(value, str) or not value:
        return None
    candidate = value.strip()
    if _LEASE_ID_RE.match(candidate):
        return candidate
    return None


def lease_id_from_headers(headers) -> str | None:
    """Read the page lease id off a request's headers.

    Tolerates ``headers`` being absent or not a real mapping (tests pass plain
    objects) — anything unusable reads as "no page lease supplied".
    """
    if not hasattr(headers, "get"):
        return None
    return normalize_lease_id(headers.get(PAGE_LEASE_HEADER))


def _lease_key(department_id: int) -> str:
    return f"bisheng:dept_flow:{int(department_id)}:leases"


def _member(user_id: int, lease_id: str) -> str:
    return f"{int(user_id)}:{lease_id}"


# TIME is read inside the script so clock skew between instances cannot make a
# live lease look expired. Calling TIME before a write requires Redis 5+.
_ENSURE_SCRIPT = """
local key = KEYS[1]
local member = ARGV[1]
local limit = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])

local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)

redis.call('ZREMRANGEBYSCORE', key, '-inf', now)

if redis.call('ZSCORE', key, member) then
  redis.call('ZADD', key, now + ttl, member)
  redis.call('PEXPIRE', key, ttl * 2)
  return 1
end

if redis.call('ZCARD', key) >= limit then
  return 0
end

redis.call('ZADD', key, now + ttl, member)
redis.call('PEXPIRE', key, ttl * 2)
return 1
"""

_RELEASE_SCRIPT = """
local key = KEYS[1]
local member = ARGV[1]
local removed = redis.call('ZREM', key, member)
if redis.call('ZCARD', key) == 0 then
  redis.call('DEL', key)
end
return removed
"""


class DepartmentFlowService:
    """Resolve and enforce department concurrent-session leases."""

    # ------------------------------------------------------------------ limit

    @classmethod
    async def resolve_limit_and_dept(cls, login_user) -> tuple[int, int | None]:
        """Return ``(limit, department_id)`` for the user's own primary department.

        Only the primary department's own ``concurrent_session_limit`` counts.
        ``0`` means "no limit", and ancestors are never consulted: a parent's
        limit does not apply to a user whose own department has none.
        """
        try:
            primary = await UserDepartmentDao.aget_user_primary_department(
                int(login_user.user_id),
            )
            if primary is None:
                return 0, None

            dept = await DepartmentDao.aget_by_id(int(primary.department_id))
            if dept is None:
                return 0, None
            limit = int(getattr(dept, "concurrent_session_limit", 0) or 0)
            if limit <= 0:
                return 0, None
            return limit, int(dept.id)
        except Exception as exc:
            logger.warning(
                "Failed to resolve department session limit for user=%s: %s",
                getattr(login_user, "user_id", None),
                exc,
            )
        return 0, None

    # ------------------------------------------------------------------ leases

    @classmethod
    async def ensure_lease(
        cls,
        login_user,
        lease_id: str | None = None,
    ) -> tuple[SlotOutcome, SlotLease | None]:
        """Acquire or renew a lease for the user's primary department.

        Used by page heartbeats and by execution entry points. A lease that
        already expired is simply re-acquired against the current head count —
        "disconnected means queue again".
        """
        limit, department_id = await cls.resolve_limit_and_dept(login_user)
        if limit <= 0 or department_id is None:
            return SlotOutcome.SKIPPED, None

        user_id = int(login_user.user_id)
        resolved_lease_id = lease_id or uuid.uuid4().hex
        lease = SlotLease(
            department_id=department_id,
            user_id=user_id,
            lease_id=resolved_lease_id,
        )
        outcome = await cls._ensure_on_key(lease, limit)
        if outcome is SlotOutcome.HELD:
            return SlotOutcome.HELD, lease
        return outcome, None

    @classmethod
    async def renew_lease(cls, lease: SlotLease) -> SlotOutcome:
        """Renew an *execution* lease on the department it was taken in.

        Deliberately does not re-resolve the user's primary department: if the
        user is moved mid-session, re-resolving would take a second lease in
        the new department while ``release_lease`` only removes the old one.
        """
        try:
            dept = await DepartmentDao.aget_by_id(int(lease.department_id))
            limit = int(getattr(dept, "concurrent_session_limit", 0) or 0) if dept else 0
        except Exception as exc:
            logger.warning(
                "Failed to resolve department limit while renewing, dept=%s user=%s: %s",
                lease.department_id,
                lease.user_id,
                exc,
            )
            return SlotOutcome.SKIPPED
        if limit <= 0:
            return SlotOutcome.SKIPPED
        return await cls._ensure_on_key(lease, limit)

    @classmethod
    async def release_lease(cls, lease: SlotLease) -> None:
        """Drop one lease. Missing entries are not an error; never goes negative."""
        if not normalize_lease_id(lease.lease_id):
            return
        try:
            redis = await get_redis_client()
            await redis.async_connection.eval(
                _RELEASE_SCRIPT,
                1,
                _lease_key(lease.department_id),
                _member(lease.user_id, lease.lease_id),
            )
        except Exception as exc:
            logger.warning(
                "Failed to release department session lease, dept=%s user=%s: %s",
                lease.department_id,
                lease.user_id,
                exc,
            )

    @classmethod
    async def _ensure_on_key(cls, lease: SlotLease, limit: int) -> SlotOutcome:
        try:
            redis = await get_redis_client()
            result = await redis.async_connection.eval(
                _ENSURE_SCRIPT,
                1,
                _lease_key(lease.department_id),
                _member(lease.user_id, lease.lease_id),
                int(limit),
                LEASE_TTL_MS,
            )
            if int(result) == 1:
                return SlotOutcome.HELD
            return SlotOutcome.REJECTED
        except Exception as exc:
            # Traffic control must never take chat down.
            logger.warning(
                "Failed to ensure department session lease, dept=%s user=%s: %s",
                lease.department_id,
                lease.user_id,
                exc,
            )
            return SlotOutcome.SKIPPED

    # ----------------------------------------------------------------- renewal

    @classmethod
    def start_renewal(cls, lease: SlotLease) -> asyncio.Task:
        """Start a background renewal task for a held lease."""
        return asyncio.create_task(cls._renew_loop(lease))

    @classmethod
    async def stop_renewal(cls, task: asyncio.Task | None, lease: SlotLease | None) -> None:
        """Cancel the renewal task, then release the lease.

        Cancelling before releasing matters: a renewal racing with the release
        would put the member back after it was removed.
        """
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if lease is not None:
            await cls.release_lease(lease)

    @classmethod
    async def _renew_loop(cls, lease: SlotLease) -> None:
        while True:
            await asyncio.sleep(RENEW_INTERVAL_S)
            # A rejected renewal does not abort the in-flight request: the
            # session keeps running, it just stops occupying a slot.
            await cls.renew_lease(lease)

    # ------------------------------------------------------------ context mgr

    @classmethod
    @asynccontextmanager
    async def hold_execution_lease(cls, login_user) -> AsyncIterator[tuple[SlotOutcome, SlotLease | None]]:
        """Hold an execution lease for the duration of a request.

        Only valid where the owner lives exactly as long as the ``with`` body.
        WebSocket per-message handlers return while the connection lives, and
        streaming endpoints return before the stream starts — those manage
        their own lease.
        """
        outcome, lease = await cls.ensure_lease(login_user)
        task: asyncio.Task | None = None
        if outcome is SlotOutcome.HELD and lease is not None:
            task = cls.start_renewal(lease)
        try:
            yield outcome, lease
        finally:
            await cls.stop_renewal(task, lease if outcome is SlotOutcome.HELD else None)
