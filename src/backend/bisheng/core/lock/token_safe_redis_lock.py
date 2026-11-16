from __future__ import annotations

import asyncio
import contextlib
import secrets
import time
from types import TracebackType


class RedisLockBusyError(RuntimeError):
    """Raised when another owner currently holds the lock."""


class RedisLockLostError(RuntimeError):
    """Raised when a lease can no longer be renewed by its owner."""


_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""

_RENEW_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""


class TokenSafeRedisLock:
    """Redis lease with atomic acquire and token-safe release/renewal."""

    def __init__(
        self,
        redis,
        key: str,
        *,
        ttl_seconds: int,
        renewal_interval_seconds: float,
        acquire_timeout_seconds: float = 0,
        retry_interval_seconds: float = 0.05,
    ):
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if renewal_interval_seconds <= 0 or renewal_interval_seconds >= ttl_seconds:
            raise ValueError("renewal_interval_seconds must be positive and lower than ttl_seconds")
        if acquire_timeout_seconds < 0:
            raise ValueError("acquire_timeout_seconds must not be negative")
        if retry_interval_seconds <= 0:
            raise ValueError("retry_interval_seconds must be positive")
        self._redis = getattr(redis, "async_connection", redis)
        self.key = key
        self.ttl_seconds = ttl_seconds
        self.renewal_interval_seconds = renewal_interval_seconds
        self.acquire_timeout_seconds = acquire_timeout_seconds
        self.retry_interval_seconds = retry_interval_seconds
        self.token = secrets.token_urlsafe(32)
        self._renewal_task: asyncio.Task | None = None
        self._lost_error: BaseException | None = None
        self._owned = False

    async def acquire(self) -> None:
        deadline = time.monotonic() + self.acquire_timeout_seconds
        while True:
            acquired = await self._redis.set(
                self.key,
                self.token,
                nx=True,
                ex=self.ttl_seconds,
            )
            if acquired:
                break
            remaining = deadline - time.monotonic()
            if self.acquire_timeout_seconds == 0 or remaining <= 0:
                raise RedisLockBusyError(f"Redis lock is busy: {self.key}")
            await asyncio.sleep(min(self.retry_interval_seconds, remaining))
        self._owned = True
        self._renewal_task = asyncio.create_task(self._renew_loop())

    async def _renew_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.renewal_interval_seconds)
                renewed = await self._redis.eval(
                    _RENEW_SCRIPT,
                    1,
                    self.key,
                    self.token,
                    self.ttl_seconds,
                )
                if not renewed:
                    self._lost_error = RedisLockLostError(f"Redis lock ownership lost: {self.key}")
                    self._owned = False
                    return
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._lost_error = RedisLockLostError(f"Redis lock renewal failed: {self.key}")
            self._lost_error.__cause__ = error
            self._owned = False

    def ensure_owned(self) -> None:
        if self._lost_error is not None:
            raise self._lost_error
        if not self._owned:
            raise RedisLockLostError(f"Redis lock is not owned: {self.key}")

    async def release(self) -> None:
        if self._renewal_task is not None:
            self._renewal_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._renewal_task
            self._renewal_task = None
        try:
            await self._redis.eval(_RELEASE_SCRIPT, 1, self.key, self.token)
        finally:
            self._owned = False

    async def __aenter__(self) -> TokenSafeRedisLock:
        await self.acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.release()
