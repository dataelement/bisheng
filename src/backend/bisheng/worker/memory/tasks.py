"""Celery tasks of long-term memory (design decision 7, 20).

All five run on the default ``celery`` queue. Cross-tenant enumeration happens
inside ``bypass_tenant_filter()``; per-tenant work sets the tenant context first;
consolidation tasks carry the tenant in the message header so ``task_prerun``
restores it. Business logic lives in ``bisheng.memory``; this module schedules.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from loguru import logger

from bisheng.core.context.tenant import bypass_tenant_filter, current_tenant_id, set_current_tenant_id
from bisheng.memory.domain.config import aget_memory_config
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

SCAN_MARK_KEY = "memory:scan:last"


async def scan(kv, publish, now: datetime | None = None) -> int:
    """Find users with due sessions and publish one consolidation task each."""
    config = await aget_memory_config()
    if not config.auto_consolidation_enabled:
        return 0
    interval = config.scan_interval_minutes * 60
    if not await kv.acquire(SCAN_MARK_KEY, "1", max(interval - 5, 1)):
        return 0  # the configured scan interval has not elapsed yet
    from bisheng.memory.domain.services.activity import MemoryActivity

    now = now or datetime.now()
    with bypass_tenant_filter():
        users = await MemoryActivity.due_users(
            now, timedelta(minutes=config.quiet_minutes), timedelta(minutes=config.lock_ttl_minutes)
        )
    for tenant_id, user_id in users:
        publish(tenant_id, user_id)
    return len(users)


def publish_consolidation(tenant_id: int, user_id: int) -> None:
    consolidate_memory_user.apply_async(args=[tenant_id, user_id], headers={"tenant_id": tenant_id})


async def _tenant_ids() -> list[int]:
    from bisheng.memory.domain.repositories import _db
    from bisheng.memory.domain.models.memory_item import MemoryItem
    from sqlmodel import select

    with bypass_tenant_filter():
        async with _db.async_session() as s:
            return sorted(int(t) for t in (await s.exec(select(MemoryItem.tenant_id).distinct())).all())


async def for_each_tenant(work) -> None:
    for tenant_id in await _tenant_ids():
        token = set_current_tenant_id(tenant_id)
        try:
            await work(tenant_id)
        except Exception:
            # One tenant failing must not stop the rest; the task runs again later.
            logger.exception("memory per-tenant task failed tenant={}", tenant_id)
        finally:
            current_tenant_id.reset(token)


async def flush_metrics(metrics) -> None:
    today = datetime.now()
    with bypass_tenant_filter():
        await metrics.flush((today - timedelta(days=1)).strftime("%Y-%m-%d"))
        await metrics.flush(today.strftime("%Y-%m-%d"))


async def cleanup_turn_records() -> int:
    from bisheng.memory.domain.services.turn_record import TurnRecordService

    with bypass_tenant_filter():
        return await TurnRecordService.cleanup_orphans()


@bisheng_celery.task(name="bisheng.worker.memory.tasks.scan_memory_sessions")
def scan_memory_sessions() -> None:
    from bisheng.memory.domain.services.factory import get_kv

    try:
        run_async_task(lambda: scan(get_kv(), publish_consolidation))
    except Exception:
        logger.exception("memory scan failed")


@bisheng_celery.task(name="bisheng.worker.memory.tasks.consolidate_memory_user")
def consolidate_memory_user(tenant_id: int, user_id: int) -> None:
    from bisheng.memory.domain.services.factory import get_consolidator

    token = set_current_tenant_id(tenant_id)
    try:
        run_async_task(lambda: get_consolidator().consolidate_user(tenant_id, user_id))
    except Exception:
        logger.exception("memory consolidation task failed tenant={} user={}", tenant_id, user_id)
    finally:
        current_tenant_id.reset(token)


@bisheng_celery.task(name="bisheng.worker.memory.tasks.reconcile_memory")
def reconcile_memory() -> None:
    from bisheng.memory.domain.services.factory import get_memory_service
    from bisheng.memory.domain.services.reconcile import reconcile_tenant

    service = get_memory_service()
    try:
        run_async_task(lambda: for_each_tenant(lambda tid: reconcile_tenant(tid, service)))
    except Exception:
        logger.exception("memory reconcile failed")


@bisheng_celery.task(name="bisheng.worker.memory.tasks.flush_memory_metrics")
def flush_memory_metrics() -> None:
    from bisheng.memory.domain.services.factory import get_metrics

    try:
        run_async_task(lambda: flush_metrics(get_metrics()))
    except Exception:
        logger.exception("memory metrics flush failed")


@bisheng_celery.task(name="bisheng.worker.memory.tasks.cleanup_memory_turns")
def cleanup_memory_turns() -> None:
    try:
        run_async_task(cleanup_turn_records)
    except Exception:
        logger.exception("memory turn-record cleanup failed")
