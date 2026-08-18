"""Auto-publish Celery task.

Enqueued after file parse success when preconditions are met.
Executes on the default "celery" queue (100 threads) — not knowledge_celery
which is reserved for parsing.
"""

from __future__ import annotations

import logging

from bisheng.worker.main import bisheng_celery

logger = logging.getLogger(__name__)


@bisheng_celery.task(
    acks_late=True,
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def auto_publish_file_celery(self, file_id: int, tenant_id: int) -> None:
    """Attempt to auto-publish a file to the matching public space.

    Called by _try_enqueue_auto_publish after parse success.
    Uses exponential backoff for retries (10s, 20s, 40s).
    Runs on the default "celery" queue.
    """
    from bisheng.knowledge.domain.services.auto_publish_service import (
        AutoPublishService,
    )
    from bisheng.worker._asyncio_utils import run_async_task

    try:
        result = run_async_task(
            lambda: AutoPublishService.execute(
                file_id=file_id,
                tenant_id=tenant_id,
            )
        )
        if result.published:
            logger.info(
                "auto_publish_file_celery: published file_id=%s "
                "document_id=%s target_space_id=%s "
                "manager_file_id=%s publish_entry_id=%s idempotent=%s",
                file_id,
                result.document_id,
                result.target_space_id,
                result.manager_file_id,
                result.publish_entry_id,
                result.idempotent,
            )
        elif result.skipped:
            logger.debug(
                "auto_publish_file_celery: skipped file_id=%s reason=%s",
                file_id,
                result.skip_reason,
            )
    except Exception as exc:
        retry_count = self.request.retries
        logger.warning(
            "auto_publish_file_celery: failed file_id=%s tenant_id=%s retry=%s/%s error=%s",
            file_id,
            tenant_id,
            retry_count,
            self.max_retries,
            str(exc),
            exc_info=True,
        )
        try:
            # Exponential backoff: 10s * 2^retry_count
            backoff = 10 * (2**retry_count)
            self.retry(exc=exc, countdown=min(backoff, 120))
        except self.MaxRetriesExceededError:
            logger.error(
                "auto_publish_file_celery: max retries exceeded file_id=%s tenant_id=%s; giving up",
                file_id,
                tenant_id,
            )
