from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import col, select

from bisheng.core import database as database_module
from bisheng.core.context import tenant as tenant_context

#: ``user.is_hidden`` value marking a person who must not be offered as a
#: grant subject. Only an explicit upstream ``jobGrade=1`` is stored as 1;
#: every other user carries 0. Super admins see them anyway — see
#: ``include_hidden`` on :meth:`GrantSubjectQueryRepository.list_users`.
_HIDDEN_USER = 1


@dataclass(frozen=True)
class _GrantDeptScope:
    positive_prefix: str | None
    exclude_prefixes: tuple[str, ...]
    tenant_id: int


def _path_ids(path: str | None) -> list[int]:
    result: list[int] = []
    for part in (path or "").split("/"):
        if part.strip().isdigit():
            result.append(int(part))
    return result


def _in_scope(department, scope: _GrantDeptScope) -> bool:
    path = getattr(department, "path", None)
    if scope.positive_prefix is not None:
        if not (path and path.startswith(scope.positive_prefix)):
            return False
    elif int(getattr(department, "tenant_id", 0) or 0) != scope.tenant_id:
        return False
    return not any(path and path.startswith(prefix) for prefix in scope.exclude_prefixes)


def _apply_scope(statement, scope: _GrantDeptScope, department_model):
    if scope.positive_prefix is not None:
        statement = statement.where(department_model.path.like(f"{scope.positive_prefix}%"))
    else:
        statement = statement.where(department_model.tenant_id == scope.tenant_id)
    for prefix in scope.exclude_prefixes:
        statement = statement.where(~department_model.path.like(f"{prefix}%"))
    return statement


def _department_node(department, *, has_children: bool = False, matched: bool = False) -> dict:
    return {
        "id": int(department.id),
        "dept_id": department.dept_id,
        "name": department.name,
        "parent_id": int(department.parent_id) if getattr(department, "parent_id", None) is not None else None,
        "path": department.path,
        "sort_order": int(getattr(department, "sort_order", 0) or 0),
        "source": department.source,
        "status": department.status,
        "has_children": has_children,
        "matched": matched,
        "children": [],
    }


