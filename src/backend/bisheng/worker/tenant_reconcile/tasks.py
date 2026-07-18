"""Celery task — 6h reconcile of user leaf-tenant assignments (F012).

The login-time and primary-department-change hooks already keep
``user_tenant`` in sync with each user's primary department. This task
is a catch-all safety net for cases where:
  - A user's primary department was updated by a legacy path that
    bypassed ``UserDepartmentService``.
  - An earlier login raised an exception inside sync_user and the user
    is now looking at a stale leaf tenant.
  - Tenant lifecycle changes (mount/unmount/disable) invalidated
    previously-active leaf assignments.

Every 6h we keyset-page the user table and batch-derive expected assignments.
Only drifted users enter ``UserTenantSyncService.sync_user``. A
``TenantRelocateBlockedError`` from enforce_transfer_before_relocate=True is
swallowed (already audited by the service) so one blocked relocation cannot
stop the scan.

The scheduled entry is registered by ``CeleryConf.validate`` in
``bisheng.core.config.settings``.
"""

import logging

from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


@bisheng_celery.task(acks_late=True, time_limit=3600, soft_time_limit=3000)
def reconcile_user_tenant_assignments():
    run_async_task(_reconcile_async)


async def _reconcile_async() -> None:
    """Batch-detect drift and sync only inconsistent active users."""
    from bisheng.common.errcode.tenant_resolver import TenantRelocateBlockedError
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.tenant.domain.constants import UserTenantSyncTrigger
    from bisheng.tenant.domain.services.user_tenant_reconcile_service import (
        UserTenantReconcileService,
    )
    from bisheng.tenant.domain.services.user_tenant_sync_service import (
        UserTenantSyncService,
    )
    from bisheng.user.domain.models.user import UserDao

    context = await UserTenantReconcileService.load_context()
    last_user_id = 0
    processed = 0
    unchanged = 0
    synced = 0
    blocked = 0
    failed = 0

    # ``bypass_tenant_filter`` wraps the whole scan because we iterate across
    # tenants; sync_user itself also uses ``bypass_tenant_filter`` internally
    # via TenantResolver, but wrapping here keeps the UserDao page read open.
    # The nesting is safe under sequential execution — each inner CM uses its
    # own reset token that doesn't affect the outer scope. If this loop is
    # ever changed to ``asyncio.gather``, move the bypass inside sync_user
    # so ContextVar tokens aren't shared across concurrent coroutines.
    with bypass_tenant_filter():
        while True:
            users = await UserDao.alist_users_after_id(
                last_user_id=last_user_id,
                limit=BATCH_SIZE,
            )
            if not users:
                break
            user_ids = [int(user.user_id) for user in users]
            drifted_user_ids = await UserTenantReconcileService.find_drifted_user_ids(
                user_ids,
                context,
            )
            processed += len(user_ids)
            unchanged += len(user_ids) - len(drifted_user_ids)

            for user_id in drifted_user_ids:
                try:
                    await UserTenantSyncService.sync_user(
                        user_id,
                        trigger=UserTenantSyncTrigger.CELERY_RECONCILE,
                    )
                    synced += 1
                except TenantRelocateBlockedError:
                    blocked += 1
                    # Already written as ``user.tenant_relocate_blocked`` in audit_log.
                except Exception as exc:
                    failed += 1
                    logger.error(
                        "reconcile_user_tenant: sync_user(%d) failed: %s",
                        user_id,
                        exc,
                    )
            last_user_id = user_ids[-1]

    logger.info(
        "reconcile_user_tenant_assignments done: processed=%d unchanged=%d synced=%d blocked=%d failed=%d",
        processed,
        unchanged,
        synced,
        blocked,
        failed,
    )
