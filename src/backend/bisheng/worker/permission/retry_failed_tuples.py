"""Celery beat task: retry failed OpenFGA tuple operations (T10, AC-04).

Runs every 30 seconds via beat schedule. Uses a Redis distributed lock to
prevent concurrent processing of the same pending tuples.

Retry policy:
  - Max 3 attempts (configurable per-tuple via max_retries)
  - Success → status='succeeded'
  - Failure within limit → retry_count++, error_message updated
  - Failure at limit → status='dead', logger.critical alert
"""

from __future__ import annotations

import asyncio
import logging

from bisheng.worker.main import bisheng_celery

logger = logging.getLogger(__name__)

LOCK_KEY = 'bisheng:lock:retry_failed_tuples'
LOCK_TTL = 60  # seconds — must be > typical execution time


@bisheng_celery.task(acks_late=True)
def retry_failed_tuples():
    """Retry pending failed tuple operations."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_retry_failed_tuples_async())
    finally:
        loop.close()


async def _retry_failed_tuples_async():
    """Async implementation: acquire lock, batch writes, then batch deletes."""
    from bisheng.database.models.failed_tuple import FailedTupleDao
    from bisheng.core.openfga.manager import get_fga_client

    # Distributed lock to prevent concurrent Beat fires from processing same rows
    redis = await _get_redis()
    if redis:
        acquired = await redis.asetNx(LOCK_KEY, 1, expiration=LOCK_TTL)
        if not acquired:
            logger.debug('retry_failed_tuples: lock held by another worker, skipping')
            return
    try:
        pending = await FailedTupleDao.aget_pending(limit=100)
        if not pending:
            return

        logger.info('Processing %d pending failed tuples', len(pending))

        fga = get_fga_client()
        if fga is None:
            logger.warning('FGAClient not available, skipping retry cycle')
            return

        write_items = [item for item in pending if item.action == 'write']
        delete_items = [item for item in pending if item.action == 'delete']

        await _retry_batch(fga, write_items, 'write', FailedTupleDao)
        await _retry_batch(fga, delete_items, 'delete', FailedTupleDao)
    finally:
        # Release lock
        if redis:
            await redis.adelete(LOCK_KEY)


async def _retry_batch(fga, items, action: str, dao) -> None:
    """Attempt a batch FGA call; on failure, fall back to per-item retry."""
    if not items:
        return

    tuples = [
        {'user': item.fga_user, 'relation': item.relation, 'object': item.object}
        for item in items
    ]

    try:
        if action == 'write':
            await fga.write_tuples(writes=tuples)
        else:
            await fga.write_tuples(deletes=tuples)

        for item in items:
            await dao.aupdate_succeeded(item.id)
        logger.info('Batch retry succeeded for %d %s tuples', len(items), action)

    except Exception:
        logger.debug('Batch %s failed, falling back to per-item retry', action)
        for item in items:
            await _retry_single(fga, item, action, dao)


async def _retry_single(fga, item, action: str, dao) -> None:
    """Retry a single tuple. Update status based on result."""
    try:
        tuple_dict = {
            'user': item.fga_user, 'relation': item.relation, 'object': item.object,
        }
        if action == 'write':
            await fga.write_tuples(writes=[tuple_dict])
        else:
            await fga.write_tuples(deletes=[tuple_dict])

        await dao.aupdate_succeeded(item.id)

    except Exception as e:
        error_msg = str(e)[:500]
        if item.retry_count + 1 >= item.max_retries:
            await dao.amark_dead(item.id, error_msg)
            logger.critical(
                'FailedTuple %d exceeded max retries (%d), marked as dead. '
                'Action=%s user=%s relation=%s object=%s error=%s',
                item.id, item.max_retries, item.action,
                item.fga_user, item.relation, item.object, error_msg,
            )
        else:
            await dao.aupdate_retry(item.id, error_msg)
            logger.warning(
                'Retry %d/%d failed for FailedTuple %d: %s',
                item.retry_count + 1, item.max_retries, item.id, error_msg,
            )


async def _get_redis():
    """Get RedisClient. Returns None if unavailable."""
    try:
        from bisheng.core.cache.redis_manager import get_redis_client
        return await get_redis_client()
    except Exception:
        return None