class GrantSubjectQueryRepository:
    """Persistence adapter for grant-subject candidates.

    Queries intentionally mirror the pre-F044 endpoint helpers so extraction
    does not alter tenant scope, ordering, pagination, or F038 lazy-tree shape.
    """

    async def is_active_tenant(self, tenant_id: int) -> bool:
        from bisheng.database.models.tenant import TenantDao

        tenant = await TenantDao.aget_by_id(tenant_id)
        return tenant is not None and getattr(tenant, "status", None) == "active"

    async def is_active_user_in_any_active_tenant(self, user_id: int) -> bool:
        """Validate the identity behind a global-super tuple is still active."""
        from bisheng.database.models.tenant import Tenant, UserTenant
        from bisheng.user.domain.models.user import User

        with tenant_context.bypass_tenant_filter():
            async with database_module.get_async_db_session() as session:
                row = (
                    await session.exec(
                        select(User.user_id)
                        .join(UserTenant, UserTenant.user_id == User.user_id)
                        .join(Tenant, Tenant.id == UserTenant.tenant_id)
                        .where(
                            User.user_id == user_id,
                            User.delete == 0,
                            UserTenant.status == "active",
                            UserTenant.is_active == 1,
                            Tenant.status == "active",
                        )
                    )
                ).first()
        return row is not None

    async def list_users(
        self,
        *,
        tenant_id: int,
        keyword: str,
        page: int,
        page_size: int,
        restrict_dept_path: str | None = None,
        include_hidden: bool = False,
    ) -> list[dict]:
        """List grantable users. ``include_hidden`` is the super-admin escape
        hatch: hidden users are withheld from everyone else's picker."""
        from bisheng.database.models.department import (
            Department,
            DepartmentDao,
            UserDepartment,
            UserDepartmentDao,
        )
        from bisheng.database.models.tenant import UserTenant
        from bisheng.user.domain.models.user import User

        with tenant_context.bypass_tenant_filter():
            async with database_module.get_async_db_session() as session:
                active_member = (
                    select(UserTenant.id)
                    .where(
                        UserTenant.user_id == User.user_id,
                        UserTenant.tenant_id == tenant_id,
                        UserTenant.status == "active",
                    )
                    .exists()
                )
                statement = (
                    select(User.user_id, User.user_name, User.external_id)
                    .where(User.delete == 0, active_member)
                    .order_by(User.user_id.desc())
                )
                if not include_hidden:
                    statement = statement.where(User.is_hidden != _HIDDEN_USER)
                if restrict_dept_path is not None:
                    in_subtree = (
                        select(UserDepartment.id)
                        .join(Department, Department.id == UserDepartment.department_id)
                        .where(
                            UserDepartment.user_id == User.user_id,
                            Department.path.like(f"{restrict_dept_path}%"),
                            Department.status == "active",
                        )
                        .exists()
                    )
                    statement = statement.where(in_subtree)
                if keyword:
                    statement = statement.where(User.user_name.like(f"{keyword}%"))
                if page and page_size:
                    statement = statement.offset((page - 1) * page_size).limit(page_size)
                users = list((await session.exec(statement)).all())

        if not users:
            return []
        user_ids = [int(user.user_id) for user in users]
        department_rows = await UserDepartmentDao.aget_by_user_ids(user_ids)
        primary_rows = [row for row in department_rows if int(getattr(row, "is_primary", 0) or 0) == 1]
        primary_ids = {int(row.department_id) for row in primary_rows}
        departments = await DepartmentDao.aget_by_ids(list(primary_ids)) if primary_ids else []
        department_map = {int(item.id): item for item in departments}
        ancestor_ids = {
            item_id
            for department in departments
            for item_id in _path_ids(getattr(department, "path", None))
            if item_id not in department_map
        }
        if ancestor_ids:
            department_map.update(
                {
                    int(item.id): item
                    for item in await DepartmentDao.aget_by_ids(list(ancestor_ids)) or []
                    if getattr(item, "id", None) is not None
                }
            )
        primary_by_user = {int(row.user_id): department_map.get(int(row.department_id)) for row in primary_rows}

        def display_path(department) -> str | None:
            if department is None:
                return None
            labels = [
                getattr(department_map.get(item_id), "name", f"#{item_id}")
                for item_id in _path_ids(getattr(department, "path", None))
            ]
            own_name = getattr(department, "name", None)
            if own_name and own_name not in labels:
                labels.append(own_name)
            return "/".join(labels) if labels else own_name

        return [
            {
                "user_id": int(user.user_id),
                "user_name": user.user_name,
                "external_id": getattr(user, "external_id", None),
                "primary_department_path": display_path(primary_by_user.get(int(user.user_id))),
            }
            for user in users
        ]

    async def list_department_direct_users(
        self,
        *,
        tenant_id: int,
        department_id: int,
        page: int,
        page_size: int,
        restrict_root_path: str | None = None,
        include_hidden: bool = False,
    ) -> dict:
        """F038 user tree: direct primary-department members of ``department_id``.

        Mirrors ``list_users``' tenant/leadership/active-membership filters, but
        scoped to a single department (not the whole tenant/subtree) so the tree
        never shows a member twice under different nodes.
        """
        from bisheng.database.models.department import Department, UserDepartment
        from bisheng.database.models.tenant import UserTenant
        from bisheng.user.domain.models.user import User

        with tenant_context.bypass_tenant_filter():
            async with database_module.get_async_db_session() as session:
                scope = await self._resolve_department_scope(session, tenant_id, restrict_root_path)
                if scope is None:
                    return {"items": [], "has_more": False}
                dept = (
                    await session.exec(
                        select(Department).where(Department.id == department_id, Department.status == "active")
                    )
                ).first()
                if dept is None or not _in_scope(dept, scope):
                    return {"items": [], "has_more": False}

                active_member = (
                    select(UserTenant.id)
                    .where(
                        UserTenant.user_id == User.user_id,
                        UserTenant.tenant_id == tenant_id,
                        UserTenant.status == "active",
                    )
                    .exists()
                )
                statement = (
                    select(User.user_id, User.user_name, User.external_id)
                    .join(UserDepartment, UserDepartment.user_id == User.user_id)
                    .where(
                        UserDepartment.department_id == department_id,
                        UserDepartment.is_primary == 1,
                        User.delete == 0,
                        active_member,
                    )
                    .order_by(User.user_id.desc())
                    .offset(max(0, (page - 1) * page_size))
                    .limit(page_size + 1)
                )
                if not include_hidden:
                    statement = statement.where(User.is_hidden != _HIDDEN_USER)
                rows = list((await session.exec(statement)).all())

        has_more = len(rows) > page_size
        rows = rows[:page_size]
        return {
            "items": [
                {
                    "user_id": int(row.user_id),
                    "user_name": row.user_name,
                    "external_id": getattr(row, "external_id", None),
                }
                for row in rows
            ],
            "has_more": has_more,
        }

    async def search_users_tree(
        self,
        *,
        tenant_id: int,
        keyword: str,
        limit: int = 50,
        restrict_root_path: str | None = None,
        include_hidden: bool = False,
    ) -> dict:
        """F038 user tree search: username match, results keep the full ancestor
        department path (decision mirrors ``search_departments``' pruned tree),
        with matched users attached as leaves on their primary department node.

        Users with no primary department, or whose primary department falls
        outside the resource's authorizable scope, cannot be placed in the tree
        and are dropped from the result (same visibility boundary as browsing).
        """
        from bisheng.database.models.department import Department, DepartmentDao, UserDepartment, UserDepartmentDao
        from bisheng.database.models.tenant import UserTenant
        from bisheng.user.domain.models.user import User

        keyword = (keyword or "").strip()
        if not keyword:
            return {"roots": [], "total_matches": 0, "truncated": False}
        limit = max(1, min(limit, 200))
        with tenant_context.bypass_tenant_filter():
            async with database_module.get_async_db_session() as session:
                scope = await self._resolve_department_scope(session, tenant_id, restrict_root_path)
                if scope is None:
                    return {"roots": [], "total_matches": 0, "truncated": False}

                active_member = (
                    select(UserTenant.id)
                    .where(
                        UserTenant.user_id == User.user_id,
                        UserTenant.tenant_id == tenant_id,
                        UserTenant.status == "active",
                    )
                    .exists()
                )
                statement = (
                    select(User.user_id, User.user_name, User.external_id)
                    .where(
                        User.delete == 0,
                        active_member,
                        User.user_name.like(f"%{keyword}%"),
                    )
                    .order_by(User.user_id.desc())
                    .limit(limit + 1)
                )
                if not include_hidden:
                    statement = statement.where(User.is_hidden != _HIDDEN_USER)
                if scope.positive_prefix is not None:
                    in_subtree = (
                        select(UserDepartment.id)
                        .join(Department, Department.id == UserDepartment.department_id)
                        .where(
                            UserDepartment.user_id == User.user_id,
                            # A user is represented only under the primary
                            # department. Filtering by any secondary
                            # membership here would consume a search slot and
                            # later drop the user when the primary department
                            # is outside the resource scope.
                            UserDepartment.is_primary == 1,
                            Department.path.like(f"{scope.positive_prefix}%"),
                            Department.status == "active",
                        )
                        .exists()
                    )
                    statement = statement.where(in_subtree)
                users = list((await session.exec(statement)).all())
                truncated = len(users) > limit
                users = users[:limit]
                if not users:
                    return {"roots": [], "total_matches": 0, "truncated": False}

                user_ids = [int(user.user_id) for user in users]
                department_rows = await UserDepartmentDao.aget_by_user_ids(user_ids)
                primary_rows = [row for row in department_rows if int(getattr(row, "is_primary", 0) or 0) == 1]
                primary_dept_by_user = {int(row.user_id): int(row.department_id) for row in primary_rows}
                dept_ids = sorted(set(primary_dept_by_user.values()))
                departments = await DepartmentDao.aget_by_ids(dept_ids) if dept_ids else []
                seed_departments = [item for item in departments if _in_scope(item, scope)]
                roots = await self._build_pruned(session, seed_departments, set(), scope, Department)

        node_by_id: dict[int, dict] = {}

        def _collect(nodes: list[dict]) -> None:
            for node in nodes:
                node.setdefault("users", [])
                node_by_id[node["id"]] = node
                _collect(node["children"])

        _collect(roots)

        placed = 0
        for user in users:
            dept_id = primary_dept_by_user.get(int(user.user_id))
            node = node_by_id.get(dept_id) if dept_id is not None else None
            if node is None:
                continue
            node["users"].append(
                {
                    "user_id": int(user.user_id),
                    "user_name": user.user_name,
                    "external_id": getattr(user, "external_id", None),
                }
            )
            placed += 1

        return {"roots": roots, "total_matches": placed, "truncated": truncated}

    async def _resolve_department_scope(
        self, session, tenant_id: int, restrict_root_path: str | None
    ) -> _GrantDeptScope | None:
        from bisheng.database.models.department import Department
        from bisheng.database.models.tenant import ROOT_TENANT_ID, Tenant

        tenant = (await session.exec(select(Tenant).where(Tenant.id == tenant_id, Tenant.status == "active"))).first()
        if tenant is None:
            return None
        root = None
        if getattr(tenant, "root_dept_id", None):
            root = (
                await session.exec(
                    select(Department).where(
                        Department.id == int(tenant.root_dept_id),
                        Department.status == "active",
                    )
                )
            ).first()
        excluded: list[str] = []
        if root is not None and tenant_id == ROOT_TENANT_ID:
            child_roots = (
                await session.exec(
                    select(Department.path).where(
                        Department.is_tenant_root == 1,
                        Department.mounted_tenant_id.is_not(None),
                        Department.mounted_tenant_id != ROOT_TENANT_ID,
                        Department.status == "active",
                    )
                )
            ).all()
            excluded = [path for path in child_roots if path]
        return _GrantDeptScope(
            positive_prefix=restrict_root_path or (root.path if root is not None else None),
            exclude_prefixes=tuple(excluded),
            tenant_id=tenant_id,
        )

    async def _children_existence(self, session, parent_ids: list[int], scope, department_model) -> set[int]:
        if not parent_ids:
            return set()
        statement = select(department_model.parent_id).where(
            col(department_model.parent_id).in_(parent_ids),
            department_model.status == "active",
        )
        rows = (await session.exec(_apply_scope(statement, scope, department_model).distinct())).all()
        return {
            int(row[0] if isinstance(row, (list, tuple)) else row)
            for row in rows
            if (row[0] if isinstance(row, (list, tuple)) else row) is not None
        }

    async def _build_pruned(self, session, seeds, matched_ids: set[int], scope, department_model) -> list[dict]:
        needed = {item_id for seed in seeds for item_id in _path_ids(seed.path)}
        if not needed:
            return []
        rows = list(
            (
                await session.exec(
                    select(department_model).where(
                        col(department_model.id).in_(list(needed)),
                        department_model.status == "active",
                    )
                )
            ).all()
        )
        visible = [item for item in rows if _in_scope(item, scope)]
        child_ids = await self._children_existence(session, [int(item.id) for item in visible], scope, department_model)
        nodes = {
            int(item.id): _department_node(
                item,
                has_children=int(item.id) in child_ids,
                matched=int(item.id) in matched_ids,
            )
            for item in visible
        }
        roots: list[dict] = []
        for item in visible:
            parent_id = int(item.parent_id) if getattr(item, "parent_id", None) is not None else None
            if parent_id is not None and parent_id in nodes:
                nodes[parent_id]["children"].append(nodes[int(item.id)])
            else:
                roots.append(nodes[int(item.id)])

        def sort_nodes(layer: list[dict]) -> None:
            layer.sort(key=lambda node: (node["sort_order"], node["id"]))
            for node in layer:
                sort_nodes(node["children"])

        sort_nodes(roots)
        return roots

    async def list_departments_children(
        self,
        *,
        tenant_id: int,
        parent_id: int | None = None,
        restrict_root_path: str | None = None,
    ) -> list[dict]:
        from bisheng.database.models.department import Department

        with tenant_context.bypass_tenant_filter():
            async with database_module.get_async_db_session() as session:
                scope = await self._resolve_department_scope(session, tenant_id, restrict_root_path)
                if scope is None:
                    return []
                if parent_id is None:
                    root_ids = _path_ids(scope.positive_prefix)
                    if root_ids:
                        root = (
                            await session.exec(
                                select(Department).where(Department.id == root_ids[-1], Department.status == "active")
                            )
                        ).first()
                        departments = [root] if root is not None and _in_scope(root, scope) else []
                    else:
                        statement = select(Department).where(
                            Department.parent_id.is_(None), Department.status == "active"
                        )
                        departments = list(
                            (
                                await session.exec(
                                    _apply_scope(statement, scope, Department).order_by(
                                        Department.sort_order, Department.id
                                    )
                                )
                            ).all()
                        )
                else:
                    parent = (
                        await session.exec(
                            select(Department).where(Department.id == parent_id, Department.status == "active")
                        )
                    ).first()
                    if parent is None or not _in_scope(parent, scope):
                        return []
                    statement = select(Department).where(
                        Department.parent_id == parent_id, Department.status == "active"
                    )
                    departments = list(
                        (
                            await session.exec(
                                _apply_scope(statement, scope, Department).order_by(
                                    Department.sort_order, Department.id
                                )
                            )
                        ).all()
                    )
                departments = [item for item in departments if item is not None]
                child_ids = await self._children_existence(
                    session, [int(item.id) for item in departments], scope, Department
                )
                return [_department_node(item, has_children=int(item.id) in child_ids) for item in departments]

    async def search_departments(
        self,
        *,
        tenant_id: int,
        keyword: str,
        limit: int = 50,
        restrict_root_path: str | None = None,
    ) -> dict:
        from bisheng.database.models.department import Department

        keyword = (keyword or "").strip()
        if not keyword:
            return {"roots": [], "total_matches": 0, "truncated": False}
        limit = max(1, min(limit, 200))
        with tenant_context.bypass_tenant_filter():
            async with database_module.get_async_db_session() as session:
                scope = await self._resolve_department_scope(session, tenant_id, restrict_root_path)
                if scope is None:
                    return {"roots": [], "total_matches": 0, "truncated": False}
                statement = select(Department).where(
                    Department.name.like(f"%{keyword}%"), Department.status == "active"
                )
                matched = list(
                    (
                        await session.exec(
                            _apply_scope(statement, scope, Department)
                            .order_by(Department.sort_order, Department.id)
                            .limit(limit + 1)
                        )
                    ).all()
                )
                truncated = len(matched) > limit
                matched = matched[:limit]
                roots = await self._build_pruned(
                    session, matched, {int(item.id) for item in matched}, scope, Department
                )
                return {
                    "roots": roots,
                    "total_matches": len(matched),
                    "truncated": truncated,
                }

    async def get_departments_path_tree(
        self,
        *,
        tenant_id: int,
        dept_id: int,
        restrict_root_path: str | None = None,
    ) -> dict:
        from bisheng.database.models.department import Department

        with tenant_context.bypass_tenant_filter():
            async with database_module.get_async_db_session() as session:
                scope = await self._resolve_department_scope(session, tenant_id, restrict_root_path)
                if scope is None:
                    return {"roots": [], "total_matches": 0, "truncated": False}
                target = (
                    await session.exec(
                        select(Department).where(Department.id == dept_id, Department.status == "active")
                    )
                ).first()
                if target is None or not _in_scope(target, scope):
                    return {"roots": [], "total_matches": 0, "truncated": False}
                roots = await self._build_pruned(session, [target], {int(target.id)}, scope, Department)
                return {"roots": roots, "total_matches": 1, "truncated": False}

    async def list_user_groups(
        self,
        *,
        tenant_id: int,
        keyword: str,
        viewer_user_id: int,
        can_view_all: bool,
    ) -> list[dict]:
        from bisheng.database.models.group import Group
        from bisheng.database.models.tenant import Tenant
        from bisheng.database.models.user_group import UserGroupDao

        visible_ids: set[int] = set()
        if not can_view_all:
            rows = await UserGroupDao.aget_user_visible_group_ids(viewer_user_id)
            visible_ids = {int(row[0]) if isinstance(row, tuple) else int(row) for row in rows or [] if row is not None}
        with tenant_context.bypass_tenant_filter():
            async with database_module.get_async_db_session() as session:
                statement = (
                    select(Group)
                    .join(Tenant, Tenant.id == Group.tenant_id)
                    .where(Group.tenant_id == tenant_id, Tenant.status == "active")
                    .order_by(Group.update_time.desc())
                    .limit(2000)
                )
                if not can_view_all:
                    visible = (Group.visibility == "public") | (Group.create_user == viewer_user_id)
                    if visible_ids:
                        visible = visible | col(Group.id).in_(visible_ids)
                    statement = statement.where(visible)
                if keyword:
                    statement = statement.where(Group.group_name.like(f"%{keyword}%"))
                groups = list((await session.exec(statement)).all())
        return [
            {"id": int(group.id), "group_name": group.group_name}
            for group in groups
            if getattr(group, "id", None) is not None
        ]

    async def users_exist_in_tenant(self, user_ids: set[int], tenant_id: int) -> bool:
        from bisheng.database.models.tenant import Tenant, UserTenant
        from bisheng.user.domain.models.user import User

        with tenant_context.bypass_tenant_filter():
            async with database_module.get_async_db_session() as session:
                statement = (
                    select(User.user_id)
                    .join(UserTenant, UserTenant.user_id == User.user_id)
                    .join(Tenant, Tenant.id == UserTenant.tenant_id)
                    .where(
                        col(User.user_id).in_(user_ids),
                        UserTenant.tenant_id == tenant_id,
                        UserTenant.status == "active",
                        Tenant.status == "active",
                        User.delete == 0,
                    )
                )
                rows = (await session.exec(statement)).all()
        return {int(row[0] if isinstance(row, tuple) else row) for row in rows} == user_ids

    async def departments_exist_in_tenant(self, department_ids: set[int], tenant_id: int) -> bool:
        from bisheng.database.models.department import Department

        with tenant_context.bypass_tenant_filter():
            async with database_module.get_async_db_session() as session:
                scope = await self._resolve_department_scope(session, tenant_id, None)
                if scope is None:
                    return False
                rows = list(
                    (
                        await session.exec(
                            select(Department).where(
                                col(Department.id).in_(department_ids),
                                Department.status == "active",
                            )
                        )
                    ).all()
                )
        return {int(item.id) for item in rows if _in_scope(item, scope)} == department_ids

    async def grant_subjects_exist_in_department_scope(
        self,
        *,
        user_ids: set[int],
        department_ids: set[int],
        tenant_id: int,
        restrict_root_path: str,
    ) -> bool:
        """Check grant subjects against a department-space boundary.

        Departments must be within the space subtree. Users must have their
        *primary* department in that subtree, which is the same placement rule
        used by the user authorization tree. User groups cannot be safely
        scoped by a department subtree and are handled by the service layer.
        """
        from bisheng.database.models.department import Department, UserDepartment

        with tenant_context.bypass_tenant_filter():
            async with database_module.get_async_db_session() as session:
                scope = await self._resolve_department_scope(session, tenant_id, restrict_root_path)
                if scope is None:
                    return False

                if department_ids:
                    department_rows = list(
                        (
                            await session.exec(
                                select(Department).where(
                                    col(Department.id).in_(department_ids),
                                    Department.status == "active",
                                )
                            )
                        ).all()
                    )
                    if {int(item.id) for item in department_rows if _in_scope(item, scope)} != department_ids:
                        return False

                if user_ids:
                    user_rows = (
                        await session.exec(
                            select(UserDepartment.user_id)
                            .join(Department, Department.id == UserDepartment.department_id)
                            .where(
                                col(UserDepartment.user_id).in_(user_ids),
                                UserDepartment.is_primary == 1,
                                Department.status == "active",
                            )
                        )
                    ).all()
                    scoped_user_ids = {int(row[0] if isinstance(row, tuple) else row) for row in user_rows}
                    if scoped_user_ids != user_ids:
                        return False

                    primary_departments = list(
                        (
                            await session.exec(
                                select(Department)
                                .join(UserDepartment, UserDepartment.department_id == Department.id)
                                .where(
                                    col(UserDepartment.user_id).in_(user_ids),
                                    UserDepartment.is_primary == 1,
                                    Department.status == "active",
                                )
                            )
                        ).all()
                    )
                    if any(not _in_scope(department, scope) for department in primary_departments):
                        return False

        return True

    async def user_groups_exist_in_tenant(self, group_ids: set[int], tenant_id: int) -> bool:
        from bisheng.database.models.group import Group
        from bisheng.database.models.tenant import Tenant

        with tenant_context.bypass_tenant_filter():
            async with database_module.get_async_db_session() as session:
                statement = (
                    select(Group.id)
                    .join(Tenant, Tenant.id == Group.tenant_id)
                    .where(
                        col(Group.id).in_(group_ids),
                        Group.tenant_id == tenant_id,
                        Tenant.status == "active",
                    )
                )
                rows = (await session.exec(statement)).all()
        return {int(row[0] if isinstance(row, tuple) else row) for row in rows} == group_ids

    async def resolve_exact_department_member_user_ids_batch(
        self,
        *,
        department_ids: set[int],
        tenant_id: int,
    ) -> dict[int, set[int]]:
        """Resolve tenant-scoped department usersets in one session.

        Missing mapping keys are invalid/out-of-tenant departments. Valid empty
        departments remain present with an empty member set. Exact departments
        are used because include-children grants are already materialized as
        separate OpenFGA department tuples on write.
        """
        if not department_ids:
            return {}

        from bisheng.database.models.department import Department, UserDepartment

        with tenant_context.bypass_tenant_filter():
            async with database_module.get_async_db_session() as session:
                scope = await self._resolve_department_scope(session, tenant_id, None)
                if scope is None:
                    return {}
                department_statement = select(Department).where(
                    col(Department.id).in_(department_ids),
                    Department.status == "active",
                )
                departments = list(await session.exec(_apply_scope(department_statement, scope, Department)))
                valid_department_ids = {
                    int(department.id) for department in departments if getattr(department, "id", None) is not None
                }
                members_by_department = {department_id: set() for department_id in valid_department_ids}
                if not valid_department_ids:
                    return members_by_department

                member_statement = (
                    select(UserDepartment.department_id, UserDepartment.user_id)
                    .join(Department, Department.id == UserDepartment.department_id)
                    .where(
                        col(UserDepartment.department_id).in_(valid_department_ids),
                        Department.status == "active",
                    )
                )
                member_rows = (await session.exec(_apply_scope(member_statement, scope, Department))).all()
                for row in member_rows:
                    department_id = int(getattr(row, "department_id", row[0]))
                    user_id = int(getattr(row, "user_id", row[1]))
                    members_by_department[department_id].add(user_id)
        return members_by_department

    async def resolve_user_group_member_user_ids_batch(
        self,
        *,
        group_ids: set[int],
        tenant_id: int,
    ) -> dict[int, set[int]]:
        """Resolve tenant-scoped user-group usersets in one session."""
        if not group_ids:
            return {}

        from bisheng.database.models.group import Group
        from bisheng.database.models.tenant import Tenant
        from bisheng.database.models.user_group import UserGroup

        with tenant_context.bypass_tenant_filter():
            async with database_module.get_async_db_session() as session:
                groups = list(
                    (
                        await session.exec(
                            select(Group)
                            .join(Tenant, Tenant.id == Group.tenant_id)
                            .where(
                                col(Group.id).in_(group_ids),
                                Group.tenant_id == tenant_id,
                                Tenant.status == "active",
                            )
                        )
                    ).all()
                )
                valid_group_ids = {int(group.id) for group in groups if getattr(group, "id", None) is not None}
                members_by_group = {group_id: set() for group_id in valid_group_ids}
                if not valid_group_ids:
                    return members_by_group

                member_rows = (
                    await session.exec(
                        select(UserGroup.group_id, UserGroup.user_id).where(
                            col(UserGroup.group_id).in_(valid_group_ids),
                            UserGroup.tenant_id == tenant_id,
                        )
                    )
                ).all()
                for row in member_rows:
                    group_id = int(getattr(row, "group_id", row[0]))
                    user_id = int(getattr(row, "user_id", row[1]))
                    members_by_group[group_id].add(user_id)
        return members_by_group

    async def resolve_user_group_admin_user_ids_batch(
        self,
        *,
        group_ids: set[int],
        tenant_id: int,
    ) -> dict[int, set[int]]:
        """Resolve active tenant group-admin usersets without including members."""
        if not group_ids:
            return {}

        from bisheng.database.models.group import Group
        from bisheng.database.models.tenant import Tenant
        from bisheng.database.models.user_group import UserGroup

        with tenant_context.bypass_tenant_filter():
            async with database_module.get_async_db_session() as session:
                groups = list(
                    (
                        await session.exec(
                            select(Group)
                            .join(Tenant, Tenant.id == Group.tenant_id)
                            .where(
                                col(Group.id).in_(group_ids),
                                Group.tenant_id == tenant_id,
                                Tenant.status == "active",
                            )
                        )
                    ).all()
                )
                valid_group_ids = {int(group.id) for group in groups if getattr(group, "id", None) is not None}
                admins_by_group = {group_id: set() for group_id in valid_group_ids}
                if not valid_group_ids:
                    return admins_by_group

                admin_rows = (
                    await session.exec(
                        select(UserGroup.group_id, UserGroup.user_id).where(
                            col(UserGroup.group_id).in_(valid_group_ids),
                            UserGroup.tenant_id == tenant_id,
                            UserGroup.is_group_admin == True,  # noqa: E712
                        )
                    )
                ).all()
                for row in admin_rows:
                    group_id = int(getattr(row, "group_id", row[0]))
                    user_id = int(getattr(row, "user_id", row[1]))
                    admins_by_group[group_id].add(user_id)
        return admins_by_group

    async def filter_active_user_ids_in_tenant(
        self,
        *,
        user_ids: set[int],
        tenant_id: int,
    ) -> set[int]:
        """Keep enabled users with a current, active relation to one tenant."""
        if not user_ids:
            return set()

        from bisheng.database.models.tenant import Tenant, UserTenant
        from bisheng.user.domain.models.user import User

        with tenant_context.bypass_tenant_filter():
            async with database_module.get_async_db_session() as session:
                rows = (
                    await session.exec(
                        select(User.user_id)
                        .join(UserTenant, UserTenant.user_id == User.user_id)
                        .join(Tenant, Tenant.id == UserTenant.tenant_id)
                        .where(
                            col(User.user_id).in_(user_ids),
                            User.delete == 0,
                            UserTenant.tenant_id == tenant_id,
                            UserTenant.status == "active",
                            UserTenant.is_active == 1,
                            Tenant.status == "active",
                        )
                    )
                ).all()
        return {int(row[0] if isinstance(row, tuple) else row) for row in rows if row is not None}

    async def resolve_active_subject_strings_for_user(
        self,
        *,
        user_id: int,
        tenant_id: int,
    ) -> set[str]:
        """Build one user's current tenant-scoped OpenFGA subjects fail-closed."""
        from bisheng.database.models.department import Department, UserDepartment
        from bisheng.database.models.group import Group
        from bisheng.database.models.tenant import Tenant, UserTenant
        from bisheng.database.models.user_group import UserGroup
        from bisheng.user.domain.models.user import User

        with tenant_context.bypass_tenant_filter():
            async with database_module.get_async_db_session() as session:
                active_user = (
                    await session.exec(
                        select(User.user_id)
                        .join(UserTenant, UserTenant.user_id == User.user_id)
                        .join(Tenant, Tenant.id == UserTenant.tenant_id)
                        .where(
                            User.user_id == user_id,
                            User.delete == 0,
                            UserTenant.tenant_id == tenant_id,
                            UserTenant.status == "active",
                            UserTenant.is_active == 1,
                            Tenant.status == "active",
                        )
                    )
                ).first()
                if active_user is None:
                    return set()

                subjects = {f"user:{int(user_id)}"}
                department_ids = (
                    await session.exec(
                        select(UserDepartment.department_id)
                        .join(Department, Department.id == UserDepartment.department_id)
                        .where(
                            UserDepartment.user_id == user_id,
                            Department.tenant_id == tenant_id,
                            Department.status == "active",
                        )
                    )
                ).all()
                subjects.update(
                    f"department:{int(row[0] if isinstance(row, tuple) else row)}#member" for row in department_ids
                )

                group_rows = (
                    await session.exec(
                        select(UserGroup.group_id, UserGroup.is_group_admin)
                        .join(Group, Group.id == UserGroup.group_id)
                        .join(Tenant, Tenant.id == Group.tenant_id)
                        .where(
                            UserGroup.user_id == user_id,
                            UserGroup.tenant_id == tenant_id,
                            Group.tenant_id == tenant_id,
                            Tenant.status == "active",
                        )
                    )
                ).all()
                for row in group_rows:
                    group_id = int(getattr(row, "group_id", row[0]))
                    is_admin = bool(getattr(row, "is_group_admin", row[1]))
                    subjects.add(f"user_group:{group_id}#member")
                    if is_admin:
                        subjects.add(f"user_group:{group_id}#admin")
        return subjects

    async def resolve_department_space_path(self, *, resource_type: str, resource_id: str):
        if resource_type != "knowledge_space" or not str(resource_id).isdigit():
            return None
        from bisheng.database.models.department import DepartmentDao
        from bisheng.knowledge.domain.models.department_knowledge_space import (
            DepartmentKnowledgeSpaceDao,
        )

        binding = await DepartmentKnowledgeSpaceDao.aget_by_space_id(int(resource_id))
        if binding is None:
            return None
        department = await DepartmentDao.aget_by_id(int(binding.department_id))
        if department is None or getattr(department, "status", None) != "active":
            return False
        return getattr(department, "path", None) or False
