"""Department reads behind the audit organisation picker (F003 design §6.1).

Every query is bounded by the caller's ``AuditDeptScope`` closure plus the
audit tenant, and runs with the tenant filter bypassed: the scope is the
boundary here, and a global super's picker spans tenants on purpose.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import false, or_
from sqlalchemy.orm import aliased
from sqlmodel import col, select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import Department
from bisheng.database.models.org_snapshot import DEPT_STATUS_ACTIVE, AuditDeptScope

DEPT_STATUS_ARCHIVED = "archived"


def _in_audit_tenant(dept, tenant_scope: int):
    """Departments the audit tenant may offer.

    A child tenant's departments stay on the parent tree: ``tenant_id`` is the
    parent. The subtree is the tenant's ``root_dept_id``, and also a mount
    flagged with ``mounted_tenant_id``. Matching only ``tenant_id`` hides that
    whole subtree, which is why a tenant administrator's picker was empty
    while a platform super still saw every organisation.
    """
    from bisheng.database.models.tenant import Tenant

    mount = aliased(Department)
    under_mount = (
        select(mount.id)
        .where(
            mount.is_deleted == 0,
            mount.is_tenant_root == 1,
            mount.mounted_tenant_id == tenant_scope,
            mount.path != "",
            dept.path.startswith(mount.path),
        )
        .exists()
    )
    root = aliased(Department)
    under_root = (
        select(root.id)
        .join(Tenant, Tenant.root_dept_id == root.id)
        .where(
            Tenant.id == tenant_scope,
            root.is_deleted == 0,
            root.path != "",
            dept.path.startswith(root.path),
        )
        .exists()
    )
    return or_(dept.tenant_id == tenant_scope, under_mount, under_root)


def _closure(scope: AuditDeptScope, tenant_scope: int | None, dept=Department) -> list:
    """Closure conditions on ``dept`` (the model or an alias of it)."""
    conditions = [dept.is_deleted == 0]
    if tenant_scope is not None:
        conditions.append(_in_audit_tenant(dept, tenant_scope))
    if not scope.unrestricted:
        parts = [dept.path.startswith(path) for path in scope.admin_paths]
        if scope.exact_ids:
            parts.append(dept.id.in_(scope.exact_ids))
        conditions.append(or_(*parts) if parts else false())
    return conditions


def _not_lifted_root(scope: AuditDeptScope, tenant_scope: int | None) -> list:
    """Tenant roots ``top_level`` already lifted to the top are not repeated as children."""
    if tenant_scope is None and scope.unrestricted:
        return [Department.is_tenant_root == 0]
    return []


class AuditDeptRepository:
    @classmethod
    async def _all(cls, statement) -> list[Department]:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return list((await session.exec(statement)).all())

    @classmethod
    async def root_paths(cls, tenant_scope: int) -> list[str]:
        """Paths of every department root in the audit tenant.

        A tenant administrator's list, export and picker are limited to these
        paths. A child tenant's root is its mount point, so the path covers
        the mounted subtree and nothing above it.
        """
        scope = AuditDeptScope.unlimited()
        parent = aliased(Department)
        parent_in_closure = (
            select(parent.id).where(parent.id == Department.parent_id, *_closure(scope, tenant_scope, parent)).exists()
        )
        statement = (
            select(Department.path)
            .where(*_closure(scope, tenant_scope), ~parent_in_closure, Department.path != "")
            .distinct()
            .order_by(Department.path)
        )
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return [path for path in (await session.exec(statement)).all() if path]

    @classmethod
    async def top_level(cls, scope: AuditDeptScope, tenant_scope: int | None, limit: int) -> list[Department]:
        """Active closure members whose parent is outside the closure.

        That is the managed roots for a department admin, the primary
        department for a menu role, and the tenant's root for a tenant-level
        reader. A cross-tenant reader also gets every mounted tenant root at
        the top, grouped by ``tenant_id`` on the page (AC-27), instead of
        finding it deep under the parent tenant's tree.
        """
        closure = _closure(scope, tenant_scope)
        parent = aliased(Department)
        parent_in_closure = (
            select(parent.id).where(parent.id == Department.parent_id, *_closure(scope, tenant_scope, parent)).exists()
        )
        is_top = ~parent_in_closure
        if tenant_scope is None and scope.unrestricted:
            is_top = or_(is_top, Department.is_tenant_root == 1)
        statement = (
            select(Department)
            .where(*closure, Department.status == DEPT_STATUS_ACTIVE, is_top)
            .order_by(Department.tenant_id, Department.sort_order, Department.id)
            .limit(limit)
        )
        return await cls._all(statement)

    @classmethod
    async def children(
        cls, scope: AuditDeptScope, tenant_scope: int | None, parent_id: int, limit: int
    ) -> list[Department]:
        statement = (
            select(Department)
            .where(
                *_closure(scope, tenant_scope),
                *_not_lifted_root(scope, tenant_scope),
                Department.parent_id == parent_id,
                Department.status == DEPT_STATUS_ACTIVE,
            )
            .order_by(Department.sort_order, Department.id)
            .limit(limit)
        )
        return await cls._all(statement)

    @classmethod
    async def archived(cls, scope: AuditDeptScope, tenant_scope: int | None, limit: int) -> list[Department]:
        statement = (
            select(Department)
            .where(*_closure(scope, tenant_scope), Department.status == DEPT_STATUS_ARCHIVED)
            .order_by(Department.path, Department.id)
            .limit(limit)
        )
        return await cls._all(statement)

    @classmethod
    async def search(
        cls, scope: AuditDeptScope, tenant_scope: int | None, keyword: str, limit: int
    ) -> list[Department]:
        """Name, ``dept_id`` or ``external_id`` substring; active and archived alike."""
        pattern = f"%{keyword}%"
        statement = (
            select(Department)
            .where(
                *_closure(scope, tenant_scope),
                or_(
                    col(Department.name).like(pattern),
                    col(Department.dept_id).like(pattern),
                    col(Department.external_id).like(pattern),
                ),
            )
            .order_by(Department.path, Department.id)
            .limit(limit)
        )
        return await cls._all(statement)

    @classmethod
    async def parents_with_children(
        cls, scope: AuditDeptScope, tenant_scope: int | None, parent_ids: Iterable[int]
    ) -> set[int]:
        ids = sorted(set(parent_ids))
        if not ids:
            return set()
        statement = (
            select(Department.parent_id)
            .where(
                *_closure(scope, tenant_scope),
                *_not_lifted_root(scope, tenant_scope),
                col(Department.parent_id).in_(ids),
                Department.status == DEPT_STATUS_ACTIVE,
            )
            .distinct()
        )
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return set((await session.exec(statement)).all())

    @classmethod
    async def names_by_id(cls, dept_ids: Iterable[int]) -> dict[int, str]:
        """Names of the ancestors on the given departments' paths (unscoped: labels only)."""
        ids = sorted(set(dept_ids))
        if not ids:
            return {}
        statement = select(Department.id, Department.name).where(col(Department.id).in_(ids))
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return {row[0]: row[1] for row in (await session.exec(statement)).all()}


__all__ = ["DEPT_STATUS_ARCHIVED", "AuditDeptRepository"]
