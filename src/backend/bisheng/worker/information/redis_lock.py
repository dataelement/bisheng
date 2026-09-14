import uuid
from typing import Any

from loguru import logger

_REFRESH_SCRIPT = """
local current = redis.call('GET', KEYS[1])
if current == ARGV[1] then
    return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

_RELEASE_SCRIPT = """
local current = redis.call('GET', KEYS[1])
if current == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class InformationRedisLock:
    """Redis token lock that never falls back to process-local ownership."""

    def __init__(
        self,
        redis_connection: Any,
        key: str,
        *,
        ttl_seconds: int,
        token: str | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.redis = redis_connection
        self.key = key
        self.ttl_seconds = ttl_seconds
        self.token = token or uuid.uuid4().hex
        self.acquired = False
        self.redis_available = True
        self.ownership_lost = False

    def acquire(self) -> bool:
        try:
            self.acquired = bool(self.redis.set(self.key, self.token, nx=True, ex=self.ttl_seconds))
            return self.acquired
        except Exception:
            self.redis_available = False
            self.acquired = False
            logger.exception("information redis lock acquire failed key={}", self.key)
            return False

    def refresh(self) -> bool:
        if not self.acquired:
            return False
        try:
            refreshed = bool(
                self.redis.eval(
                    _REFRESH_SCRIPT,
                    1,
                    self.key,
                    self.token,
                    self.ttl_seconds,
                )
            )
        except Exception:
            self.redis_available = False
            refreshed = False
            logger.exception("information redis lock refresh failed key={}", self.key)
        if not refreshed:
            self.ownership_lost = True
            self.acquired = False
        return refreshed

    def release(self) -> bool:
        try:
            released = bool(self.redis.eval(_RELEASE_SCRIPT, 1, self.key, self.token))
        except Exception:
            self.redis_available = False
            logger.exception("information redis lock release failed key={}", self.key)
            return False
        self.acquired = False
        if not released:
            self.ownership_lost = True
        return released

    def __enter__(self) -> "InformationRedisLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self.acquired:
            self.release()
