"""Production CLI and worker assembly; no app configuration is loaded at import time."""

import asyncio
import os
import socket
from collections.abc import Callable
from contextlib import asynccontextmanager, contextmanager

from bisheng.core.context import tenant as context
from bisheng.dsh.config import DshSettings
from bisheng.dsh.domain.repositories.operations_identity import OperationsIdentityRecords
from bisheng.dsh.domain.repositories.usage import DshUsageRepository
from bisheng.dsh.domain.services.projection import DshProjectionService
from bisheng.dsh.domain.services.usage import DshUsageService
from bisheng.dsh.infrastructure.quota_redis import QuotaRedis
from bisheng.dsh.infrastructure.quota_topology import QuotaTopology, create_quota_redis
from bisheng.dsh.infrastructure.shared_trust import OUTBOUND_KEY_ID, configured_key


def _decode_admin_token(token: str) -> dict:
    from bisheng.user.domain.services.auth import AuthJwt

    return AuthJwt().decode_jwt_token(token)


async def _current_login(record: dict):
    from bisheng.user.domain.services.auth import LoginUser

    login = await LoginUser.init_login_user(
        user_id=record["user_id"],
        user_name=record["user_name"],
        tenant_id=record["tenant_id"],
        token_version=record["token_version"],
    )
    from bisheng.permission.application import PermissionObject, PermissionSubject, get_permission_relation_api

    permissions = await get_permission_relation_api()
    current_global = await permissions.check(
        subject=PermissionSubject("user", str(record["user_id"])),
        relation="super_admin",
        resource=PermissionObject("system", "global"),
    )
    # The current LoginUser role list is loaded afresh; preserve the existing global AdminRole path.
    login.is_global_super = bool(current_global or login.is_admin())
    return login


class OperationsAuthentication:
    def __init__(self, *, records=None, decode: Callable = _decode_admin_token, login: Callable = _current_login):
        self.records = records or OperationsIdentityRecords()
        self.decode, self.login = decode, login
        self.tokens = []

    async def authenticate_admin(self, credential: str, *, tenant_id: int) -> int:
        if type(tenant_id) is not int or tenant_id < 1 or not credential or len(credential) > 16384:
            raise PermissionError("A valid administrator credential and selected tenant are required")
        subject = self.decode(credential)
        user_id = subject.get("user_id")
        version = subject.get("token_version", 0)
        if type(user_id) is not int or user_id < 1 or type(version) is not int:
            raise PermissionError("Invalid administrator subject")
        actor = await self.records.actor(user_id)
        if (
            not actor
            or not actor["active"]
            or actor["token_version"] != version
            or subject.get("tenant_id", 1) != actor["tenant_id"]
        ):
            raise PermissionError("Administrator session is stale or disabled")
        login = await self.login(actor)
        if not login.is_global_super or not await self.records.active_tenant(tenant_id):
            raise PermissionError("Current global administrator and active target tenant are required")
        self.tokens.extend(
            [
                context.set_current_tenant_id(tenant_id),
                context.set_admin_scope_tenant_id(None),
                context.set_visible_tenant_ids(frozenset({tenant_id})),
                context._bypass_tenant_filter.set(False),
                context._strict_tenant_filter.set(True),
            ]
        )
        return user_id

    async def authorize(self, actor_user_id: int, user_id: int) -> bool:
        tenant_id = context.get_current_tenant_id()
        if tenant_id is None or type(user_id) is not int or user_id < 1:
            return False
        actor = await self.records.actor(actor_user_id)
        if not actor or not actor["active"] or not await self.records.active_tenant(tenant_id):
            return False
        # The owning repository verifies the historical request's tenant. Disabled/moved users
        # still have accountable usage in their original tenant and must remain reconcilable.
        return bool((await self.login(actor)).is_global_super)

    def reset(self):
        for token in reversed(self.tokens):
            token.var.reset(token)
        self.tokens.clear()


@contextmanager
def repository_scope(repository_type):
    from bisheng.core.database import get_sync_db_session

    with get_sync_db_session() as session, session.begin():
        yield repository_type(session)


class _ActivatedUsage(DshUsageService):
    def __init__(self, quota, activate):
        super().__init__(quota)
        self.activate = activate

    async def get_request(self, event):
        await self.activate()
        return await super().get_request(event)

    async def claim_reconciliation(self, event, **kwargs):
        await self.activate()
        return await super().claim_reconciliation(event, **kwargs)

    async def record_usage(self, event, expected_version):
        await self.activate()
        return await super().record_usage(event, expected_version)


