"""Auto-publish Celery task.

Enqueued after file parse success when preconditions are met.
Executes on the default "celery" queue (100 threads) — not knowledge_celery
which is reserved for parsing.
"""

from __future__ import annotations

import logging

from bisheng.worker.main import bisheng_celery

logger = logging.getLogger(__name__)


@bisheng_celery.task(acks_late=True)
def auto_publish_file_celery(file_id: int, tenant_id: int) -> str:
    from bisheng.knowledge.domain.services.knowledge_background_service import KnowledgeBackgroundService
    from bisheng.worker._asyncio_utils import run_async_task
    from bisheng.core.context.tenant import current_tenant_id

    async def run():
        token = current_tenant_id.set(tenant_id)
        try:
            service = KnowledgeBackgroundService()
            files = await service.repository_call("files", [file_id])
            if not files:
                return "skipped"
            job_id = await service.repository_call("request_auto_publish", files[0])
            return await service.process(job_id, tenant_id) if job_id else "skipped"
        finally:
            current_tenant_id.reset(token)
    return run_async_task(run)
