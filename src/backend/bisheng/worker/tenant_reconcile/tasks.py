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

Every 6h we walk the user table in batches, calling
``UserTenantSyncService.sync_user`` per user. A ``TenantRelocateBlockedError``
from enforce_transfer_before_relocate=True is swallowed (already audited
by the service) so one user's blocked relocation can't stop the scan.

The scheduled entry is registered by ``CeleryConf.validate`` in
``bisheng.core.config.settings``.
"""

import asyncio
import logging

from bisheng.worker.main import bisheng_celery

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


@bisheng_celery.task(acks_late=True, time_limit=3600, soft_time_limit=3000)
def reconcile_user_tenant_assignments():
    """Kickoff — hands control to the asyncio loop."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_reconcile_async())
    finally:
        loop.close()


async def _reconcile_async() -> None:
    """Page through every active user, call sync_user with a reconcile trigger."""
    from bisheng.common.errcode.tenant_resolver import TenantRelocateBlockedError
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.tenant.domain.constants import UserTenantSyncTrigger
    from bisheng.tenant.domain.services.user_tenant_sync_service import (
        UserTenantSyncService,
    )
    from bisheng.user.domain.models.user import UserDao

    offset = 0
    processed = 0
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
            users = await UserDao.alist_users_paginated(
                offset=offset, limit=BATCH_SIZE,
            )
            if not users:
                break
            for u in users:
                processed += 1
                try:
                    await UserTenantSyncService.sync_user(
                        u.user_id,
                        trigger=UserTenantSyncTrigger.CELERY_RECONCILE,
                    )
                    synced += 1
                except TenantRelocateBlockedError:
                    blocked += 1
                    # Already written as ``user.tenant_relocate_blocked`` in audit_log.
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    logger.error(
                        'reconcile_user_tenant: sync_user(%d) failed: %s',
                        u.user_id, exc,
                    )
            offset += BATCH_SIZE

    logger.info(
        'reconcile_user_tenant_assignments done: processed=%d synced=%d '
        'blocked=%d failed=%d',
        processed, synced, blocked, failed,
    )
