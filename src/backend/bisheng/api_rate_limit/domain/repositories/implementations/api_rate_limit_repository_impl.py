from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from uuid import uuid4

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.api_rate_limit.domain.repositories.interfaces.api_rate_limit_repository import (
    API_RATE_LIMIT_CONFIG_KEY,
    ApiRateLimitConfigRecord,
    ApiRateLimitConfigRepository,
)
from bisheng.api_rate_limit.domain.schemas.api_rate_limit import (
    ApiRateLimitConfig,
    RateLimitDimension,
    RateLimitLimits,
)
from bisheng.common.models.config import Config
from bisheng.core.cache.redis_conn import RedisClient


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    dimension: RateLimitDimension | None = None
    retry_after: int = 0


class ApiRateLimitConfigRepositoryImpl(ApiRateLimitConfigRepository):
    _COMMENT = "Cluster-wide API rate limit config"

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _to_record(model: Config | None) -> ApiRateLimitConfigRecord | None:
        if model is None:
            return None
        return ApiRateLimitConfigRecord(key=model.key, value=model.value, comment=model.comment)

    async def _find_model(self, *, for_update: bool) -> Config | None:
        statement = select(Config).where(Config.key == API_RATE_LIMIT_CONFIG_KEY)
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.exec(statement)
        return result.first()

    async def get(self) -> ApiRateLimitConfigRecord | None:
        return self._to_record(await self._find_model(for_update=False))

    async def get_for_update(self) -> ApiRateLimitConfigRecord | None:
        return self._to_record(await self._find_model(for_update=True))

    async def write_value(self, value: str) -> None:
        model = await self._find_model(for_update=False)
        if model is None:
            model = Config(key=API_RATE_LIMIT_CONFIG_KEY, value=value, comment=self._COMMENT)
        else:
            model.value = value
            model.comment = model.comment or self._COMMENT
        self.session.add(model)
        await self.session.flush()


class ApiRateLimitRedisRepository:
    ACTIVE_KEY = "bisheng:api_rate_limit:{config}:active"
    ACTIVE_REVISION_KEY = "bisheng:api_rate_limit:{config}:active_revision"
    CANDIDATE_PREFIX = "bisheng:api_rate_limit:{config}:candidate"
    RECOVERY_LOCK_KEY = "bisheng:api_rate_limit:{config}:recover_lock"
    CANDIDATE_TTL_SECONDS = 300
    RECOVERY_LOCK_TTL_SECONDS = 5

    _ACTIVATE_SCRIPT = """
local candidate = redis.call('GET', KEYS[1])
if not candidate then
  return -1
end
local current = tonumber(redis.call('GET', KEYS[3]) or '-1')
local incoming = tonumber(ARGV[1])
if current > incoming then
  return 0
end
redis.call('SET', KEYS[2], candidate)
redis.call('SET', KEYS[3], ARGV[1])
redis.call('DEL', KEYS[1])
return 1
"""
    _ACQUIRE_LOCK_SCRIPT = """
if redis.call('SET', KEYS[1], ARGV[1], 'NX', 'EX', ARGV[2]) then
  return 1
end
return 0
"""
    _RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""
    _COUNT_SCRIPT = """
local max_ttl = 0
local max_index = 0
for i = 1, #KEYS do
  local arg_index = ((i - 1) * 2) + 1
  local limit = tonumber(ARGV[arg_index])
  local ttl = tonumber(ARGV[arg_index + 1])
  local count = redis.call('INCR', KEYS[i])
  if count == 1 or redis.call('TTL', KEYS[i]) < 0 then
    redis.call('EXPIRE', KEYS[i], ttl + 1)
  end
  if count > limit and ttl > max_ttl then
    max_ttl = ttl
    max_index = i
  end
end
if max_index > 0 then
  return {0, max_index, max_ttl}
end
return {1, 0, 0}
"""

    def __init__(self, redis_client: RedisClient):
        self.redis = redis_client

    @staticmethod
    def _serialized(config: ApiRateLimitConfig) -> dict:
        return config.model_dump(mode="json", by_alias=True)

    @classmethod
    def content_digest(cls, config: ApiRateLimitConfig) -> str:
        value = json.dumps(cls._serialized(config), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    async def get_active(self) -> ApiRateLimitConfig | None:
        value = await self.redis.aget(self.ACTIVE_KEY)
        if value is None:
            return None
        return ApiRateLimitConfig.model_validate(value)

    async def stage(self, config: ApiRateLimitConfig) -> str:
        digest = self.content_digest(config)[:16]
        candidate_key = f"{self.CANDIDATE_PREFIX}:{config.revision}:{digest}"
        await self.redis.aset(
            candidate_key,
            self._serialized(config),
            expiration=self.CANDIDATE_TTL_SECONDS,
        )
        return candidate_key

    async def activate(self, candidate_key: str, revision: int) -> bool:
        result = await self.redis.aeval(
            self._ACTIVATE_SCRIPT,
            keys=[candidate_key, self.ACTIVE_KEY, self.ACTIVE_REVISION_KEY],
            args=[revision],
        )
        return int(result) == 1

    async def acquire_recovery_lock(self) -> str | None:
        token = uuid4().hex
        result = await self.redis.aeval(
            self._ACQUIRE_LOCK_SCRIPT,
            keys=[self.RECOVERY_LOCK_KEY],
            args=[token, self.RECOVERY_LOCK_TTL_SECONDS],
        )
        return token if int(result) == 1 else None

    async def release_recovery_lock(self, token: str) -> None:
        await self.redis.aeval(
            self._RELEASE_LOCK_SCRIPT,
            keys=[self.RECOVERY_LOCK_KEY],
            args=[token],
        )

    @staticmethod
    def _policy_hash(limits: RateLimitLimits) -> str:
        normalized = json.dumps(limits.model_dump(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _endpoint_hash(method: str, route_template: str) -> str:
        return hashlib.sha256(f"{method.upper()} {route_template}".encode()).hexdigest()[:16]

    async def check(
        self,
        *,
        method: str,
        route_template: str,
        limits: RateLimitLimits,
        now: float | None = None,
    ) -> RateLimitDecision:
        active_items = limits.active_items()
        if not active_items:
            return RateLimitDecision(allowed=True)

        epoch_seconds = int(time.time() if now is None else now)
        window_seconds = {
            RateLimitDimension.SECOND: 1,
            RateLimitDimension.MINUTE: 60,
            RateLimitDimension.HOUR: 3600,
            RateLimitDimension.DAY: 86400,
        }
        endpoint_hash = self._endpoint_hash(method, route_template)
        policy_hash = self._policy_hash(limits)
        hash_tag = f"{{{endpoint_hash}:{policy_hash}}}"
        keys: list[str] = []
        args: list[int] = []
        dimensions: list[RateLimitDimension] = []
        for dimension, limit in active_items:
            seconds = window_seconds[dimension]
            bucket = math.floor(epoch_seconds / seconds)
            retry_after = max(1, seconds - (epoch_seconds % seconds))
            keys.append(f"bisheng:api_rate_limit:counter:{hash_tag}:{dimension.value}:{bucket}")
            args.extend([limit, retry_after])
            dimensions.append(dimension)

        result = await self.redis.aeval(self._COUNT_SCRIPT, keys=keys, args=args)
        allowed, dimension_index, retry_after = (int(value) for value in result)
        if allowed == 1:
            return RateLimitDecision(allowed=True)
        return RateLimitDecision(
            allowed=False,
            dimension=dimensions[dimension_index - 1],
            retry_after=max(1, retry_after),
        )
