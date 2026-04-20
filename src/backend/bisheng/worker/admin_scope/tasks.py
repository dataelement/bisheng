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

import asyncio
import logging

from bisheng.worker.main import bisheng_celery

logger = logging.getLogger(__name__)


@bisheng_celery.task(
    acks_late=True,
    time_limit=600,
    soft_time_limit=540,
    name='bisheng.worker.admin_scope.tasks.admin_scope_cleanup',
)
def admin_scope_cleanup():
    """Kickoff — hands control to the asyncio loop."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_cleanup_async())
    finally:
        loop.close()


async def _cleanup_async() -> None:
    """Delete ``admin_scope:{user_id}`` keys whose Tenant is no longer active.

    Fast path: if no scope keys exist, skip the DB query altogether.
    """
    from bisheng.core.cache.redis_manager import get_redis_client
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.database.models.tenant import TenantDao

    redis = await get_redis_client()
    keys = await redis.akeys('admin_scope:*')
    if not keys:
        return

    # Cross-tenant read — without the bypass, the tenant_filter event
    # listener's behaviour when current_tenant_id is None is undefined.
    with bypass_tenant_filter():
        non_active = set(await TenantDao.aget_non_active_ids())

    if not non_active:
        return  # All tenants active — all scope keys still valid.

    deleted = 0
    for key in keys:
        try:
            raw = await redis.aget(key)
        except Exception as exc:  # noqa: BLE001
            logger.debug('admin_scope_cleanup: read %s failed: %s', key, exc)
            continue
        if raw is None:
            continue
        try:
            scope_id = int(raw)
        except (TypeError, ValueError):
            # Corrupt value — treat as stale and remove.
            await redis.adelete(key)
            deleted += 1
            continue
        if scope_id in non_active:
            await redis.adelete(key)
            deleted += 1

    logger.info(
        'admin_scope_cleanup done: total_keys=%d non_active_tenants=%d deleted=%d',
        len(keys), len(non_active), deleted,
    )
