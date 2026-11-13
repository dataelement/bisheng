"""Which departments an audit reader may see (F003 design decision 4).

One resolver for the three audit tabs, their candidates, details and exports,
so every entry point answers the same question the same way (AC-18).
"""

from __future__ import annotations

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
from bisheng.database.models.org_snapshot import AuditDeptScope, DeptSelection
from bisheng.department.domain.repositories.audit_dept_repository import DEPT_STATUS_ARCHIVED, AuditDeptRepository

AUDIT_WEB_MENU = "log"


def _path_ids(path: str | None) -> list[int]:
    return [int(part) for part in (path or "").strip("/").split("/") if part.isdigit()]


def _path_leaf(path: str) -> int | None:
    ids = _path_ids(path)
    return ids[-1] if ids else None


def _node(dept, names: dict[int, str], has_children: bool) -> dict:
    return {
        "id": dept.id,
        "dept_id": dept.dept_id,
        "external_id": dept.external_id,
        "name": dept.name,
        "path_name": "/".join(names[one] for one in _path_ids(dept.path) if one in names) or dept.name,
        "parent_id": dept.parent_id,
        "tenant_id": dept.tenant_id,
        "has_children": has_children,
    }


class AuditDeptScopeService:
    @classmethod
    async def resolve(cls, login_user: UserPayload, tenant_scope: int | None = None) -> AuditDeptScope:
        """Scope for ``login_user`` inside the audit tenant ``tenant_scope``.

        ``tenant_scope`` is the tenant the audit query is already pinned to
        (``None`` only for a global super without an admin scope). Raises
        ``UnAuthorizedError`` for a caller who may not open the audit page —
        a user-group admin without the audit menu included (decision 9).
        """
        tenant_id = tenant_scope if tenant_scope is not None else get_current_tenant_id()
        # Ask the live tenant-admin relation before the RBAC short-circuit.
        # Child-tenant administrators also carry AdminRole, so ``is_admin()``
        # and the JWT ``is_global_super`` flag are both true for them
        # (``_check_is_global_super`` falls back to that role, and the role
        # sync writes ``super_admin``). Audit routes always install a
        # management scope, which made the old short-circuit show every row
        # in the tenant — including 「未记录」 and the system admin's sessions.
        if tenant_id is not None and await cls._is_tenant_admin(login_user.user_id, tenant_id):
            # The tenant's own department tree, including a child tenant mounted
            # on the parent tree. Operators from outside that tree stay hidden,
            # and so do 「未记录」 rows, which predate the department stamp.
            return AuditDeptScope.restricted(
                admin_paths=await AuditDeptRepository.root_paths(tenant_id), unattributed=True
            )
        if await cls.is_audit_admin(login_user, tenant_id):
            return AuditDeptScope.unlimited()

        admin_departments = await DepartmentDao.aget_user_admin_departments(login_user.user_id)
        if not await cls._has_audit_menu(login_user, is_department_admin=bool(admin_departments)):
            raise UnAuthorizedError()

        admin_paths = [
            dept.path
            for dept in admin_departments
            if dept.path and not dept.is_deleted and (tenant_id is None or dept.tenant_id == tenant_id)
        ]
        if admin_paths:
            return AuditDeptScope.restricted(admin_paths=admin_paths)

        primary = await UserDepartmentDao.aget_user_primary_department(login_user.user_id)
        return AuditDeptScope.restricted(exact_ids=[primary.department_id] if primary else [])

    @classmethod
    async def candidates(
        cls,
        scope: AuditDeptScope,
        tenant_scope: int | None,
        *,
        parent_id: int | None = None,
        keyword: str | None = None,
        limit: int = 50,
    ) -> dict:
        """Organisation picker payload (design §6.1), bounded by ``scope``."""
        keyword = (keyword or "").strip()
        if keyword:
            found = await AuditDeptRepository.search(scope, tenant_scope, keyword, limit)
            active = [one for one in found if one.status != DEPT_STATUS_ARCHIVED]
            archived = [one for one in found if one.status == DEPT_STATUS_ARCHIVED]
        elif parent_id is not None:
            active = await AuditDeptRepository.children(scope, tenant_scope, parent_id, limit)
            archived = []
        else:
            active = await AuditDeptRepository.top_level(scope, tenant_scope, limit)
            archived = await AuditDeptRepository.archived(scope, tenant_scope, limit)

        with_children = await AuditDeptRepository.parents_with_children(scope, tenant_scope, (d.id for d in active))
        names = await AuditDeptRepository.names_by_id(
            one for dept in [*active, *archived] for one in _path_ids(dept.path)
        )
        return {
            "active": [_node(dept, names, dept.id in with_children) for dept in active],
            "archived": [_node(dept, names, False) for dept in archived],
            "show_none": scope.shows_none,
            "show_unrecorded": scope.unrestricted,
        }

    @classmethod
    async def describe(cls, scope: AuditDeptScope) -> dict:
        """Names the departments ``scope`` allows, for the audit page banner.

        ``admin_paths`` include every department under that node. ``exact_ids``
        are one department and nothing beneath it. An unrestricted scope has
        no department list.
        """
        if scope.unrestricted:
            return {"organizations": [], "unrestricted_organization": True}
        leaves = [leaf for path in scope.admin_paths if (leaf := _path_leaf(path)) is not None]
        names = await AuditDeptRepository.names_by_id([*leaves, *scope.exact_ids])
        organizations = [{"name": names.get(leaf) or str(leaf), "includes_descendants": True} for leaf in leaves]
        organizations.extend(
            {"name": names.get(dept_id) or str(dept_id), "includes_descendants": False} for dept_id in scope.exact_ids
        )
        return {"organizations": organizations, "unrestricted_organization": False}

    @classmethod
    async def is_audit_admin(cls, login_user: UserPayload, _tenant_id: int | None) -> bool:
        """Platform super or the system administrator role: no department limit.

        A tenant administrator also looks like this (AdminRole), so ``resolve``
        must apply the tenant-admin crop before calling this.
        """
        return bool(login_user.is_global_super or login_user.is_admin())

    @staticmethod
    async def _is_tenant_admin(user_id: int, tenant_id: int) -> bool:
        from bisheng.common.permission_identity import check_tenant_admin

        return await check_tenant_admin(user_id, tenant_id)

    @classmethod
    async def _has_audit_menu(cls, login_user: UserPayload, *, is_department_admin: bool) -> bool:
        from bisheng.user.domain.models.user import UserDao
        from bisheng.user.domain.services.auth import LoginUser

        db_user = await UserDao.aget_user(login_user.user_id)
        if db_user is None:
            return False
        _, web_menu = await LoginUser.get_roles_web_menu(db_user, is_department_admin=is_department_admin)
        return AUDIT_WEB_MENU in set(web_menu)


__all__ = ["AUDIT_WEB_MENU", "AuditDeptScope", "AuditDeptScopeService", "DeptSelection"]
