from __future__ import annotations

import json
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from bisheng.core.cache.redis_manager import get_redis_client


class ModelRateLimitState(StrEnum):
    NORMAL = "normal"
    RECOVERING = "recovering"
    BUSY = "busy"


@dataclass(frozen=True, slots=True)
class ModelRateLimitView:
    model_id: int
    rate_limit_state: ModelRateLimitState
    busy_until: datetime | None
    status_version: int


@dataclass(frozen=True, slots=True)
class MarkBusyResult:
    view: ModelRateLimitView
    should_schedule: bool
    probe_token: str | None


@dataclass(frozen=True, slots=True)
class ProbeRateLimitResult:
    changed: bool
    next_probe_token: str | None


_MARK_BUSY_SCRIPT = """
-- operation:mark_busy
local raw = redis.call('GET', KEYS[1])
local previous = nil
if raw then
    previous = cjson.decode(raw)
end

local version = tonumber(ARGV[3])
local previous_probe_state = nil
local last_probe_at = cjson.null
if previous then
    previous_probe_state = previous.probe_state
    if previous.last_probe_at then
        last_probe_at = previous.last_probe_at
    end
end

local should_schedule = 1
local probe_token = ARGV[4]
local probe_attempt = 1
if previous_probe_state == 'scheduled'
    and previous.probe_token
    and previous.probe_attempt then
    should_schedule = 0
    probe_token = previous.probe_token
    probe_attempt = tonumber(previous.probe_attempt)
end

local now_epoch = tonumber(ARGV[1])
local ttl_seconds = tonumber(ARGV[2])
local next_state = {
    state = 'recovering',
    version = version,
    limited_at = now_epoch,
    busy_until = now_epoch + ttl_seconds,
    probe_state = 'scheduled',
    probe_attempt = probe_attempt,
    probe_token = probe_token,
    last_probe_at = last_probe_at
}
local encoded = cjson.encode(next_state)
redis.call('SET', KEYS[1], encoded, 'EX', ttl_seconds)
return {encoded, should_schedule}
"""


_BEGIN_PROBE_SCRIPT = """
-- operation:begin_probe
local raw = redis.call('GET', KEYS[1])
if not raw then
    return {0, 0}
end

local state = cjson.decode(raw)
if state.probe_state ~= 'scheduled'
    or state.probe_token ~= ARGV[2]
    or tonumber(state.probe_attempt) ~= tonumber(ARGV[3]) then
    return {0, 0}
end

state.probe_state = 'running'
state.last_probe_at = tonumber(ARGV[1])
redis.call('SET', KEYS[1], cjson.encode(state), 'KEEPTTL')
return {1, tonumber(state.version)}
"""


_RECORD_PROBE_LIMIT_SCRIPT = """
-- operation:record_probe_limit
local raw = redis.call('GET', KEYS[1])
if not raw then
    return 0
end

local state = cjson.decode(raw)
if tonumber(state.version) ~= tonumber(ARGV[1]) then
    return 0
end
if state.probe_state ~= 'running'
    or tonumber(state.probe_attempt) ~= tonumber(ARGV[2]) then
    return 0
end

if tonumber(ARGV[3]) == 1 then
    state.state = 'busy'
    state.probe_state = 'exhausted'
else
    state.state = 'recovering'
    state.probe_state = 'scheduled'
    state.probe_attempt = tonumber(ARGV[2]) + 1
    state.probe_token = ARGV[4]
end
redis.call('SET', KEYS[1], cjson.encode(state), 'KEEPTTL')
return 1
"""


_CLEAR_VERSION_SCRIPT = """
-- operation:clear_version
local raw = redis.call('GET', KEYS[1])
if not raw then
    return 0
end

local state = cjson.decode(raw)
if tonumber(state.version) ~= tonumber(ARGV[1]) then
    return 0
end

redis.call('DEL', KEYS[1])
return 1
"""


