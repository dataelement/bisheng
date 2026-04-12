"""Celery beat task: retry failed OpenFGA tuple operations (T10, AC-04).

Runs every 30 seconds via beat schedule. Picks up pending FailedTuples,
retries the write/delete via FGAClient, and updates status accordingly.

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


@bisheng_celery.task(acks_late=True)
def retry_failed_tuples():
    """Retry pending failed tuple operations."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_retry_failed_tuples_async())
    finally:
        loop.close()


async def _retry_failed_tuples_async():
    """Async implementation of the retry logic."""
    from bisheng.database.models.failed_tuple import FailedTupleDao

    pending = await FailedTupleDao.aget_pending(limit=100)
    if not pending:
        return

    logger.info('Processing %d pending failed tuples', len(pending))

    fga = _get_fga_client()
    if fga is None:
        logger.warning('FGAClient not available, skipping retry cycle')
        return

    for item in pending:
        try:
            tuple_dict = {
                'user': item.fga_user,
                'relation': item.relation,
                'object': item.object,
            }

            if item.action == 'write':
                await fga.write_tuples(writes=[tuple_dict])
            elif item.action == 'delete':
                await fga.write_tuples(deletes=[tuple_dict])
            else:
                logger.warning('Unknown action %s for FailedTuple %d', item.action, item.id)
                continue

            # Success
            await FailedTupleDao.aupdate_succeeded(item.id)
            logger.debug('Retry succeeded for FailedTuple %d', item.id)

        except Exception as e:
            error_msg = str(e)[:500]

            if item.retry_count + 1 >= item.max_retries:
                # Exceeded max retries — mark as dead
                await FailedTupleDao.amark_dead(item.id, error_msg)
                logger.critical(
                    'FailedTuple %d exceeded max retries (%d), marked as dead. '
                    'Action=%s user=%s relation=%s object=%s error=%s',
                    item.id, item.max_retries, item.action,
                    item.fga_user, item.relation, item.object, error_msg,
                )
            else:
                # Increment retry count
                await FailedTupleDao.aupdate_retry(item.id, error_msg)
                logger.warning(
                    'Retry %d/%d failed for FailedTuple %d: %s',
                    item.retry_count + 1, item.max_retries, item.id, error_msg,
                )


def _get_fga_client():
    """Get FGAClient instance. Returns None if unavailable."""
    try:
        from bisheng.core.openfga.manager import get_fga_client
        return get_fga_client()
    except Exception:
        return None
