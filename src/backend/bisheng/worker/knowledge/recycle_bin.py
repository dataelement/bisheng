"""Celery tasks for knowledge recycle-bin maintenance."""

from __future__ import annotations

from loguru import logger

from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery


@bisheng_celery.task(
    name="bisheng.worker.knowledge.recycle_bin.purge_expired_recycle_items",
    acks_late=True,
)
def purge_expired_recycle_items_celery(_task=None):
    """Daily beat: hard-delete recycle items past expire_at."""
    from bisheng.knowledge.domain.services.knowledge_recycle_service import KnowledgeRecycleService

    count = run_async_task(KnowledgeRecycleService.purge_expired_items)
    logger.info("purge_expired_recycle_items done count={}", count)
    return {"purged": count}
