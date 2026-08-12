"""Candidate subjects for granting one resource: users, groups, departments.

Answering "who may I grant this resource to" needs a different predicate from
"which users do I administer" — holding `manage_permission` **on the resource**,
not membership of an organisational admin role. The pickers used to ask exactly
this; F048 pointed them at the org-management endpoints instead, so a knowledge
space's manager who administers no department saw an empty user list and a
permission error on the department tree.

The queries here carry over from that earlier implementation, including the
department-space narrowing (F033) and the prefix keyword match that keeps the
`user_name` index usable (F038).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import col, select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import Department, DepartmentDao, UserDepartment
from bisheng.database.models.group import Group
from bisheng.database.models.tenant import UserTenant
from bisheng.knowledge.domain.models.department_knowledge_space import (
    DepartmentKnowledgeSpaceDao,
)
from bisheng.user.domain.models.user import User

# A department-bound space whose department is gone has no candidate in scope;
# an empty path would match everything instead of nothing.
_MATCHES_NOTHING = "\x00never-matches"


@dataclass(frozen=True, slots=True)
class GrantSubjectScope:
    """The resource's tenant, plus the department subtree it is confined to."""

    tenant_id: int
    department_path: str | None


async def resolve_department_space_path(resource_type: str, resource_id: str) -> str | None:
    """Narrow a department-bound knowledge space to that department's subtree.

    Derived from the binding, never from anything the client sends, so a direct
    API call cannot widen the candidate set (F033).
    """

    if resource_type != "knowledge_space":
        return None
    try:
        space_id = int(resource_id)
    except (TypeError, ValueError):
        return None
    binding = await DepartmentKnowledgeSpaceDao.aget_by_space_id(space_id)
    if binding is None:
        return None
    department = await DepartmentDao.aget_by_id(int(binding.department_id))
    if department is None or getattr(department, "status", "active") != "active":
        return _MATCHES_NOTHING
    return str(department.path)


async def list_candidate_users(
    scope: GrantSubjectScope,
    *,
    keyword: str,
    page: int,
    page_size: int,
) -> list[dict]:
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            in_tenant = (
                select(UserTenant.id)
                .where(
                    UserTenant.user_id == User.user_id,
                    UserTenant.tenant_id == scope.tenant_id,
                    UserTenant.status == "active",
                )
                .exists()
            )
            statement = (
                select(User.user_id, User.user_name)
                .where(User.delete == 0, in_tenant)
                .order_by(col(User.user_id).desc())
            )
            if scope.department_path is not None:
                in_subtree = (
                    select(UserDepartment.id)
                    .join(Department, Department.id == UserDepartment.department_id)
                    .where(
                        UserDepartment.user_id == User.user_id,
                        col(Department.path).like(f"{scope.department_path}%"),
                        Department.status == "active",
                    )
                    .exists()
                )
                statement = statement.where(in_subtree)
            if keyword:
                # Prefix match keeps the user_name index usable; a leading
                # wildcard forced a full scan of a 150k-row table (F038).
                statement = statement.where(col(User.user_name).like(f"{keyword}%"))
            rows = (await session.exec(statement.offset((page - 1) * page_size).limit(page_size))).all()
    return [{"user_id": int(row.user_id), "user_name": row.user_name} for row in rows]


async def list_candidate_user_groups(
    scope: GrantSubjectScope,
    *,
    keyword: str,
    page: int,
    page_size: int,
) -> list[dict]:
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            statement = select(Group.id, Group.group_name).where(Group.tenant_id == scope.tenant_id)
            if keyword:
                statement = statement.where(col(Group.group_name).like(f"{keyword}%"))
            statement = statement.order_by(col(Group.id).desc()).offset((page - 1) * page_size).limit(page_size)
            rows = (await session.exec(statement)).all()
    return [{"id": int(row.id), "name": row.group_name} for row in rows]


async def list_candidate_department_layer(
    scope: GrantSubjectScope,
    *,
    parent_id: int | None,
) -> list[dict]:
    """One layer of the department tree, so a large organisation never loads at once."""

    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            statement = select(Department).where(
                Department.tenant_id == scope.tenant_id,
                Department.status == "active",
            )
            if parent_id is None:
                # A department-bound space starts at its own department, not at
                # the tenant root.
                if scope.department_path is not None:
                    statement = statement.where(col(Department.path) == scope.department_path)
                else:
                    statement = statement.where(col(Department.parent_id).is_(None))
            else:
                statement = statement.where(Department.parent_id == parent_id)
                if scope.department_path is not None:
                    statement = statement.where(col(Department.path).like(f"{scope.department_path}%"))
            rows = (await session.exec(statement.order_by(col(Department.id)))).all()
    return await _with_children_flags(rows)


async def search_candidate_departments(
    scope: GrantSubjectScope,
    *,
    keyword: str,
    limit: int,
) -> dict:
    if not keyword:
        return {"roots": [], "total_matches": 0, "truncated": False}
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            statement = select(Department).where(
                Department.tenant_id == scope.tenant_id,
                Department.status == "active",
                col(Department.name).like(f"%{keyword}%"),
            )
            if scope.department_path is not None:
                statement = statement.where(col(Department.path).like(f"{scope.department_path}%"))
            rows = (await session.exec(statement.order_by(col(Department.id)).limit(limit + 1))).all()
    truncated = len(rows) > limit
    matches = list(rows[:limit])
    return {
        "roots": await _with_children_flags(matches),
        "total_matches": len(matches),
        "truncated": truncated,
    }


async def get_candidate_department_path(scope: GrantSubjectScope, *, dept_id: int) -> list[dict]:
    """The ancestor chain of one department, so the picker can reveal it."""

    department = await DepartmentDao.aget_by_id(dept_id)
    if department is None or int(department.tenant_id) != scope.tenant_id:
        return []
    if scope.department_path is not None and not str(department.path).startswith(scope.department_path):
        return []
    ancestor_ids = [int(part) for part in str(department.path).strip("/").split("/") if part.isdigit()]
    if not ancestor_ids:
        return []
    rows = await DepartmentDao.aget_by_ids(ancestor_ids)
    by_id = {int(row.id): row for row in rows if row.id is not None}
    return await _with_children_flags([by_id[dept] for dept in ancestor_ids if dept in by_id])


async def _with_children_flags(rows: list) -> list[dict]:
    """Attach `has_children` for one rendered layer in a single query (F038)."""

    ids = [int(row.id) for row in rows if row.id is not None]
    with_children = await DepartmentDao.aget_children_existence(ids) if ids else set()
    return [
        {
            "id": int(row.id),
            "name": row.name,
            "parent_id": int(row.parent_id) if row.parent_id is not None else None,
            "path": str(row.path),
            "has_children": int(row.id) in with_children,
        }
        for row in rows
    ]
