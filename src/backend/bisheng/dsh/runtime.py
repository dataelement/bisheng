"""Production DSH composition shared by the HTTP API, workers and controlled CLI."""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from loguru import logger

from bisheng.common.errcode.dsh import DshQuotaUnavailableError
from bisheng.dsh.domain.repositories.policy import DshPolicyRepository
from bisheng.dsh.domain.repositories.usage import DshUsageRepository
from bisheng.dsh.domain.services.model import DshModelService
from bisheng.dsh.domain.services.usage import DshUsageService
from bisheng.dsh.infrastructure.quota_redis import QuotaRedis
from bisheng.dsh.infrastructure.quota_topology import QuotaTopology, create_quota_redis


async def read_policy(user_id: int):
    def read():
        from bisheng.core.database import get_sync_db_session

        with get_sync_db_session() as session:
            policy = DshPolicyRepository(session).get(user_id)
            return policy.model_copy(deep=True) if policy else None

    return await asyncio.to_thread(read)


async def read_persisted_usage(user_id: int, month: str):
    def read():
        from bisheng.core.database import get_sync_db_session

        with get_sync_db_session() as session:
            return DshUsageRepository(session).persisted_usage(user_id, month)

    return await asyncio.to_thread(read)


async def read_new_month_proof(user_id: int, month: str):
    def read():
        from bisheng.core.database import get_sync_db_session

        with get_sync_db_session() as session:
            return DshUsageRepository(session).new_month_proof(user_id, month)

    return await asyncio.to_thread(read)


@dataclass
class ModelRuntime:
    model: DshModelService
    usage: DshUsageService
    quota: QuotaRedis
    settings: object
    activation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def activate(self):
        async with self.activation_lock:
            await self._activate()

    async def _activate(self):
        await self.quota.topology.activate()

    async def prepare_month(self, principal, month: str):
        await self.activate()
        try:
            return await self.usage.read_usage(int(principal.tenant_id), int(principal.user_id), month)
        except Exception:
            logger.exception("DSH quota storage is unavailable")
            raise DshQuotaUnavailableError() from None

    async def complete(self, principal, request):
        from bisheng.dsh.domain.services.access import principal_scope

        with principal_scope(principal):
            month = datetime.now(UTC).astimezone(ZoneInfo(self.settings.billing_timezone)).strftime("%Y-%m")
            await self.prepare_month(principal, month)
            return await self.model.complete(principal, request)

    async def close(self):
        self.quota.topology.close()
        await self.quota.redis.aclose()


async def get_model_runtime(runtime) -> ModelRuntime:
    existing = getattr(runtime, "models", None)
    if existing is not None:
        return existing
    # Construction has no await until publication, so concurrent requests share one instance.
    from bisheng.llm.domain.services.llm import LLMService

    config = runtime.settings
    from bisheng.common.services.config_service import settings as application_settings

    redis = create_quota_redis(application_settings.redis_url)
    quota = QuotaRedis(
        redis,
        QuotaTopology(redis, shared=True, automatic=True),
        memory_budget_bytes=config.quota_memory_budget_bytes,
        memory_headroom_bytes=config.quota_memory_headroom_bytes,
        backlog_high_watermark=config.quota_backlog_high_watermark,
        backlog_stop_seconds=config.backlog_stop_seconds,
    )
    from bisheng.dsh.domain.services.automatic_quota_recovery import AutomaticQuotaRecovery
    from bisheng.dsh.operations_runtime import repository_scope

    quota.recovery = AutomaticQuotaRecovery(
        quota, lambda: repository_scope(DshUsageRepository), billing_timezone=config.billing_timezone
    )
    usage = DshUsageService(quota)

    def build(model, server, principal, request):
        return LLMService.build_dsh_llm(model, server, user_id=int(principal.user_id), streaming=request.stream)

    from bisheng.dsh.infrastructure.model_capabilities import model_capabilities

    capabilities = model_capabilities

    model = DshModelService(
        policy_reader=read_policy,
        model_loader=LLMService.get_dsh_model_snapshot,
        llm_builder=build,
        capabilities_for=capabilities,
        usage=usage,
        now=lambda: datetime.now(UTC),
        billing_timezone=config.billing_timezone,
    )
    result = ModelRuntime(model, usage, quota, config)
    runtime.models = result
    return result