class ModelRateLimitStateService:
    """Tenant-scoped, model-level Redis projection for transient rate limits."""

    def __init__(
        self,
        redis: Any | None = None,
        ttl_seconds: int = 300,
        clock: Callable[[], datetime] | None = None,
        version_factory: Callable[[], int] | None = None,
        probe_token_factory: Callable[[], str] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._redis = redis
        self._ttl_seconds = ttl_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        # Redis Lua numbers use IEEE-754 doubles. A random 52-bit generation is
        # represented exactly and is not reset when the short-lived busy key is
        # deleted or expires.
        self._version_factory = version_factory or (lambda: secrets.randbits(52) or 1)
        self._probe_token_factory = probe_token_factory or (lambda: secrets.token_urlsafe(24))

    @staticmethod
    def _key(tenant_id: int, model_id: int) -> str:
        return f"model_rate_limit:{tenant_id}:{model_id}"

    async def _connection(self, key: str | None = None) -> Any:
        client = self._redis or await get_redis_client()
        if key is not None and hasattr(client, "acluster_nodes"):
            await client.acluster_nodes(key)
        return getattr(client, "async_connection", client)

    def _now_epoch(self) -> int:
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        return int(now.timestamp())

    @staticmethod
    def _decode(value: Any) -> str:
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)

    @classmethod
    def _payload(cls, raw: Any) -> dict[str, Any]:
        return json.loads(cls._decode(raw))

    @classmethod
    def _view(cls, model_id: int, raw: Any | None) -> ModelRateLimitView:
        if raw is None:
            return ModelRateLimitView(
                model_id=model_id,
                rate_limit_state=ModelRateLimitState.NORMAL,
                busy_until=None,
                status_version=0,
            )

        payload = cls._payload(raw)
        busy_until_epoch = payload.get("busy_until")
        busy_until = datetime.fromtimestamp(int(busy_until_epoch), tz=UTC) if busy_until_epoch is not None else None
        return ModelRateLimitView(
            model_id=model_id,
            rate_limit_state=ModelRateLimitState(payload["state"]),
            busy_until=busy_until,
            status_version=int(payload["version"]),
        )

    async def mark_busy(self, tenant_id: int, model_id: int) -> MarkBusyResult:
        key = self._key(tenant_id, model_id)
        connection = await self._connection(key)
        raw_state, should_schedule = await connection.eval(
            _MARK_BUSY_SCRIPT,
            1,
            key,
            self._now_epoch(),
            self._ttl_seconds,
            self._version_factory(),
            self._probe_token_factory(),
        )
        payload = self._payload(raw_state)
        return MarkBusyResult(
            view=self._view(model_id, raw_state),
            should_schedule=bool(int(should_schedule)),
            probe_token=str(payload["probe_token"]),
        )

    async def begin_probe(
        self,
        tenant_id: int,
        model_id: int,
        probe_token: str,
        probe_attempt: int,
    ) -> int | None:
        key = self._key(tenant_id, model_id)
        connection = await self._connection(key)
        claimed, current_version = await connection.eval(
            _BEGIN_PROBE_SCRIPT,
            1,
            key,
            self._now_epoch(),
            probe_token,
            probe_attempt,
        )
        return int(current_version) if bool(int(claimed)) else None

    async def record_probe_rate_limited(
        self,
        tenant_id: int,
        model_id: int,
        observed_version: int,
        probe_attempt: int,
        *,
        exhausted: bool,
    ) -> ProbeRateLimitResult:
        key = self._key(tenant_id, model_id)
        connection = await self._connection(key)
        next_probe_token = self._probe_token_factory()
        changed = await connection.eval(
            _RECORD_PROBE_LIMIT_SCRIPT,
            1,
            key,
            observed_version,
            probe_attempt,
            int(exhausted),
            next_probe_token,
        )
        did_change = bool(int(changed))
        return ProbeRateLimitResult(
            changed=did_change,
            next_probe_token=next_probe_token if did_change and not exhausted else None,
        )

    async def clear_if_version(
        self,
        tenant_id: int,
        model_id: int,
        observed_version: int,
    ) -> bool:
        key = self._key(tenant_id, model_id)
        connection = await self._connection(key)
        changed = await connection.eval(
            _CLEAR_VERSION_SCRIPT,
            1,
            key,
            observed_version,
        )
        return bool(int(changed))

    async def get_state(self, tenant_id: int, model_id: int) -> ModelRateLimitView:
        key = self._key(tenant_id, model_id)
        connection = await self._connection(key)
        return self._view(model_id, await connection.get(key))

    async def list_states(
        self,
        tenant_id: int,
        model_ids: Sequence[int],
    ) -> dict[int, ModelRateLimitView]:
        unique_model_ids = list(dict.fromkeys(model_ids))
        if not unique_model_ids:
            return {}
        keys = [self._key(tenant_id, model_id) for model_id in unique_model_ids]
        connection = await self._connection(keys[0])
        if hasattr(connection, "mget_nonatomic"):
            raw_states = await connection.mget_nonatomic(keys)
        else:
            raw_states = await connection.mget(keys)
        return {
            model_id: self._view(model_id, raw_state)
            for model_id, raw_state in zip(unique_model_ids, raw_states, strict=True)
        }
