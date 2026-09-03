"""Celery beat task: retry persisted permission relation operations.

Runs every 30 seconds via beat schedule. Uses a Redis distributed lock to
prevent concurrent processing of the same pending tuples.

Retry policy:
  - Max 3 attempts (configurable per-tuple via max_retries)
  - Success → status='succeeded'
  - Failure within limit → retry_count++, error_message updated
  - Failure at limit → status='dead', logger.critical alert
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from bisheng.worker.main import bisheng_celery

logger = logging.getLogger(__name__)

LOCK_KEY = "bisheng:lock:retry_failed_tuples"
LOCK_TTL = 60  # seconds — must be > typical execution time


@bisheng_celery.task(acks_late=True)
def retry_failed_tuples():
    """Retry pending failed tuple operations."""
    _retry_failed_tuples_sync()


@bisheng_celery.task(acks_late=True)
def cleanup_succeeded_failed_tuples():
    """Delete succeeded compensation records after their retention period."""
    from bisheng.worker._asyncio_utils import run_async_task

    run_async_task(_cleanup_succeeded_failed_tuples)


async def _cleanup_succeeded_failed_tuples(*, now: datetime | None = None) -> int:
    from bisheng.common.services.config_service import settings
    from bisheng.database.models.failed_tuple import FailedTupleDao

    retention_days = settings.openfga.failed_tuple_succeeded_retention_days
    cutoff = (now or datetime.now()) - timedelta(days=retention_days)
    deleted = await FailedTupleDao.adelete_old_succeeded(cutoff)
    logger.info(
        "Cleaned up %d succeeded permission compensation records older than %d days",
        deleted,
        retention_days,
    )
    return deleted


def _retry_failed_tuples_sync() -> None:
    """Sync implementation: acquire lock, batch writes, then batch deletes."""
    from bisheng.database.models.failed_tuple import FailedTupleDao
    from bisheng.permission.application import get_permission_relation_api
    from bisheng.worker._asyncio_utils import run_async_task

    # Distributed lock to prevent concurrent Beat fires from processing same rows
    redis = _get_redis()
    if redis:
        acquired = redis.setNx(LOCK_KEY, 1, expiration=LOCK_TTL)
        if not acquired:
            logger.debug("retry_failed_tuples: lock held by another worker, skipping")
            return
    try:
        pending = FailedTupleDao.get_pending(limit=100)
        if not pending:
            return

        logger.info("Processing %d pending permission relations", len(pending))

        permissions = run_async_task(get_permission_relation_api)

        write_items = [item for item in pending if item.action == "write"]
        delete_items = [item for item in pending if item.action == "delete"]

        _retry_batch(permissions, write_items, "write", FailedTupleDao, run_async_task)
        _retry_batch(permissions, delete_items, "delete", FailedTupleDao, run_async_task)
    finally:
        # Release lock
        if redis:
            redis.delete(LOCK_KEY)


def _retry_batch(permissions, items, action: str, dao, run_async_task) -> None:
    """Attempt a batch permission mutation, then fall back to individual retries."""
    if not items:
        return

    from bisheng.permission.application.relation_api import _permission_relation_from_legacy_tuple

    relations = tuple(
        _permission_relation_from_legacy_tuple(
            user=item.fga_user,
            relation=item.relation,
            object_key=item.object,
        )
        for item in items
    )

    try:
        if action == "write":
            run_async_task(lambda: permissions.grant(relations))
        else:
            run_async_task(lambda: permissions.revoke(relations))

        for item in items:
            dao.update_succeeded(item.id)
        logger.info("Batch retry succeeded for %d %s permission relations", len(items), action)

    except Exception:
        logger.debug("Batch %s failed, falling back to per-item retry", action)
        for item in items:
            _retry_single(permissions, item, action, dao, run_async_task)


def _retry_single(permissions, item, action: str, dao, run_async_task) -> None:
    """Retry one persisted permission relation and update its status."""
    try:
        from bisheng.permission.application.relation_api import _permission_relation_from_legacy_tuple

        relation = _permission_relation_from_legacy_tuple(
            user=item.fga_user,
            relation=item.relation,
            object_key=item.object,
        )
        if action == "write":
            run_async_task(lambda: permissions.grant((relation,)))
        else:
            run_async_task(lambda: permissions.revoke((relation,)))

        dao.update_succeeded(item.id)

    except Exception as e:
        error_msg = str(e)[:500]
        if _is_idempotent_tuple_error(action, error_msg):
            dao.update_succeeded(item.id)
            logger.info(
                "Ignoring idempotent permission %s failure for FailedTuple %d: %s",
                action,
                item.id,
                error_msg,
            )
            return

        if item.retry_count + 1 >= item.max_retries:
            dao.mark_dead(item.id, error_msg)
            logger.critical(
                "FailedTuple %d exceeded max retries (%d), marked as dead. "
                "Action=%s user=%s relation=%s object=%s error=%s",
                item.id,
                item.max_retries,
                item.action,
                item.fga_user,
                item.relation,
                item.object,
                error_msg,
            )
        else:
            dao.update_retry(item.id, error_msg)
            logger.warning(
                "Retry %d/%d failed for FailedTuple %d: %s",
                item.retry_count + 1,
                item.max_retries,
                item.id,
                error_msg,
            )


def _get_redis():
    """Get RedisClient. Returns None if unavailable."""
    try:
        from bisheng.core.cache.redis_manager import get_redis_client_sync

        return get_redis_client_sync()
    except Exception:
        return None


def _is_idempotent_tuple_error(action: str, error_msg: str) -> bool:
    text = error_msg.lower()
    if action == "write":
        return "already exists" in text or "cannot write a tuple which already exists" in text
    if action == "delete":
        return "does not exist" in text or "did not exist" in text or "tuple to be deleted did not exist" in text
    return False
