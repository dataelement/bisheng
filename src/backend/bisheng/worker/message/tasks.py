"""Celery tasks for Shougang enterprise WeChat message push."""

import logging

from bisheng.core.cache.redis_manager import get_redis_client_sync
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery
from bisheng.worker.message.outbox_processor import WeChatOutboxProcessor

logger = logging.getLogger(__name__)

LOCK_KEY = "bisheng:lock:scan_wechat_message_push_outbox"
LOCK_TTL = 60  # seconds


@bisheng_celery.task(
    acks_late=True,
    time_limit=300,
    soft_time_limit=240,
    name="bisheng.worker.message.tasks.scan_wechat_message_push_outbox",
)
def scan_wechat_message_push_outbox() -> int:
    """Beat task: scan pending outbox records and dispatch push tasks."""
    redis = _get_redis()
    if redis:
        acquired = redis.setNx(LOCK_KEY, 1, expiration=LOCK_TTL)
        if not acquired:
            logger.debug("scan_wechat_message_push_outbox: lock held, skipping")
            return 0
    try:
        return run_async_task(lambda: _scan_async())
    finally:
        if redis:
            try:
                redis.delete(LOCK_KEY)
            except Exception as exc:
                logger.warning("Failed to release scan lock: %s", exc)


@bisheng_celery.task(
    acks_late=True,
    time_limit=120,
    soft_time_limit=90,
    name="bisheng.worker.message.tasks.push_single_wechat_message",
)
def push_single_wechat_message(outbox_id: int) -> bool:
    """Push a single outbox record via Shougang MADC API."""
    return run_async_task(lambda: _push_async(outbox_id))


async def _scan_async() -> int:
    processor = WeChatOutboxProcessor()
    return await processor.scan_and_dispatch()


async def _push_async(outbox_id: int) -> bool:
    processor = WeChatOutboxProcessor()
    return await processor.push_one(outbox_id)


def _get_redis():
    """Return a sync Redis client, or None if Redis is unavailable."""
    try:
        return get_redis_client_sync()
    except Exception as exc:
        logger.warning("Redis unavailable for WeChat push lock: %s", exc)
        return None
