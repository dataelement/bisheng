"""Guardrails for the tenant's canonical default root department.

The default root organization is referenced by ``tenant(root).root_dept_id``
and must keep ``parent_id IS NULL``. Every reparent entry point should call
``aassert_default_root_parent_immutable`` before mutating ``parent_id``.
"""

from __future__ import annotations

from bisheng.common.errcode.department import DepartmentDefaultRootMoveForbiddenError
from bisheng.database.models.department import Department, DepartmentDao
from bisheng.database.models.tenant import ROOT_TENANT_ID, TenantDao


async def aget_default_root_dept_id(tenant_id: int = ROOT_TENANT_ID) -> int | None:
    """Return the canonical root department id for ``tenant_id``, if configured."""
    tenant = await TenantDao.aget_by_id(int(tenant_id))
    if tenant is None or tenant.root_dept_id is None:
        return None
    return int(tenant.root_dept_id)


async def ais_default_root_department(
    dept: Department,
    *,
    tenant_id: int = ROOT_TENANT_ID,
) -> bool:
    """True when ``dept`` is the canonical default root for ``tenant_id``."""
    root_dept_id = await aget_default_root_dept_id(tenant_id)
    if root_dept_id is None or dept.id is None:
        return False
    return int(dept.id) == root_dept_id and int(dept.tenant_id or tenant_id) == int(tenant_id)


async def aassert_default_root_parent_immutable(
    dept_id: int,
    new_parent_id: int | None,
    *,
    tenant_id: int = ROOT_TENANT_ID,
) -> None:
    """Reject any ``parent_id`` change on the default root organization."""
    root_dept_id = await aget_default_root_dept_id(tenant_id)
    if root_dept_id is None or int(dept_id) != root_dept_id:
        return

    dept = await DepartmentDao.aget_by_id(int(dept_id))
    if dept is None:
        return

    current_parent_id = dept.parent_id
    if (current_parent_id or 0) == (new_parent_id or 0):
        return

    raise DepartmentDefaultRootMoveForbiddenError()
