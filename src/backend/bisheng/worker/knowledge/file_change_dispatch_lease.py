from __future__ import annotations

import secrets
from dataclasses import dataclass

_ADOPT_OR_ACQUIRE_SCRIPT = """
local current = redis.call('get', KEYS[1])
if current == ARGV[1] then
  redis.call('expire', KEYS[1], ARGV[2])
  return 1
end
if not current then
  redis.call('set', KEYS[1], ARGV[1], 'EX', ARGV[2], 'NX')
  return 1
end
return 0
"""

_RENEW_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""

_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


@dataclass(frozen=True)
class FileChangeDispatchLease:
    key: str
    token: str


class FileChangeDispatchLeaseStore:
    """Best-effort Redis single-flight claims for F046 control messages.

    Durable request/step claims remain the correctness boundary. These leases
    only stop periodic recovery and self-propelling callbacks from filling the
    shared default queue with equivalent control work.
    """

    def __init__(self, redis_client, *, ttl_seconds: int) -> None:
        if int(ttl_seconds) <= 0:
            raise ValueError("F046 dispatch lease ttl must be positive")
        self._redis = getattr(redis_client, "async_connection", redis_client)
        self.ttl_seconds = int(ttl_seconds)

    async def claim(self, key: str) -> FileChangeDispatchLease | None:
        token = secrets.token_urlsafe(32)
        acquired = await self._redis.set(
            str(key),
            token,
            nx=True,
            ex=self.ttl_seconds,
        )
        if not acquired:
            return None
        return FileChangeDispatchLease(key=str(key), token=token)

    async def adopt_or_acquire(self, lease: FileChangeDispatchLease) -> bool:
        return bool(
            await self._redis.eval(
                _ADOPT_OR_ACQUIRE_SCRIPT,
                1,
                lease.key,
                lease.token,
                self.ttl_seconds,
            )
        )

    async def renew(self, lease: FileChangeDispatchLease) -> bool:
        return bool(
            await self._redis.eval(
                _RENEW_SCRIPT,
                1,
                lease.key,
                lease.token,
                self.ttl_seconds,
            )
        )

    async def release(self, lease: FileChangeDispatchLease) -> None:
        await self._redis.eval(_RELEASE_SCRIPT, 1, lease.key, lease.token)


def new_file_change_dispatch_lease(key: str, token: str | None = None) -> FileChangeDispatchLease:
    normalized_key = str(key).strip()
    if not normalized_key:
        raise ValueError("F046 dispatch lease key must not be empty")
    normalized_token = str(token).strip() if token is not None else secrets.token_urlsafe(32)
    if not normalized_token:
        raise ValueError("F046 dispatch lease token must not be empty")
    return FileChangeDispatchLease(key=normalized_key, token=normalized_token)
