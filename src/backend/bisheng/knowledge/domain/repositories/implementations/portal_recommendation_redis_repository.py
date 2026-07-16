from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone

from bisheng.core.cache.redis_conn import RedisClient
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.storage.tenant_storage import get_redis_key_prefix
from bisheng.knowledge.domain.repositories.interfaces.portal_recommendation_redis_repository import (
    PortalRecommendationPoolVersionState,
    PortalRecommendationRedisRepository,
)
from bisheng.knowledge.domain.services.portal_recommendation_pool_service import (
    PortalRecommendationPoolState,
)
from bisheng.knowledge.domain.services.portal_recommendation_service import PortalRecommendationCandidate


class PortalRecommendationRedisRepositoryImpl(PortalRecommendationRedisRepository):
    READ_RETENTION_DAYS = 90
    POOL_VERSION_TTL_SECONDS = 48 * 60 * 60
    # The readiness manifest must disappear before any versioned pool key can
    # expire; otherwise online traffic could keep trusting a partial version.
    POOL_READY_TTL_SECONDS = POOL_VERSION_TTL_SECONDS - 5 * 60
    _RECORD_READ_SCRIPT = """
local current = redis.call('ZSCORE', KEYS[1], ARGV[1])
if (not current) or (tonumber(ARGV[2]) > tonumber(current)) then
  redis.call('ZADD', KEYS[1], ARGV[2], ARGV[1])
end
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[3])
redis.call('EXPIRE', KEYS[1], ARGV[4])
return redis.call('INCR', KEYS[2])
"""
    _INVALIDATE_USER_SCRIPT = """
redis.call('DEL', KEYS[1])
return redis.call('INCR', KEYS[2])
"""

    def __init__(self, *, redis_client: RedisClient | None = None):
        self.redis = redis_client

    async def _redis(self) -> RedisClient:
        if self.redis is None:
            self.redis = await get_redis_client()
        return self.redis

    @staticmethod
    def _assert_current_tenant(tenant_id: int) -> None:
        current = get_current_tenant_id()
        if current is None or int(current) != int(tenant_id):
            raise PermissionError("recommendation Redis tenant does not match current context")

    @staticmethod
    def _key(tenant_id: int, logical_key: str) -> str:
        return f"{get_redis_key_prefix(tenant_id)}{logical_key}"

    @classmethod
    def behavior_version_key(cls, tenant_id: int, user_id: int) -> str:
        return cls._key(tenant_id, f"sg:rec:v1:user:{{{tenant_id}}}:{user_id}:behavior_version")

    @classmethod
    def reads_key(cls, tenant_id: int, user_id: int) -> str:
        return cls._key(tenant_id, f"sg:rec:v1:user:{{{tenant_id}}}:{user_id}:reads")

    @classmethod
    def interest_key(cls, tenant_id: int, user_id: int) -> str:
        return cls._key(tenant_id, f"sg:rec:v1:user:{{{tenant_id}}}:{user_id}:interest")

    @classmethod
    def domains_key(cls, tenant_id: int, user_id: int) -> str:
        return cls._key(tenant_id, f"sg:rec:v1:user:{{{tenant_id}}}:{user_id}:domains")

    @classmethod
    def top_n_key(
        cls,
        tenant_id: int,
        user_id: int,
        config_version: int,
        pool_version: str,
        behavior_version: int,
        scope: str = "base",
    ) -> str:
        safe_scope = str(scope or "base").replace(" ", "_").replace(":", "_")
        return cls._key(
            tenant_id,
            f"sg:rec:v1:user:{{{tenant_id}}}:{user_id}:topn:{safe_scope}:"
            f"{config_version}:{pool_version}:{behavior_version}",
        )

    @classmethod
    def pool_state_key(cls, tenant_id: int) -> str:
        return cls._key(tenant_id, f"sg:rec:v1:pool:{{{tenant_id}}}:active_version")

    @classmethod
    def pool_key(cls, tenant_id: int, pool_version: str, pool_name: str) -> str:
        safe_name = pool_name.replace(" ", "_")
        return cls._key(tenant_id, f"sg:rec:v1:pool:{{{tenant_id}}}:{pool_version}:{safe_name}")

    @classmethod
    def pool_ready_key(cls, tenant_id: int, pool_version: str) -> str:
        return cls.pool_key(tenant_id, pool_version, "ready")

    @classmethod
    def pool_rebuild_trigger_key(cls, tenant_id: int) -> str:
        return cls._key(tenant_id, f"sg:rec:v1:pool:{{{tenant_id}}}:rebuild_trigger")

    @classmethod
    def watermark_key(cls, tenant_id: int) -> str:
        return cls._key(tenant_id, f"sg:rec:v1:reconcile:{tenant_id}:watermark")

    async def increment_behavior_version(self, tenant_id: int, user_id: int) -> int:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        return int(await redis.async_connection.incr(self.behavior_version_key(tenant_id, user_id)))

    async def get_behavior_version(self, tenant_id: int, user_id: int) -> int:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        value = await redis.async_connection.get(self.behavior_version_key(tenant_id, user_id))
        return int(value or 0)

    async def record_read(
        self,
        tenant_id: int,
        user_id: int,
        space_id: int,
        file_id: int,
        read_at: datetime,
    ) -> None:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        key = self.reads_key(tenant_id, user_id)
        read_at = read_at.astimezone(timezone.utc)
        member = f"{space_id}:{file_id}"
        try:
            await redis.async_connection.zadd(key, {member: read_at.timestamp()}, gt=True)
        except TypeError:
            # Minimal Redis-compatible clients may not expose the GT keyword.
            current = await redis.async_connection.zrange(key, 0, -1, withscores=True)
            current_score = next(
                (
                    score
                    for raw_member, score in current
                    if (raw_member.decode() if isinstance(raw_member, bytes) else str(raw_member)) == member
                ),
                None,
            )
            if current_score is None or read_at.timestamp() > float(current_score):
                await redis.async_connection.zadd(key, {member: read_at.timestamp()})
        cutoff = read_at - timedelta(days=self.READ_RETENTION_DAYS)
        await redis.async_connection.zremrangebyscore(key, "-inf", cutoff.timestamp())
        await redis.async_connection.expire(key, self.READ_RETENTION_DAYS * 86400)

    async def record_read_and_increment_behavior_version(
        self,
        tenant_id: int,
        user_id: int,
        space_id: int,
        file_id: int,
        read_at: datetime,
    ) -> int:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        read_at = read_at.astimezone(timezone.utc)
        cutoff = read_at - timedelta(days=self.READ_RETENTION_DAYS)
        return int(
            await redis.async_connection.eval(
                self._RECORD_READ_SCRIPT,
                2,
                self.reads_key(tenant_id, user_id),
                self.behavior_version_key(tenant_id, user_id),
                f"{space_id}:{file_id}",
                read_at.timestamp(),
                cutoff.timestamp(),
                self.READ_RETENTION_DAYS * 86400,
            )
        )

    async def list_recent_reads(
        self,
        tenant_id: int,
        user_id: int,
        *,
        now: datetime | None = None,
    ) -> dict[tuple[int, int], datetime]:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        key = self.reads_key(tenant_id, user_id)
        now = now or datetime.now(timezone.utc)
        cutoff = now - timedelta(days=self.READ_RETENTION_DAYS)
        await redis.async_connection.zremrangebyscore(key, "-inf", cutoff.timestamp())
        values = await redis.async_connection.zrange(key, 0, -1, withscores=True)
        result: dict[tuple[int, int], datetime] = {}
        for raw_member, score in values:
            member = raw_member.decode() if isinstance(raw_member, bytes) else str(raw_member)
            try:
                space_id, file_id = (int(value) for value in member.split(":", 1))
            except (TypeError, ValueError):
                continue
            result[(space_id, file_id)] = datetime.fromtimestamp(float(score), tz=timezone.utc)
        return result

    async def replace_interest(
        self,
        tenant_id: int,
        user_id: int,
        entries: Sequence[tuple[str, float]],
        ttl_seconds: int,
    ) -> None:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        key = self.interest_key(tenant_id, user_id)
        await redis.async_connection.delete(key)
        if entries:
            await redis.async_connection.zadd(key, {member: float(score) for member, score in entries})
            await redis.async_connection.zremrangebyrank(key, 0, -51)
            await redis.async_connection.expire(key, ttl_seconds)

    async def get_interest(self, tenant_id: int, user_id: int) -> list[tuple[str, float]]:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        values = await redis.async_connection.zrange(
            self.interest_key(tenant_id, user_id),
            0,
            49,
            desc=True,
            withscores=True,
        )
        return [
            (member.decode() if isinstance(member, bytes) else str(member), float(score))
            for member, score in values
        ]

    async def set_user_domains(
        self,
        tenant_id: int,
        user_id: int,
        domain_codes: Sequence[str],
        *,
        ttl_seconds: int = 1800,
    ) -> None:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        key = self.domains_key(tenant_id, user_id)
        await redis.async_connection.set(key, json.dumps(sorted(set(domain_codes))))
        await redis.async_connection.expire(key, ttl_seconds)

    async def get_user_domains(self, tenant_id: int, user_id: int) -> list[str] | None:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        value = await redis.async_connection.get(self.domains_key(tenant_id, user_id))
        if value is None:
            return None
        if isinstance(value, bytes):
            value = value.decode()
        return [str(item) for item in json.loads(value)]

    async def invalidate_user(self, tenant_id: int, user_id: int) -> None:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        # Top-N keys are versioned and naturally expire; behavior INCR invalidates them immediately.
        await redis.async_connection.eval(
            self._INVALIDATE_USER_SCRIPT,
            2,
            self.domains_key(tenant_id, user_id),
            self.behavior_version_key(tenant_id, user_id),
        )

    async def set_top_n(
        self,
        tenant_id: int,
        user_id: int,
        config_version: int,
        pool_version: str,
        behavior_version: int,
        ids: Sequence[tuple[int, int]],
        *,
        ttl_seconds: int = 240,
        scope: str = "base",
    ) -> None:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        key = self.top_n_key(
            tenant_id,
            user_id,
            config_version,
            pool_version,
            behavior_version,
            scope,
        )
        await redis.async_connection.set(key, json.dumps([[space_id, file_id] for space_id, file_id in ids]))
        await redis.async_connection.expire(key, ttl_seconds)

    async def get_top_n(
        self,
        tenant_id: int,
        user_id: int,
        config_version: int,
        pool_version: str,
        behavior_version: int,
        *,
        scope: str = "base",
    ) -> list[tuple[int, int]] | None:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        value = await redis.async_connection.get(
            self.top_n_key(
                tenant_id,
                user_id,
                config_version,
                pool_version,
                behavior_version,
                scope,
            )
        )
        if value is None:
            return None
        if isinstance(value, bytes):
            value = value.decode()
        return [(int(space_id), int(file_id)) for space_id, file_id in json.loads(value)]

    async def replace_pool(
        self,
        tenant_id: int,
        pool_version: str,
        pool_name: str,
        entries: Sequence[tuple[PortalRecommendationCandidate, float]],
    ) -> None:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        key = self.pool_key(tenant_id, pool_version, pool_name)
        await redis.async_connection.delete(key)
        if entries:
            mapping = {
                json.dumps(
                    {
                        "space_id": candidate.space_id,
                        "file_id": candidate.file_id,
                        "domain_score": candidate.domain_score,
                        "interest_score": candidate.interest_score,
                        "hot_score": candidate.hot_score,
                        "fresh_score": candidate.fresh_score,
                        "is_public": candidate.is_public,
                        "normal_acl": candidate.normal_acl,
                        "eligible": candidate.eligible,
                    },
                    sort_keys=True,
                ): float(score)
                for candidate, score in entries
            }
            await redis.async_connection.zadd(key, mapping)
            await redis.async_connection.expire(key, self.POOL_VERSION_TTL_SECONDS)

    async def get_pool(
        self,
        tenant_id: int,
        pool_version: str,
        pool_name: str,
        *,
        limit: int = 10_000,
        offset: int = 0,
    ) -> list[PortalRecommendationCandidate]:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        values = await redis.async_connection.zrange(
            self.pool_key(tenant_id, pool_version, pool_name),
            max(offset, 0),
            max(offset + limit - 1, 0),
            desc=True,
        )
        if values:
            await redis.async_connection.expire(
                self.pool_key(tenant_id, pool_version, pool_name),
                self.POOL_VERSION_TTL_SECONDS,
            )
        result = []
        for value in values:
            if isinstance(value, bytes):
                value = value.decode()
            result.append(PortalRecommendationCandidate(**json.loads(value)))
        return result

    async def get_pool_size(self, tenant_id: int, pool_version: str, pool_name: str) -> int:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        return int(
            await redis.async_connection.zcard(
                self.pool_key(tenant_id, pool_version, pool_name)
            )
        )

    async def mark_pool_version_ready(self, tenant_id: int, pool_version: str) -> None:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        await redis.async_connection.set(
            self.pool_ready_key(tenant_id, pool_version),
            "1",
            ex=self.POOL_READY_TTL_SECONDS,
        )

    async def is_pool_version_ready(self, tenant_id: int, pool_version: str) -> bool:
        self._assert_current_tenant(tenant_id)
        if not pool_version:
            return False
        redis = await self._redis()
        key = self.pool_ready_key(tenant_id, pool_version)
        value = await redis.async_connection.get(key)
        return value is not None

    async def acquire_pool_rebuild_trigger(self, tenant_id: int, *, ttl_seconds: int = 300) -> bool:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        return bool(
            await redis.async_connection.set(
                self.pool_rebuild_trigger_key(tenant_id),
                "1",
                nx=True,
                ex=max(int(ttl_seconds), 1),
            )
        )

    async def replace_hot_rotation_states(
        self,
        tenant_id: int,
        pool_version: str,
        pool_name: str,
        states: Mapping[tuple[int, int], PortalRecommendationPoolState],
    ) -> None:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        key = self.pool_key(tenant_id, pool_version, f"{pool_name}:hot_state")
        await redis.async_connection.delete(key)
        if not states:
            return
        await redis.async_connection.hset(
            key,
            mapping={
                f"{space_id}:{file_id}": json.dumps(
                    {
                        "active_since": state.active_since.isoformat(),
                        "cooldown_until": (
                            state.cooldown_until.isoformat()
                            if state.cooldown_until is not None
                            else None
                        ),
                    },
                    sort_keys=True,
                )
                for (space_id, file_id), state in states.items()
            },
        )
        await redis.async_connection.expire(key, self.POOL_VERSION_TTL_SECONDS)

    async def get_hot_rotation_states(
        self,
        tenant_id: int,
        pool_version: str,
        pool_name: str,
    ) -> dict[tuple[int, int], PortalRecommendationPoolState]:
        self._assert_current_tenant(tenant_id)
        if not pool_version:
            return {}
        redis = await self._redis()
        raw = await redis.async_connection.hgetall(
            self.pool_key(tenant_id, pool_version, f"{pool_name}:hot_state")
        )
        if raw:
            await redis.async_connection.expire(
                self.pool_key(tenant_id, pool_version, f"{pool_name}:hot_state"),
                self.POOL_VERSION_TTL_SECONDS,
            )
        result: dict[tuple[int, int], PortalRecommendationPoolState] = {}
        for raw_member, raw_value in raw.items():
            member = raw_member.decode() if isinstance(raw_member, bytes) else str(raw_member)
            value = raw_value.decode() if isinstance(raw_value, bytes) else str(raw_value)
            try:
                space_id, file_id = (int(part) for part in member.split(":", 1))
                payload = json.loads(value)
                cooldown = payload.get("cooldown_until")
                result[(space_id, file_id)] = PortalRecommendationPoolState(
                    active_since=date.fromisoformat(payload["active_since"]),
                    cooldown_until=date.fromisoformat(cooldown) if cooldown else None,
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return result

    async def increment_desired_generation(self, tenant_id: int) -> int:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        return int(
            await redis.async_connection.hincrby(
                self.pool_state_key(tenant_id),
                "desired_generation",
                1,
            )
        )

    async def get_pool_state(self, tenant_id: int) -> PortalRecommendationPoolVersionState:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        raw = await redis.async_connection.hgetall(self.pool_state_key(tenant_id))
        values = {
            (key.decode() if isinstance(key, bytes) else str(key)): (
                value.decode() if isinstance(value, bytes) else str(value)
            )
            for key, value in raw.items()
        }
        return PortalRecommendationPoolVersionState(
            desired_generation=int(values.get("desired_generation", 0)),
            active_generation=int(values.get("active_generation", 0)),
            active_pool_version=values.get("active_pool_version"),
            fingerprint=values.get("active_fingerprint"),
        )

    async def activate_pool_if_current(
        self,
        tenant_id: int,
        generation: int,
        pool_version: str,
        fingerprint: str,
    ) -> bool:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        script = """
local state_key = KEYS[1]
local generation = tonumber(ARGV[1])
local desired = tonumber(redis.call('HGET', state_key, 'desired_generation') or '0')
local active = tonumber(redis.call('HGET', state_key, 'active_generation') or '0')
if desired ~= generation or generation <= active then
  return 0
end
redis.call('HSET', state_key,
  'active_generation', generation,
  'active_pool_version', ARGV[2],
  'active_fingerprint', ARGV[3])
return 1
"""
        result = await redis.async_connection.eval(
            script,
            1,
            self.pool_state_key(tenant_id),
            int(generation),
            pool_version,
            fingerprint,
        )
        return int(result) == 1

    async def set_reconcile_watermark(self, tenant_id: int, update_time: datetime, file_id: int) -> None:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        if update_time.tzinfo is None:
            update_time = update_time.replace(tzinfo=timezone.utc)
        else:
            update_time = update_time.astimezone(timezone.utc)
        await redis.async_connection.set(
            self.watermark_key(tenant_id),
            json.dumps({"update_time": update_time.isoformat(), "file_id": file_id}),
        )

    async def get_reconcile_watermark(self, tenant_id: int) -> tuple[datetime, int] | None:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        value = await redis.async_connection.get(self.watermark_key(tenant_id))
        if value is None:
            return None
        if isinstance(value, bytes):
            value = value.decode()
        payload = json.loads(value)
        return datetime.fromisoformat(payload["update_time"]), int(payload["file_id"])
