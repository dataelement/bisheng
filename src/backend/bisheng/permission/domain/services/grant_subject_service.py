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

from fastapi import HTTPException
from sqlmodel import col, select

from bisheng.common.subject_search import normalize_keyword
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import Department, DepartmentDao, UserDepartment
from bisheng.department.domain.services.department_service import (
    DepartmentService,
    _dept_node_dict,
)
from bisheng.knowledge.domain.models.department_knowledge_space import (
    DepartmentKnowledgeSpaceDao,
)
from bisheng.permission.application.access import get_grant_subject_directory

# A department-bound space whose department is gone has no candidate in scope;
# an empty path would match everything instead of nothing.
_MATCHES_NOTHING = "\x00never-matches"


def _keyword(value: str) -> str:
    try:
        return normalize_keyword(value)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


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
    directory = await get_grant_subject_directory()
    rows = await directory.candidate_users(scope, keyword=_keyword(keyword), page=page, page_size=page_size)
    # The picker prints the staff id after the name and the department under it,
    # so people with the same display name can be told apart.
    paths = await _primary_department_paths([int(row.user_id) for row in rows])
    return [
        {
            "user_id": int(row.user_id),
            "user_name": row.user_name,
            "external_id": row.external_id,
            "primary_department_path": paths.get(int(row.user_id)),
        }
        for row in rows
    ]


async def count_candidate_users(scope: GrantSubjectScope, *, keyword: str) -> int:
    directory = await get_grant_subject_directory()
    return await directory.count_candidate_users(scope, keyword=_keyword(keyword))


async def _primary_department_paths(user_ids: list[int]) -> dict[int, str]:
    """Each user's primary department as a readable name chain, in one round trip."""

    if not user_ids:
        return {}
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            rows = (
                await session.exec(
                    select(UserDepartment.user_id, Department.path)
                    .join(Department, Department.id == UserDepartment.department_id)
                    .where(
                        col(UserDepartment.user_id).in_(user_ids),
                        UserDepartment.is_primary == 1,
                        Department.status == "active",
                    )
                )
            ).all()
    if not rows:
        return {}
    needed: set[int] = set()
    for row in rows:
        needed.update(int(part) for part in str(row.path).strip("/").split("/") if part.isdigit())
    names = {int(d.id): d.name for d in await DepartmentDao.aget_by_ids(list(needed)) if d.id is not None}
    resolved: dict[int, str] = {}
    for row in rows:
        chain = [
            names[int(part)] for part in str(row.path).strip("/").split("/") if part.isdigit() and int(part) in names
        ]
        if chain:
            resolved[int(row.user_id)] = "/".join(chain)
    return resolved


async def list_candidate_user_groups(
    scope: GrantSubjectScope,
    *,
    keyword: str,
    page: int,
    page_size: int,
) -> list[dict]:
    directory = await get_grant_subject_directory()
    rows = await directory.candidate_groups(scope, keyword=_keyword(keyword), page=page, page_size=page_size)
    return [{"id": int(row.id), "name": row.group_name} for row in rows]


async def count_candidate_user_groups(scope: GrantSubjectScope, *, keyword: str) -> int:
    directory = await get_grant_subject_directory()
    return await directory.count_candidate_groups(scope, keyword=_keyword(keyword))


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
    return await _as_tree_nodes(rows)


async def search_candidate_departments(
    scope: GrantSubjectScope,
    *,
    keyword: str,
    limit: int,
) -> dict:
    keyword = _keyword(keyword)
    if not keyword:
        return {"roots": [], "total_matches": 0, "truncated": False}
    directory = await get_grant_subject_directory()
    rows = await directory.candidate_departments(scope, keyword=keyword, limit=limit + 1)
    truncated = len(rows) > limit
    matches = list(rows[:limit])
    roots = await DepartmentService.abuild_forest_within_subtree(
        matches,
        {int(row.id) for row in matches if row.id is not None},
        confined_to_path=None if scope.department_path is None else scope.department_path,
    )
    return {"roots": roots, "total_matches": len(matches), "truncated": truncated}


async def get_candidate_department_path(scope: GrantSubjectScope, *, dept_id: int) -> dict:
    """Reveal one department: the pruned tree from the root down to it.

    Same envelope as the org-management locate endpoint, because the picker's
    tree renders the two interchangeably.
    """

    empty = {"roots": [], "total_matches": 0, "truncated": False}
    department = await DepartmentDao.aget_by_id(dept_id)
    if department is None or int(department.tenant_id) != scope.tenant_id:
        return empty
    if scope.department_path is not None and not str(department.path).startswith(scope.department_path):
        return empty
    roots = await DepartmentService.abuild_forest_within_subtree(
        [department],
        {int(department.id)},
        confined_to_path=scope.department_path,
    )
    return {"roots": roots, "total_matches": 1, "truncated": False}


async def _as_tree_nodes(rows: list) -> list[dict]:
    """One rendered layer, in the org tree's node shape (`has_children` batched)."""

    ids = [int(row.id) for row in rows if row.id is not None]
    with_children = await DepartmentDao.aget_children_existence(ids) if ids else set()
    return [_dept_node_dict(row, has_children=int(row.id) in with_children) for row in rows]
