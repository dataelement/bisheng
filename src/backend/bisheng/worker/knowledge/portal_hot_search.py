"""Tenant-aware Celery tasks for the portal home hot-search rebuild (F048).

Root Beat only fans out; every tenant child task carries an explicit
``tenant_id`` header that ``worker/tenant_context.py`` restores into the
ContextVar, so all downstream repos see the right tenant.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from loguru import logger

from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.database.models.tenant import TenantDao
from bisheng.knowledge.domain.repositories.implementations.portal_hot_search_redis_repository_impl import (
    PortalHotSearchRedisRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.portal_hot_search_repository_impl import (
    PortalHotSearchRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.portal_hot_search_telemetry_repository_impl import (
    PortalHotSearchTelemetryRepositoryImpl,
)
from bisheng.knowledge.domain.services.portal_hot_search_filter_service import (
    PortalHotSearchFilterService,
)
from bisheng.knowledge.domain.services.portal_hot_search_intent_service import (
    PortalHotSearchIntentService,
)
from bisheng.knowledge.domain.services.portal_hot_search_pipeline_service import (
    PortalHotSearchPipelineService,
)
from bisheng.knowledge.domain.services.portal_hot_search_rewrite_service import (
    PortalHotSearchRewriteService,
)
from bisheng.knowledge.domain.services.portal_hot_search_scoring_service import (
    PortalHotSearchScoringService,
)
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

KNOWLEDGE_QUEUE = "knowledge_celery"


def _dispatch_task_for_tenants(task, tenant_ids: list[int]) -> None:
    for tenant_id in sorted({int(value) for value in tenant_ids if int(value) > 0}):
        task.apply_async(headers={"tenant_id": tenant_id}, queue=KNOWLEDGE_QUEUE)


def _build_llm_invoke(tenant_id: int) -> Callable[[str], str] | None:
    """Return a prompt->text callable backed by the tenant knowledge LLM, or None."""
    from bisheng.llm.domain.services import LLMService

    try:
        llm = LLMService.get_knowledge_similar_llm(invoke_user_id=0, tenant_id=tenant_id)
    except Exception:
        logger.warning("hot-search LLM resolve failed tenant={}", tenant_id)
        return None
    if llm is None:
        return None

    def _invoke(prompt: str) -> str:
        response = llm.invoke(prompt)
        return getattr(response, "content", None) or str(response)

    return _invoke


async def _rebuild_async(now: datetime | None = None) -> str:
    tenant_id = int(get_current_tenant_id() or DEFAULT_TENANT_ID)
    config = settings.portal_hot_search
    if not config.enabled:
        logger.info("hot-search rebuild disabled tenant={}", tenant_id)
        return "disabled"

    now = now or datetime.now(timezone.utc)
    llm_invoke = _build_llm_invoke(tenant_id)
    telemetry_repository = PortalHotSearchTelemetryRepositoryImpl()
    redis_repository = PortalHotSearchRedisRepositoryImpl(
        cache_ttl=config.redis_ttl,
        lock_ttl=config.lock_ttl,
    )
    filter_service = PortalHotSearchFilterService()
    scoring_service = PortalHotSearchScoringService(
        min_unique_users=config.min_unique_users,
        min_search_count=config.min_search_count,
        window_days=config.window_days,
    )
    intent_service = PortalHotSearchIntentService(llm_invoke=llm_invoke)
    rewrite_service = PortalHotSearchRewriteService(llm_invoke=llm_invoke)

    async with get_async_db_session() as session:
        pipeline = PortalHotSearchPipelineService(
            tenant_id=tenant_id,
            config=config,
            telemetry_repository=telemetry_repository,
            hot_search_repository=PortalHotSearchRepositoryImpl(session),
            redis_repository=redis_repository,
            filter_service=filter_service,
            intent_service=intent_service,
            scoring_service=scoring_service,
            rewrite_service=rewrite_service,
        )
        # Capture (not propagate) the failure inside the session block so the
        # failed batch_run row can be committed before we re-raise; letting the
        # exception escape here would trigger the session-maker rollback.
        error: Exception | None = None
        status = "skipped"
        try:
            stats = await pipeline.run(now=now)
            status = stats.status
        except Exception as exc:
            error = exc
        try:
            await session.commit()
        except Exception:
            await session.rollback()
    if error is not None:
        raise error
    return status


@bisheng_celery.task(
    bind=True,
    name="bisheng.worker.knowledge.portal_hot_search.rebuild_portal_hot_search_snapshot",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    time_limit=1800,
    acks_late=True,
)
def rebuild_portal_hot_search_snapshot_celery(_task):
    return run_async_task(_rebuild_async)


@bisheng_celery.task(
    bind=True,
    name="bisheng.worker.knowledge.portal_hot_search.trigger_portal_hot_search_rebuild",
    acks_late=True,
)
def trigger_portal_hot_search_rebuild_celery(_task):
    """Manual single-tenant rerun (AC-34); reuses the same pipeline and lock."""
    return run_async_task(_rebuild_async)


async def _fanout_async() -> int:
    tenant_ids = [DEFAULT_TENANT_ID, *(await TenantDao.aget_children_ids_active(DEFAULT_TENANT_ID))]
    _dispatch_task_for_tenants(rebuild_portal_hot_search_snapshot_celery, tenant_ids)
    return len(set(tenant_ids))


@bisheng_celery.task(name="bisheng.worker.knowledge.portal_hot_search.fanout_portal_hot_search_rebuild")
def fanout_portal_hot_search_rebuild():
    return run_async_task(_fanout_async)