class OperationsRuntime:
    def __init__(self, config: DshSettings):
        self.config = config
        self.settings = config
        self.http = None
        self.gateway = None
        self.admin = None
        self.policy = None
        self.profiles = None
        self.repository_scope = None
        self.authentication = OperationsAuthentication()
        from bisheng.common.services.config_service import settings as application_settings

        redis = create_quota_redis(application_settings.redis_url)
        self.quota = QuotaRedis(
            redis,
            QuotaTopology(redis, shared=True, automatic=True),
            memory_budget_bytes=config.quota_memory_budget_bytes,
            memory_headroom_bytes=config.quota_memory_headroom_bytes,
            backlog_high_watermark=config.quota_backlog_high_watermark,
            backlog_stop_seconds=config.backlog_stop_seconds,
        )
        from bisheng.dsh.domain.services.automatic_quota_recovery import AutomaticQuotaRecovery

        self.quota.recovery = AutomaticQuotaRecovery(
            self.quota, lambda: repository_scope(DshUsageRepository), billing_timezone=config.billing_timezone
        )
        self.activation_lock = asyncio.Lock()
        self.admin_lock = asyncio.Lock()
        self.usage = _ActivatedUsage(self.quota, self.activate)
        self.projection = DshProjectionService(
            self.quota,
            lambda: repository_scope(DshUsageRepository),
            consumer=f"{socket.gethostname()}:{os.getpid()}",
            backpressure_seconds=config.backlog_stop_seconds,
            high_watermark=config.quota_backlog_high_watermark,
            retention_seconds=config.quota_retention_seconds,
            max_batches=config.quota_projection_max_batches,
            max_seconds=config.quota_projection_max_seconds,
        )

    async def authenticate_admin(self, credential: str, *, tenant_id: int) -> int:
        return await self.authentication.authenticate_admin(credential, tenant_id=tenant_id)

    async def activate(self):
        async with self.activation_lock:
            await self.quota.topology.activate()

    async def initialize_admin(self):
        async with self.admin_lock:
            await self._initialize_admin()

    async def _initialize_admin(self):
        if self.admin is not None:
            return
        import httpx

        from bisheng.core.cache.redis_manager import get_redis_client
        from bisheng.dsh.admin_runtime import get_admin_runtime
        from bisheng.dsh.infrastructure.gateway_client import GatewayClient
        from bisheng.dsh.infrastructure.service_auth import RedisNonceStore, ServiceAuth, ServiceKey

        redis = (await get_redis_client()).async_connection
        key = ServiceKey(
            OUTBOUND_KEY_ID,
            configured_key(OUTBOUND_KEY_ID).hex().encode(),
        )
        self.http = httpx.AsyncClient(verify=True, follow_redirects=False)
        self.gateway = GatewayClient(
            self.config.gateway_internal_url,
            ServiceAuth(key, RedisNonceStore(redis)),
            self.http,
            self.config.introspection_timeout_seconds,
        )
        services = await get_admin_runtime(self, quota=_ActivatedQuotaProxy(self), usage=self.usage)
        self.admin, self.policy, self.profiles, self.repository_scope = (
            services.admin,
            services.policy,
            services.profiles,
            services.repository_scope,
        )

    async def close(self):
        self.quota.topology.close()
        try:
            await self.quota.redis.aclose()
            if self.http is not None:
                await self.http.aclose()
        finally:
            self.authentication.reset()


def _production_config():
    from bisheng.common.services.config_service import settings

    config = settings.dsh
    if not config.enabled:
        raise RuntimeError("DSH is disabled")
    return settings, config


_worker_runtime: OperationsRuntime | None = None
_worker_runtime_lock = asyncio.Lock()


@asynccontextmanager
async def operations_worker_runtime():
    global _worker_runtime

    _, config = _production_config()
    async with _worker_runtime_lock:
        if _worker_runtime is None or _worker_runtime.config != config:
            if _worker_runtime is not None:
                await _worker_runtime.close()
            _worker_runtime = OperationsRuntime(config)
    yield _worker_runtime


@asynccontextmanager
async def projection_worker_runtime():
    async with operations_worker_runtime() as runtime:
        await runtime.activate()
        yield runtime.projection


async def close_operations_worker_runtime():
    global _worker_runtime
    if _worker_runtime is not None:
        await _worker_runtime.close()
        _worker_runtime = None


@asynccontextmanager
async def administration_worker_runtime():
    async with operations_worker_runtime() as runtime:
        await runtime.initialize_admin()
        yield runtime


async def active_tenant_ids():
    records = OperationsIdentityRecords()
    return await records.active_tenant_ids()


class _ActivatedQuotaProxy:
    def __init__(self, runtime):
        self.runtime = runtime

    def __getattr__(self, name):
        async def call(*args, **kwargs):
            await self.runtime.activate()
            return await getattr(self.runtime.quota, name)(*args, **kwargs)

        return call


def _register_cli_permission_contexts(settings):
    if not settings.openfga.enabled:
        return
    from bisheng.api.services.f048_permission_runtime import initialize_f048_worker_runtime
    from bisheng.department.domain.services.department_projection_scope import (
        get_department_projection_scope,
        register_department_projection_runtime_context,
    )
    from bisheng.permission.application.process_runtime import register_f048_permission_runtime_context

    async def initialize(client):
        return await initialize_f048_worker_runtime(
            client, external_scopes={"department": get_department_projection_scope()}
        )

    register_f048_permission_runtime_context(initialize)
    register_department_projection_runtime_context()
