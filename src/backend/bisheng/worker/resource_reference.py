"""Ordinary, tenant-routed retry of auxiliary reference hints."""

from loguru import logger
from sqlalchemy.exc import SQLAlchemyError

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.resource_reference.application.source_sync import refresh_root
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery


@bisheng_celery.task(
    bind=True, name="bisheng.worker.resource_reference.sync_reference_root", acks_late=True, max_retries=5
)
def sync_reference_root(self, *, tenant_id, source_type, source_id):
    header = (self.request.headers or {}).get("tenant_id")
    if type(tenant_id) is not int or tenant_id <= 0 or str(header) != str(tenant_id):
        raise ValueError("reference sync tenant header mismatch")
    try:
        return run_async_task(lambda: refresh_root(tenant_id, source_type, source_id))
    except (SQLAlchemyError, BaseErrorCode, ValueError, TypeError, KeyError) as error:
        logger.error(
            "Reference sync failed tenant={} type={} source={} task={} retry={} error={}",
            tenant_id,
            source_type,
            source_id,
            self.request.id,
            self.request.retries,
            type(error).__name__,
        )
        intervals = (10, 30, 60, 120, 300)
        raise self.retry(exc=error, countdown=intervals[min(self.request.retries, len(intervals) - 1)])
