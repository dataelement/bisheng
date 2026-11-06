"""Read-only, tenant-wide organisation directory for the ``identity:read`` scope.

Why this is not ``DepartmentService.aget_tree(login_user)``: that one computes
what the *caller* may administer — a department administrator's subtree, a tenant
administrator's whole tenant. A service account holds no management role at all,
so reusing it would hand every MCP caller an **empty tree** and look like a
permission bug rather than the wrong question.

``identity:read`` has exactly one boundary, and it is tenant isolation (spec
AC-31 / AC-32): granting the scope means the whole tenant's org chart is
readable, and there is deliberately no mechanism to narrow it to some
departments — the decision is "give the scope or don't". Everything here
therefore runs under the tenant ContextVar and its automatic filter (C3) with no
further narrowing.

Two shapes are structural rather than incidental:

* **Credential-bearing fields never enter a payload.** ``password``,
  ``token_version``, ``external_id`` and anything token-shaped are absent from
  the projections below, not filtered out downstream.
* **Service accounts cannot appear.** They live in their own ``service_account``
  table with no ``user`` row and belong to no department, so the directory omits
  them by construction (伴生 D10 / 决议-11) — there is no "hide them" branch to
  forget.
"""

from __future__ import annotations

from typing import Any

from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.database.models.department import Department, DepartmentDao, UserDepartmentDao
from bisheng.database.models.role import RoleDao
from bisheng.database.models.tenant import UserTenantDao
from bisheng.user.domain.models.user import UserDao
from bisheng.user.domain.models.user_role import UserRoleDao

#: Hard ceiling on one page of department members.
MAX_MEMBER_PAGE_SIZE = 200


