"""Fail-closed pinning for a dedicated non-retrying Redis connection."""

import asyncio

from redis.asyncio import Redis
from redis.asyncio.connection import Connection, ConnectionPool, SSLConnection
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import ConnectionError, RedisError


class _PinnedConnectionMixin:
    recovery_connect_allowed = True

    async def connect_check_health(self, check_health=True, retry_socket_connect=True):
        if not self.is_connected and not self.recovery_connect_allowed:
            raise ConnectionError("Quota connection lost; explicit recovery is required")
        return await super().connect_check_health(check_health=check_health, retry_socket_connect=False)


class PinnedQuotaConnection(_PinnedConnectionMixin, Connection):
    pass


class PinnedQuotaSSLConnection(_PinnedConnectionMixin, SSLConnection):
    pass


def create_quota_redis(url: str | dict) -> Redis:
    if isinstance(url, dict):
        import ast

        from redis.asyncio.sentinel import Sentinel, SentinelManagedConnection

        class PinnedSentinelConnection(_PinnedConnectionMixin, SentinelManagedConnection):
            pass

        options = dict(url)
        if options.pop("mode", "sentinel") != "sentinel":
            raise ValueError("DSH quota recovery currently supports standalone and Sentinel Redis")
        hosts = [ast.literal_eval(host) if isinstance(host, str) else host for host in options.pop("sentinel_hosts")]
        sentinel_password = options.pop("sentinel_password", None)
        master = options.pop("sentinel_master")
        sentinel = Sentinel(hosts, sentinel_kwargs={"password": sentinel_password})
        options.update(
            decode_responses=True,
            retry=Retry(NoBackoff(), 0),
            socket_timeout=2,
            socket_connect_timeout=2,
            connection_class=PinnedSentinelConnection,
        )
        connection = sentinel.master_for(master, **options)
        return Redis(connection_pool=connection.connection_pool, single_connection_client=True)
    pool = ConnectionPool.from_url(
        url, decode_responses=True, retry=Retry(NoBackoff(), 0), socket_timeout=2, socket_connect_timeout=2
    )
    pool.connection_class = (
        PinnedQuotaSSLConnection if issubclass(pool.connection_class, SSLConnection) else PinnedQuotaConnection
    )
    return Redis(connection_pool=pool, single_connection_client=True)


class QuotaTopology:
    def __init__(self, redis: Redis, *, shared: bool = False, automatic: bool = False):
        if not redis.single_connection_client:
            raise ValueError("Quota requires one pinned connection with automatic retries disabled")
        if not issubclass(redis.connection_pool.connection_class, _PinnedConnectionMixin):
            raise ValueError("Construct quota storage with create_quota_redis; transparent reconnect is unsafe")
        redis.set_retry(Retry(NoBackoff(), 0))
        self.redis = redis
        self.shared = shared
        self.automatic = automatic
        self.lock = asyncio.Lock()
        self.run_id: str | None = None
        self.connection_id: int | None = None
        self.epoch: int | None = None
        self.ready = False

    def close(self):
        self.ready = False

    async def approve(
        self, run_id: str, epoch: int, *, old_primary_isolated: bool, ledger_proven: bool, evicted_keys: int = 0
    ):
        self.close()
        if not old_primary_isolated or not ledger_proven or epoch < 1:
            raise RuntimeError("Recovery requires fencing and authoritative ledger proof")
        if self.redis.connection is not None:
            self.redis.connection.recovery_connect_allowed = True
        info = await self.redis.info()
        if info.get("run_id") != run_id or info.get("role") != "master":
            raise RuntimeError("Unapproved primary")
        if not self.shared and (info.get("maxmemory_policy") != "noeviction" or info.get("aof_enabled") != 1):
            raise RuntimeError("Quota storage requires AOF and noeviction")
        if self.shared and int(info.get("evicted_keys", 0)) != evicted_keys:
            raise RuntimeError("Shared Redis eviction requires ledger recovery")
        self.evicted_keys = evicted_keys
        self.run_id, self.epoch = run_id, epoch
        self.connection_id = await self.redis.client_id()
        self.redis.connection.recovery_connect_allowed = False
        self.ready = True

    async def activate(self):
        """Reconnect to the configured Redis; SQL recovery no longer needs operator approval."""
        async with self.lock:
            if self.redis.connection is not None:
                self.redis.connection.recovery_connect_allowed = True
            info = await self.redis.info()
            if info.get("role") != "master":
                self.close()
                raise RuntimeError("Quota storage requires a writable Redis primary")
            self.run_id, self.epoch = info["run_id"], 1
            self.connection_id = await self.redis.client_id()
            self.ready = True

    async def check(self):
        if self.automatic:
            if self.redis.connection is not None:
                self.redis.connection.recovery_connect_allowed = True
            try:
                info = await self.redis.info()
                if info.get("role") != "master":
                    raise RuntimeError("Quota storage requires a writable Redis primary")
                self.run_id, self.epoch = info["run_id"], 1
                self.connection_id = await self.redis.client_id()
                self.ready = True
                return
            except (RedisError, RuntimeError):
                self.close()
                raise
        if not self.ready:
            raise RuntimeError("Quota recovery gate is closed")
        try:
            connection_id = await self.redis.client_id()
            info = await self.redis.info()
            if (
                connection_id != self.connection_id
                or info.get("run_id") != self.run_id
                or info.get("role") != "master"
                or (
                    not self.shared
                    and (
                        info.get("aof_last_write_status") != "ok"
                        or info.get("aof_enabled") != 1
                        or info.get("maxmemory_policy") != "noeviction"
                    )
                )
                or (self.shared and int(info.get("evicted_keys", 0)) != self.evicted_keys)
            ):
                raise RuntimeError("Redis connection, primary, or durability state changed")
        except (RedisError, RuntimeError):
            self.close()
            raise
