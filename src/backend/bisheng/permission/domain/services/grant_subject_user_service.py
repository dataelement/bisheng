from __future__ import annotations

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.department.domain.services.department_display_service import (
    get_department_display_name,
)
from bisheng.permission.domain.models.grant_subject_user import (
    GrantSubjectDepartment,
    GrantSubjectDepartmentMembership,
    GrantSubjectUser,
)
from bisheng.permission.domain.repositories.implementations.grant_subject_user_repository_impl import (
    GrantSubjectUserRepositoryImpl,
)
from bisheng.permission.domain.repositories.interfaces.grant_subject_user_repository import (
    GrantSubjectUserRepository,
)


class GrantSubjectUserService:
    def __init__(self, repository: GrantSubjectUserRepository):
        self.repository = repository

    async def list_users(
        self,
        *,
        tenant_id: int,
        keyword: str,
        page: int,
        page_size: int,
        department_id: int | None = None,
        unassigned: bool = False,
    ) -> list[dict]:
        if department_id is not None and unassigned:
            raise ValueError("department_id and unassigned are mutually exclusive")

        departments = await self.repository.list_visible_departments(tenant_id=tenant_id)
        visible_department_ids = tuple(department.department_id for department in departments)
        if department_id is not None and department_id not in visible_department_ids:
            return []

        candidates = await self.repository.list_candidates(
            tenant_id=tenant_id,
            visible_department_ids=visible_department_ids,
            keyword=keyword,
            page=page,
            page_size=page_size,
            department_id=department_id,
            unassigned=unassigned,
        )
        if not candidates:
            return []

        links = await self.repository.list_department_links(
            user_ids=tuple(candidate.user_id for candidate in candidates),
            visible_department_ids=visible_department_ids,
        )
        department_map = {department.department_id: department for department in departments}
        path_map = {
            department.department_id: self._department_path(
                department,
                department_map,
                use_display_name=False,
            )
            for department in departments
        }
        display_path_map = {
            department.department_id: self._department_path(
                department,
                department_map,
                use_display_name=True,
            )
            for department in departments
        }
        links_by_user: dict[int, list[GrantSubjectDepartmentMembership]] = {}
        seen_links: set[tuple[int, int]] = set()
        for link in links:
            link_key = (link.user_id, link.department_id)
            department = department_map.get(link.department_id)
            if department is None or link_key in seen_links:
                continue
            seen_links.add(link_key)
            links_by_user.setdefault(link.user_id, []).append(
                GrantSubjectDepartmentMembership(
                    department_id=department.department_id,
                    dept_id=department.dept_id,
                    name=department.name,
                    short_name=department.short_name,
                    display_name=get_department_display_name(
                        department.name,
                        department.short_name,
                    ),
                    path=path_map[department.department_id],
                    display_path=display_path_map[department.department_id],
                    is_primary=link.is_primary,
                )
            )

        result: list[dict] = []
        for candidate in candidates:
            memberships = links_by_user.get(candidate.user_id, [])
            memberships.sort(key=lambda item: (not item.is_primary, item.path, item.department_id))
            result.append(
                GrantSubjectUser(
                    user_id=candidate.user_id,
                    user_name=candidate.user_name,
                    external_id=candidate.external_id,
                    department_memberships=tuple(memberships),
                ).to_dict()
            )
        return result

    @staticmethod
    def _department_path(
        department: GrantSubjectDepartment,
        department_map: dict[int, GrantSubjectDepartment],
        *,
        use_display_name: bool,
    ) -> str:
        path_ids = [
            int(part)
            for part in department.path.split("/")
            if part.strip().isdigit()
        ]
        labels = []
        for path_id in path_ids:
            path_department = department_map.get(path_id)
            if path_department is None:
                continue
            labels.append(
                get_department_display_name(
                    path_department.name,
                    path_department.short_name,
                )
                if use_display_name
                else path_department.name
            )
        current_name = (
            get_department_display_name(department.name, department.short_name)
            if use_display_name
            else department.name
        )
        if not labels or labels[-1] != current_name:
            labels.append(current_name)
        return "/".join(labels)


async def list_grant_subject_users(
    *,
    tenant_id: int,
    keyword: str,
    page: int,
    page_size: int,
    department_id: int | None = None,
    unassigned: bool = False,
) -> list[dict]:
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            service = GrantSubjectUserService(GrantSubjectUserRepositoryImpl(session))
            return await service.list_users(
                tenant_id=tenant_id,
                keyword=keyword,
                page=page,
                page_size=page_size,
                department_id=department_id,
                unassigned=unassigned,
            )
