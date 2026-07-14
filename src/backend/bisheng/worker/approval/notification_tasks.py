from __future__ import annotations

import logging

from bisheng.approval.domain.repositories.approval_notification_outbox_repository import (
    ApprovalNotificationOutboxRepository,
)
from bisheng.approval.domain.services.approval_notification_service import (
    ApprovalNotificationService,
)
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

logger = logging.getLogger(__name__)

LOCK_TTL_SECONDS = 120


@bisheng_celery.task(
    acks_late=True,
    time_limit=120,
    soft_time_limit=110,
    name="bisheng.worker.approval.notification_tasks.consume_approval_notification",
)
def consume_approval_notification(outbox_id: int, tenant_id: int) -> bool:
    redis = _get_redis()
    lock_key = f"bisheng:lock:approval_notification:{outbox_id}"
    if redis and not redis.setNx(lock_key, 1, expiration=LOCK_TTL_SECONDS):
        logger.debug("approval notification lock held: outbox_id=%s", outbox_id)
        return False
    try:
        return run_async_task(lambda: _consume_approval_notification_async(outbox_id, tenant_id))
    finally:
        if redis:
            redis.delete(lock_key)


@bisheng_celery.task(
    acks_late=True,
    time_limit=120,
    soft_time_limit=110,
    name="bisheng.worker.approval.notification_tasks.dispatch_approval_notifications",
)
def dispatch_approval_notifications() -> int:
    return run_async_task(_dispatch_approval_notifications_async)


async def _build_notification_service() -> ApprovalNotificationService:
    return ApprovalNotificationService()


async def _consume_approval_notification_async(outbox_id: int, tenant_id: int) -> bool:
    token = set_current_tenant_id(tenant_id)
    try:
        service = await _build_notification_service()
        return await service.consume(outbox_id)
    finally:
        current_tenant_id.reset(token)


async def _dispatch_approval_notifications_async() -> int:
    rows = await ApprovalNotificationOutboxRepository.list_dispatchable(limit=100)
    dispatched = 0
    for row in rows:
        try:
            consume_approval_notification.delay(int(row.id), int(row.tenant_id))
            dispatched += 1
        except Exception as exc:
            logger.exception(
                "approval notification beat dispatch failed: outbox_id=%s",
                row.id,
            )
            await ApprovalNotificationOutboxRepository.mark_failed(int(row.id), str(exc))
    return dispatched


def _get_redis():
    try:
        from bisheng.core.cache.redis_manager import get_redis_client_sync

        return get_redis_client_sync()
    except Exception:
        logger.warning("approval notification Redis lock unavailable", exc_info=True)
        return None
