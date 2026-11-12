"""Management search shares the lazy tree's authorization scope."""

from fastapi import HTTPException

from bisheng.common.errcode.department import (
    DepartmentMemberNotFoundError,
    DepartmentNotFoundError,
    DepartmentPermissionDeniedError,
)
from bisheng.common.subject_search import normalize_keyword
from bisheng.department.domain.repositories.organization_search_repository import OrganizationSearchRepository
from bisheng.department.domain.services.department_service import _aget_user_scope, _path_in_scope


class OrganizationSearchService:
    @classmethod
    async def search(cls, login_user, keyword, kind, page, limit, include_archived, preferred_department_id):
        is_admin, admin_paths = await _aget_user_scope(login_user)
        try:
            keyword = normalize_keyword(keyword)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if not keyword:
            return {"data": [], "total": 0}
        paths = None if is_admin else admin_paths
        if kind == "departments":
            return await OrganizationSearchRepository.departments(keyword, page, limit, paths, include_archived)
        return await OrganizationSearchRepository.members(
            keyword,
            page,
            limit,
            paths,
            include_archived,
            preferred_department_id,
        )

    @classmethod
    async def locate_member(cls, login_user, dept_id, user_id, limit, is_primary, include_archived):
        is_admin, admin_paths = await _aget_user_scope(login_user)
        department = await OrganizationSearchRepository.department(dept_id)
        if department is None:
            raise DepartmentNotFoundError()
        if not _path_in_scope(department.path, is_admin, admin_paths):
            raise DepartmentPermissionDeniedError()
        if department.status != "active" and not (include_archived and department.status == "archived"):
            raise DepartmentNotFoundError()
        result = await OrganizationSearchRepository.member_location(department.id, user_id, limit, is_primary)
        if result is None:
            raise DepartmentMemberNotFoundError()
        return result
