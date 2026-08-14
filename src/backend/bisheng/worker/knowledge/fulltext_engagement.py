"""门户互动累计值的合并同步、历史构建与近期校准任务。"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from loguru import logger

from bisheng.common.services.config_service import settings
from bisheng.core.search.elasticsearch.manager import get_es_connection, get_statistics_es_connection
from bisheng.knowledge.domain import knowledge_fulltext_constants as constants
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_engagement_repository_impl import (
    KnowledgeFulltextEngagementQueueRepositoryImpl,
    KnowledgeFulltextEngagementRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_index_repository_impl import (
    KnowledgeFulltextIndexRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_engagement_service import (
    KnowledgeFulltextEngagementService,
    settle_knowledge_fulltext_engagement_batch,
)
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery


def register_fulltext_engagement_beat_schedule() -> None:
    schedule = dict(bisheng_celery.conf.beat_schedule or {})
    schedule.setdefault(
        "sync_knowledge_fulltext_engagement",
        {
            "task": constants.KNOWLEDGE_FULLTEXT_ENGAGEMENT_SYNC_TASK,
            "schedule": float(constants.KNOWLEDGE_FULLTEXT_ENGAGEMENT_DELAY_SECONDS),
        },
    )
    schedule.setdefault(
        "reconcile_knowledge_fulltext_engagement",
        {
            "task": constants.KNOWLEDGE_FULLTEXT_ENGAGEMENT_RECONCILE_TASK,
            "schedule": 86400.0,
        },
    )
    bisheng_celery.conf.beat_schedule = schedule


register_fulltext_engagement_beat_schedule()


@bisheng_celery.task(
    acks_late=True,
    time_limit=720,
    soft_time_limit=700,
    name=constants.KNOWLEDGE_FULLTEXT_ENGAGEMENT_SYNC_TASK,
)
def sync_knowledge_fulltext_engagement() -> dict[str, int]:
    return run_async_task(_sync_engagement)


@bisheng_celery.task(
    acks_late=True,
    time_limit=3600,
    soft_time_limit=3500,
    name=constants.KNOWLEDGE_FULLTEXT_ENGAGEMENT_REBUILD_TASK,
)
def rebuild_knowledge_fulltext_engagement(reset: bool = False) -> dict[str, int | bool]:
    return run_async_task(lambda: _rebuild_engagement(reset=bool(reset)))


@bisheng_celery.task(
    acks_late=True,
    time_limit=1800,
    soft_time_limit=1700,
    name=constants.KNOWLEDGE_FULLTEXT_ENGAGEMENT_RECONCILE_TASK,
)
def reconcile_knowledge_fulltext_engagement() -> dict[str, int | bool]:
    return run_async_task(_reconcile_engagement)


async def _build_service() -> tuple[KnowledgeFulltextEngagementService, KnowledgeFulltextEngagementQueueRepositoryImpl]:
    constants.ensure_runtime_compatible(multi_tenant_enabled=settings.multi_tenant.enabled)
    business_client = await get_es_connection()
    raw_client = await get_statistics_es_connection()
    index_repository = KnowledgeFulltextIndexRepositoryImpl(business_client)
    await index_repository.ensure_index()
    queue_repository = KnowledgeFulltextEngagementQueueRepositoryImpl()
    service = KnowledgeFulltextEngagementService(
        statistics_repository=KnowledgeFulltextEngagementRepositoryImpl(
            daily_client=business_client,
            raw_client=raw_client,
        ),
        queue_repository=queue_repository,
        index_repository=index_repository,
    )
    return service, queue_repository


async def _sync_engagement() -> dict[str, int]:
    service, queue_repository = await _build_service()
    now = datetime.now(timezone.utc)
    now_epoch = int(now.timestamp())
    lease_owner = uuid4().hex
    await queue_repository.release_schedule()
    reclaimed = await queue_repository.reclaim_expired(now_epoch=now_epoch)
    file_ids = await queue_repository.claim(
        now_epoch=now_epoch,
        lease_owner=lease_owner,
        limit=constants.KNOWLEDGE_FULLTEXT_ENGAGEMENT_BATCH_SIZE,
    )
    summary = {
        "claimed": len(file_ids),
        "reclaimed": reclaimed,
        "updated": 0,
        "noop": 0,
        "missing": 0,
        "failed": 0,
    }
    if not file_ids:
        return summary
    try:
        result = await service.sync_file_ids(file_ids, updated_at=now)
    except Exception:
        for file_id in file_ids:
            await queue_repository.retry(
                file_id=file_id,
                lease_owner=lease_owner,
                now_epoch=now_epoch,
            )
        logger.bind(
            claimed_count=len(file_ids),
            status="failed",
            failure_stage="engagement_batch",
        ).exception("knowledge fulltext engagement batch failed")
        raise

    await settle_knowledge_fulltext_engagement_batch(
        queue_repository=queue_repository,
        result=result,
        lease_owner=lease_owner,
        now_epoch=now_epoch,
    )
    summary.update(
        updated=len(result.updated_ids),
        noop=len(result.noop_ids),
        missing=len(result.missing_ids),
        failed=len(result.failed_ids),
    )
    logger.bind(**summary, status="completed").info("knowledge fulltext engagement batch completed")
    return summary


async def _rebuild_engagement(*, reset: bool = False) -> dict[str, int | bool]:
    service, queue_repository = await _build_service()
    token = uuid4().hex
    if not await queue_repository.acquire_history_lock(token):
        return {"acquired": False}
    try:
        if reset:
            await queue_repository.clear_history_state()
        summary = await service.rebuild_history(now=datetime.now(timezone.utc))
        logger.bind(**summary, status="completed").info("knowledge fulltext engagement history rebuilt")
        return {"acquired": True, **summary}
    finally:
        await queue_repository.release_history_lock(token)


async def _reconcile_engagement() -> dict[str, int | bool]:
    service, queue_repository = await _build_service()
    token = uuid4().hex
    if not await queue_repository.acquire_history_lock(token):
        return {"acquired": False}
    try:
        summary = await service.reconcile_recent(now=datetime.now(timezone.utc))
        logger.bind(**summary, status="completed").info("knowledge fulltext engagement reconciled")
        return {"acquired": True, **summary}
    finally:
        await queue_repository.release_history_lock(token)
