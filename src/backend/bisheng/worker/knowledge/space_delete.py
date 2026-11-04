"""Tenant-routed deletion cleanup with durable periodic recovery."""

from loguru import logger

from bisheng.knowledge.domain.services.knowledge_space_direct_delete_service import (
    KnowledgeSpaceDirectDeleteService,
    dispatch_delete_job,
)
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

PURGE_TASK = "bisheng.worker.knowledge.space_delete.purge_space_delete"
SCAN_TASK = "bisheng.worker.knowledge.space_delete.dispatch_pending_deletes"


@bisheng_celery.task(bind=True, name=PURGE_TASK, acks_late=True, max_retries=3)
def purge_space_delete(self, *, job_id: str):
    try:
        return run_async_task(lambda: KnowledgeSpaceDirectDeleteService().purge(job_id))
    except Exception as exc:
        logger.exception("Knowledge delete cleanup failed job={}", job_id)
        raise self.retry(exc=exc, countdown=60)


async def _dispatch_pending() -> int:
    jobs = await KnowledgeSpaceDirectDeleteService().repository.due_jobs()
    dispatched = 0
    for tenant_id, job_id in jobs:
        try:
            await dispatch_delete_job(tenant_id=tenant_id, job_id=job_id)
            dispatched += 1
        except Exception:
            logger.exception("Knowledge delete dispatch failed tenant={} job={}", tenant_id, job_id)
    return dispatched


@bisheng_celery.task(name=SCAN_TASK, acks_late=True)
def dispatch_pending_deletes():
    return run_async_task(_dispatch_pending)
