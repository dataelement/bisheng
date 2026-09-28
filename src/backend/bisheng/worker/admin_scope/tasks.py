"""Celery task — 10min sweep of admin_scope Redis keys (F019 AC-13).

When a Child Tenant is disabled / archived / orphaned / deleted, any
live ``admin_scope:{user_id}=Child_id`` Redis keys pointing at that
tenant become stale — the super admin still has the scope set, but
queries filtered by that tenant now return empty. Spec AD-07 deliberately
chose Celery sweep over a synchronous hook to keep the Tenant
disable/archive hot path free of Redis scans; the 10-minute cadence
gives an upper bound of ≈10 minutes on the stale-key window.

**Tenant context note** (spec §5.4): Celery workers run without a request
context, so ``current_tenant_id`` ContextVar is None. The non-active id
lookup must be wrapped with ``bypass_tenant_filter()``; otherwise
SQLAlchemy's auto-injected tenant filter on ``tenant`` rows is undefined.

The scheduled entry is registered by ``CeleryConf.validate`` in
``bisheng.core.config.settings``.
"""

import logging

from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

logger = logging.getLogger(__name__)


@bisheng_celery.task(
    acks_late=True,
    time_limit=600,
    soft_time_limit=540,
    name="bisheng.worker.admin_scope.tasks.admin_scope_cleanup",
)
def admin_scope_cleanup():
    run_async_task(_cleanup_async)


async def _cleanup_async() -> None:
    """分页扫描并删除失效范围，保留扫描后的并发更新。"""
    import pickle

    from bisheng.core.cache.redis_manager import get_redis_client
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.database.models.tenant import TenantDao

    redis = await get_redis_client()
    non_active = None
    total = deleted = 0
    async for keys in redis.ascan_batches("admin_scope:*", batch_size=200):
        if non_active is None:
            with bypass_tenant_filter():
                non_active = set(await TenantDao.aget_non_active_ids())
            if not non_active:
                return
        values = await redis.aget_raw_many(keys)
        stale = []
        total += len(keys)
        for key, raw in zip(keys, values):
            if raw is None:
                continue
            try:
                value = pickle.loads(raw)
                if value is None:
                    continue
                expired = int(value) in non_active
            except (ValueError, TypeError, pickle.UnpicklingError, EOFError):
                logger.warning("管理员范围值无效 key=%s", key)
                expired = True
            if expired:
                stale.append((key, raw))
        deleted += await redis.adelete_unchanged_many(stale)
    logger.info("admin_scope_cleanup done: total_keys=%d deleted=%d", total, deleted)
