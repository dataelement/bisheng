"""Batch drift detection for user leaf-tenant reconciliation.

The write path remains :class:`UserTenantSyncService`; this service only
pre-computes which users are likely to need that write path. It keeps the
six-hour safety net cheap when most assignments are already consistent.
"""

from dataclasses import dataclass

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
from bisheng.database.models.tenant import ROOT_TENANT_ID, TenantDao, UserTenantDao


@dataclass(frozen=True)
class UserTenantReconcileContext:
    mount_tenant_by_department: dict[int, int]
    active_tenant_ids: frozenset[int]


class UserTenantReconcileService:
    """Find drifted users with batched read-only lookups."""

    @classmethod
    async def load_context(cls) -> UserTenantReconcileContext:
        """Load topology shared by every user batch in one reconcile run."""
        with bypass_tenant_filter():
            mount_tenant_by_department = await DepartmentDao.aget_mount_tenant_ids()
            active_tenant_ids = await TenantDao.aget_active_ids()
        return UserTenantReconcileContext(
            mount_tenant_by_department=mount_tenant_by_department,
            active_tenant_ids=frozenset(active_tenant_ids),
        )

    @classmethod
    async def find_drifted_user_ids(
        cls,
        user_ids: list[int],
        context: UserTenantReconcileContext,
    ) -> list[int]:
        """Return users whose active snapshot differs from tree derivation."""
        if not user_ids:
            return []

        with bypass_tenant_filter():
            primary_departments = await UserDepartmentDao.aget_primary_department_paths_by_user_ids(user_ids)
            current_tenants = await UserTenantDao.aget_active_tenant_ids_by_user_ids(user_ids)

        drifted: list[int] = []
        for user_id in user_ids:
            expected_tenant_id = cls.expected_tenant_id(
                primary_departments.get(user_id),
                context,
            )
            if current_tenants.get(user_id) != expected_tenant_id:
                drifted.append(user_id)
        return drifted

    @staticmethod
    def expected_tenant_id(
        primary_department: tuple[int, str] | None,
        context: UserTenantReconcileContext,
    ) -> int:
        """Mirror ``TenantResolver`` using a preloaded mount topology."""
        if primary_department is None:
            return ROOT_TENANT_ID

        department_id, path = primary_department
        ancestor_ids = [int(part) for part in (path or "").split("/") if part.isdigit()]
        if department_id not in ancestor_ids:
            ancestor_ids.append(department_id)

        for ancestor_id in reversed(ancestor_ids):
            tenant_id = context.mount_tenant_by_department.get(ancestor_id)
            if tenant_id in context.active_tenant_ids:
                return tenant_id
        return ROOT_TENANT_ID