class OrgDirectoryService:
    """Tenant-wide org chart and person lookup. No narrowing, no credentials."""

    @classmethod
    async def atree(cls) -> list[dict[str, Any]]:
        """The active departments of the current tenant, as a nested tree."""

        tenant_id = get_current_tenant_id()
        rows = await DepartmentDao.aget_active_by_tenant(int(tenant_id or 0))
        return cls._build_tree(rows)

    @classmethod
    async def amembers(
        cls,
        dept_id: str,
        *,
        page: int = 1,
        size: int = 50,
        keyword: str | None = None,
    ) -> dict[str, Any] | None:
        """One page of a department's members, or ``None`` if it is not ours."""

        department = await cls._load_department(dept_id)
        if department is None:
            return None
        size = max(1, min(int(size or 50), MAX_MEMBER_PAGE_SIZE))
        page = max(1, int(page or 1))
        rows, total = await UserDepartmentDao.aget_members(
            int(department.id),
            page=page,
            limit=size,
            keyword=keyword or "",
        )
        user_ids = [int(row[0]) for row in rows or []]
        # One lookup for the page, not one per row: ``aget_members`` selects
        # names but not the disabled flag, and a member list of 200 should not
        # cost 200 round trips to add it.
        by_id = {int(user.user_id): user for user in (await UserDao.aget_user_by_ids(user_ids)) or []}
        members = [
            {"user_id": int(row[0]), "user_name": row[1], "status": cls._status(by_id.get(int(row[0])))}
            for row in rows or []
        ]
        return {"members": members, "total": int(total or 0)}

    @classmethod
    async def aget_user(cls, user_id: int) -> dict[str, Any] | None:
        """One person's identity and org membership, or ``None``.

        ``None`` covers "no such user" **and** "in another tenant" — the caller
        turns both into the same answer, because telling them apart is a way to
        enumerate other tenants' user ids.
        """

        user = await UserDao.aget_user(int(user_id))
        if user is None:
            return None
        # A disabled person is still a person in this org chart, and is returned
        # with ``status: "disabled"``. Hiding them would read as "no such user"
        # and send an agent hunting for a typo in an id that is perfectly valid —
        # and would leave ``status`` a field that can only ever say "active".
        membership = await UserTenantDao.aget_active_user_tenant(int(user_id))
        tenant_id = int(get_current_tenant_id() or 0)
        if membership is None or int(membership.tenant_id or 0) != tenant_id:
            return None

        return {
            "user_id": int(user.user_id),
            "user_name": user.user_name,
            "status": cls._status(user),
            "departments": await cls._departments_of(int(user_id)),
            "roles": await cls._role_names_of(int(user_id)),
        }

    # -- internals ------------------------------------------------------

    @staticmethod
    def _status(user) -> str:
        if user is None:
            return "disabled"
        return "disabled" if int(getattr(user, "delete", 0) or 0) == 1 else "active"

    @classmethod
    async def _load_department(cls, dept_id: str) -> Department | None:
        department = await DepartmentDao.aget_by_dept_id(str(dept_id))
        if department is None or department.status != "active":
            return None
        # ``aget_by_dept_id`` runs under the automatic tenant filter, but the
        # comparison is repeated explicitly: the filter admits Root-tenant rows
        # through the IN-list, and an org chart is not a shared resource.
        if int(department.tenant_id or 0) != int(get_current_tenant_id() or 0):
            return None
        return department

    @classmethod
    async def _departments_of(cls, user_id: int) -> list[dict[str, Any]]:
        memberships = await UserDepartmentDao.aget_user_departments(user_id)
        department_ids = [int(item.department_id) for item in memberships or []]
        if not department_ids:
            return []
        rows = await DepartmentDao.aget_by_ids(department_ids)
        tenant_id = int(get_current_tenant_id() or 0)
        return [
            {"dept_id": row.dept_id, "name": row.name, "path": row.path}
            for row in rows or []
            if int(row.tenant_id or 0) == tenant_id
        ]

    @staticmethod
    async def _role_names_of(user_id: int) -> list[str]:
        user_roles = await UserRoleDao.aget_user_roles(user_id)
        role_ids = [int(item.role_id) for item in user_roles or []]
        if not role_ids:
            return []
        roles = await RoleDao.aget_role_by_ids(role_ids)
        return [role.role_name for role in roles or []]

    @staticmethod
    def _build_tree(rows: list[Department]) -> list[dict[str, Any]]:
        """Nest by ``parent_id``.

        ``is_tenant_root`` / ``mounted_tenant_id`` are deliberately dropped:
        tenant topology is platform administration, not organisation
        information, and this scope grants the latter.
        """

        nodes: dict[int, dict[str, Any]] = {}
        for row in rows:
            nodes[int(row.id)] = {
                "dept_id": row.dept_id,
                "name": row.name,
                "parent_id": int(row.parent_id) if row.parent_id is not None else None,
                "path": row.path,
                "sort_order": int(row.sort_order or 0),
                "source": row.source,
                "status": row.status,
                "children": [],
            }
        roots: list[dict[str, Any]] = []
        for row in rows:
            node = nodes[int(row.id)]
            parent = nodes.get(int(row.parent_id)) if row.parent_id is not None else None
            if parent is None:
                roots.append(node)
            else:
                parent["children"].append(node)

        def sort_nodes(items: list[dict[str, Any]]) -> None:
            items.sort(key=lambda item: (item["sort_order"], item["name"]))
            for item in items:
                sort_nodes(item["children"])

        sort_nodes(roots)
        # ``parent_id`` is an internal row id; the tree is addressed by
        # ``dept_id`` everywhere else, so translate before it leaves.
        id_to_dept_id = {int(row.id): row.dept_id for row in rows}

        def rewrite(items: list[dict[str, Any]]) -> None:
            for item in items:
                parent_id = item["parent_id"]
                item["parent_id"] = id_to_dept_id.get(parent_id) if parent_id is not None else None
                rewrite(item["children"])

        rewrite(roots)
        return roots


__all__ = ["MAX_MEMBER_PAGE_SIZE", "OrgDirectoryService"]
