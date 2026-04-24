"""UserDepartmentService — transactional primary-department change entry point.

v2.5.1 F012: encapsulates the "promote department X to primary, demote the
old primary" flow and fires ``UserTenantSyncService.sync_user`` as the final
transactional step so the user's leaf-tenant assignment stays in lockstep
with their primary-department assignment.

Secondary-department (``is_primary=0``) add/remove flows do NOT go through
this service (AC-07) — the caller would use ``UserDepartmentDao.aadd_member``
/ ``aremove_member`` directly, which intentionally skips sync_user.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import update

from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import (
    UserDepartment,
    UserDepartmentDao,
)
from bisheng.department.domain.services.department_change_handler import (
    DepartmentChangeHandler,
)
from bisheng.tenant.domain.constants import UserTenantSyncTrigger
from bisheng.tenant.domain.services.user_tenant_sync_service import (
    UserTenantSyncService,
)

logger = logging.getLogger(__name__)


class UserDepartmentService:
    """Stateless service — classmethod only."""

    @classmethod
    async def change_primary_department(
        cls,
        user_id: int,
        new_dept_id: int,
    ) -> dict[str, Any]:
        """Swap ``is_primary`` from the old primary to ``new_dept_id``.

        Behaviour:
          - No-op (returns the current state) when ``new_dept_id`` equals
            the existing primary's ``department_id``.
          - Otherwise: demote the old primary row (if any), upsert the new
            primary row with ``is_primary=1``, then call
            ``UserTenantSyncService.sync_user`` which handles the leaf
            tenant swap + audit + FGA rewrite.

        Raises ``TenantRelocateBlockedError`` (propagated from
        ``sync_user``) when the user owns resources under the old tenant
        and ``enforce_transfer_before_relocate`` is set.

        **Ordering caveat**: the UserDepartment rows are committed BEFORE
        ``sync_user`` runs so the resolver can see the new primary. If
        sync_user raises (typically ``TenantRelocateBlockedError``) the
        UserDepartment change is already persisted — the user's new
        primary department stands, but their leaf-tenant assignment has
        NOT switched. The 6h Celery reconcile (F012 T11) converges this
        on the next tick, and a subsequent login also re-attempts the
        sync. If you need strict all-or-nothing semantics, wrap the
        caller in a SAVEPOINT and rewind the primary-dept change on
        ``TenantRelocateBlockedError`` yourself.
        """
        current_primary = await UserDepartmentDao.aget_user_primary_department(
            user_id,
        )
        if current_primary and current_primary.department_id == new_dept_id:
            # Same primary — skip DB writes and the sync_user call
            # (sync would also be a no-op, but saving the audit/FGA
            # work is meaningful under bulk rekey operations).
            return {
                'user_id': user_id,
                'primary_department_id': new_dept_id,
                'leaf_tenant_id': None,
                'changed': False,
            }

        async with get_async_db_session() as session:
            if current_primary is not None:
                await session.exec(
                    update(UserDepartment)
                    .where(
                        UserDepartment.user_id == user_id,
                        UserDepartment.department_id == current_primary.department_id,
                    )
                    .values(is_primary=0)
                )

            # Upsert the new primary row. If the user already belongs to
            # new_dept_id as a secondary, promote it; otherwise insert.
            existing_secondary = await session.exec(
                _select_user_dept(user_id, new_dept_id)
            )
            row = existing_secondary.first()
            if row is None:
                session.add(UserDepartment(
                    user_id=user_id,
                    department_id=new_dept_id,
                    is_primary=1,
                ))
            else:
                await session.exec(
                    update(UserDepartment)
                    .where(
                        UserDepartment.user_id == user_id,
                        UserDepartment.department_id == new_dept_id,
                    )
                    .values(is_primary=1)
                )
            await session.commit()

        ops = DepartmentChangeHandler.on_members_added(new_dept_id, [user_id])
        await DepartmentChangeHandler.execute_async(ops)

        # Fire the leaf-tenant sync AFTER the DB write is committed so the
        # resolver can see the new primary. sync_user may raise
        # TenantRelocateBlockedError — let it propagate; the caller (API
        # endpoint or org-sync worker) handles the 409 translation.
        leaf = await UserTenantSyncService.sync_user(
            user_id, trigger=UserTenantSyncTrigger.DEPT_CHANGE,
        )

        return {
            'user_id': user_id,
            'primary_department_id': new_dept_id,
            'leaf_tenant_id': getattr(leaf, 'id', None),
            'changed': True,
        }


def _select_user_dept(user_id: int, department_id: int):
    """Reusable ``SELECT`` statement for the user+dept composite lookup."""
    from sqlmodel import select
    return select(UserDepartment).where(
        UserDepartment.user_id == user_id,
        UserDepartment.department_id == department_id,
    )
