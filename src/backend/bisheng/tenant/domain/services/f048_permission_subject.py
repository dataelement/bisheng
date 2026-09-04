"""Tenant-owned subject validation for F048 Grant APIs."""

from __future__ import annotations

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.database.models.department import (
    DepartmentDao,
    UserDepartmentDao,
)
from bisheng.database.models.group import GroupDao
from bisheng.database.models.tenant import UserTenantDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.open_api.domain.repositories.service_account_repository import ServiceAccountRepository
from bisheng.permission.domain.services import grant_subject_service
from bisheng.permission.domain.services.grant_source_service import (
    GrantSourceRecord,
    GrantSourceService,
)
from bisheng.permission.domain.services.grant_subject_service import GrantSubjectScope
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)
from bisheng.user.domain.models.user import UserDao


class TenantPermissionSubjectDirectory:
    """Validate subjects and decorate names without entering permission domain."""

    def __init__(self) -> None:
        self._sources = GrantSourceService()

    @staticmethod
    def _prospective_scope(tenant_id: int, resource_type: str) -> GrantSubjectScope:
        if resource_type not in {"knowledge_space", "channel"}:
            raise PermissionInvalidResourceError()
        return GrantSubjectScope(tenant_id=tenant_id, department_path=None)

    async def list_users(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        keyword: str,
        page: int,
        page_size: int,
    ) -> dict[str, object]:
        scope = self._prospective_scope(tenant_id, resource_type)
        rows = await grant_subject_service.list_candidate_users(
            scope,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
        total = await grant_subject_service.count_candidate_users(scope, keyword=keyword)
        return {"data": rows, "total": total}

    async def list_user_groups(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        keyword: str,
        page: int,
        page_size: int,
    ) -> dict[str, object]:
        scope = self._prospective_scope(tenant_id, resource_type)
        rows = await grant_subject_service.list_candidate_user_groups(
            scope,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
        total = await grant_subject_service.count_candidate_user_groups(scope, keyword=keyword)
        return {"data": rows, "total": total}

    async def list_department_children(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        parent_id: int | None,
    ) -> list[dict[str, object]]:
        return await grant_subject_service.list_candidate_department_layer(
            self._prospective_scope(tenant_id, resource_type),
            parent_id=parent_id,
        )

    async def search_departments(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        keyword: str,
        limit: int,
    ) -> dict[str, object]:
        return await grant_subject_service.search_candidate_departments(
            self._prospective_scope(tenant_id, resource_type),
            keyword=keyword,
            limit=limit,
        )

    async def get_department_path(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        department_id: int,
    ) -> dict[str, object]:
        return await grant_subject_service.get_candidate_department_path(
            self._prospective_scope(tenant_id, resource_type),
            dept_id=department_id,
        )

    async def actor_projected_subjects(
        self,
        actor: PermissionActor,
    ) -> frozenset[str]:
        if actor.subject_type == "service_account":
            return frozenset({actor.fga_subject})
        projected = {actor.fga_subject}
        memberships = await UserDepartmentDao.aget_user_departments(actor.user_id)
        departments = await DepartmentDao.aget_by_ids([row.department_id for row in memberships])
        for department in departments:
            if int(department.tenant_id or 0) != actor.current_tenant_id or department.status != "active":
                continue
            projected.add(f"department:{department.id}#member")
            path_ids = [int(value) for value in (department.path or "").split("/") if value.isdigit()]
            for ancestor_id in (*path_ids, int(department.id or 0)):
                if ancestor_id > 0:
                    projected.add(f"department:{ancestor_id}#subtree_member")

        member_groups = await UserGroupDao.aget_user_group(actor.user_id)
        admin_groups = await UserGroupDao.aget_user_admin_group(actor.user_id)
        for membership in (*member_groups, *admin_groups):
            projected.add(f"user_group:{membership.group_id}#member")
        for membership in admin_groups:
            projected.add(f"user_group:{membership.group_id}#admin")
        return frozenset(projected)

    async def canonical_source(
        self,
        *,
        tenant_id: int,
        source_id: int,
        subject_type: str,
        subject_id: str,
        userset_relation: str | None,
        include_children: bool,
    ) -> GrantSourceRecord:
        normalized_type = subject_type.strip().lower()
        normalized_id = subject_id.strip()
        if not normalized_id.isdigit():
            raise PermissionInvalidResourceError()
        identifier = int(normalized_id)
        if normalized_type == "user":
            rows = await UserTenantDao.aget_user_tenants(identifier)
            valid = any(row.tenant_id == tenant_id and row.status == "active" and row.is_active == 1 for row in rows)
            source_type = "DIRECT"
        elif normalized_type == "service_account":
            row = await ServiceAccountRepository.get(identifier)
            valid = bool(row and row.is_enabled and row.tenant_id == tenant_id)
            source_type = "DIRECT"
        elif normalized_type == "department":
            row = await DepartmentDao.aget_by_id(identifier)
            valid = bool(row and row.status == "active" and row.tenant_id == tenant_id)
            source_type = "DEPARTMENT"
        elif normalized_type == "user_group":
            row = await GroupDao.aget_by_id(identifier)
            valid = bool(row and row.tenant_id == tenant_id)
            source_type = "USER_GROUP"
        else:
            raise PermissionInvalidResourceError()
        if not valid:
            raise PermissionInvalidResourceError()
        return self._sources.canonicalize_source(
            source_id=source_id,
            subject_type=normalized_type,
            subject_id=normalized_id,
            source_type=source_type,
            userset_relation=userset_relation,
            include_children=include_children,
        )

    async def display_names(
        self,
        subjects: tuple[tuple[str, str], ...],
    ) -> dict[tuple[str, str], str]:
        user_ids = [
            int(subject_id) for subject_type, subject_id in subjects if subject_type == "user" and subject_id.isdigit()
        ]
        department_ids = [
            int(subject_id)
            for subject_type, subject_id in subjects
            if subject_type == "department" and subject_id.isdigit()
        ]
        group_ids = [
            int(subject_id)
            for subject_type, subject_id in subjects
            if subject_type == "user_group" and subject_id.isdigit()
        ]
        service_account_ids = [
            int(subject_id)
            for subject_type, subject_id in subjects
            if subject_type == "service_account" and subject_id.isdigit()
        ]
        users = await UserDao.aget_user_by_ids(user_ids) if user_ids else []
        departments = await DepartmentDao.aget_by_ids(department_ids) if department_ids else []
        groups = await GroupDao.aget_group_by_ids(group_ids) if group_ids else []
        service_accounts = await ServiceAccountRepository.get_by_ids(service_account_ids)
        return {
            **{("user", str(row.user_id)): row.user_name for row in users or () if row.user_id is not None},
            **{("department", str(row.id)): row.name for row in departments if row.id is not None},
            **{("user_group", str(row.id)): row.group_name for row in groups if row.id is not None},
            **{("service_account", str(row.id)): row.name for row in service_accounts if row.id is not None},
        }

    async def resource_display_names(
        self,
        resources: tuple[tuple[str, str], ...],
    ) -> dict[tuple[str, str], str]:
        """Label the resources a grant can be inherited from.

        The permission layer knows a resource's identity, never its name, so the
        business side resolves labels for both spaces and folders. Unknown or
        missing resources stay unlabeled so callers can use a friendly generic
        fallback without exposing the internal resource key.
        """

        from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao

        knowledge_ids = [
            int(resource_id)
            for resource_type, resource_id in resources
            if resource_type in {"knowledge_space", "knowledge_library"} and resource_id.isdigit()
        ]
        folder_ids = [
            int(resource_id)
            for resource_type, resource_id in resources
            if resource_type == "folder" and resource_id.isdigit()
        ]
        knowledge_rows = await KnowledgeDao.aget_list_by_ids(knowledge_ids) if knowledge_ids else []
        folder_rows = await KnowledgeFileDao.aget_file_by_ids(folder_ids) if folder_ids else []
        knowledge_by_id = {int(row.id): row.name for row in knowledge_rows or () if row.id is not None}
        folder_by_id = {int(row.id): row.file_name for row in folder_rows or () if row.id is not None}
        labels = {
            (resource_type, resource_id): knowledge_by_id[int(resource_id)]
            for resource_type, resource_id in resources
            if resource_type in {"knowledge_space", "knowledge_library"}
            and resource_id.isdigit()
            and int(resource_id) in knowledge_by_id
        }
        labels.update(
            {
                (resource_type, resource_id): folder_by_id[int(resource_id)]
                for resource_type, resource_id in resources
                if resource_type == "folder" and resource_id.isdigit() and int(resource_id) in folder_by_id
            }
        )
        return labels
