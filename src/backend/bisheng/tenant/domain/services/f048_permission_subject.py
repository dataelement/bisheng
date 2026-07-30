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
from bisheng.permission.domain.services.grant_source_service import (
    GrantSourceRecord,
    GrantSourceService,
)
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)
from bisheng.user.domain.models.user import UserDao


class TenantPermissionSubjectDirectory:
    """Validate subjects and decorate names without entering permission domain."""

    def __init__(self) -> None:
        self._sources = GrantSourceService()

    async def actor_projected_subjects(
        self,
        actor: PermissionActor,
    ) -> frozenset[str]:
        projected = {f"user:{actor.user_id}"}
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
        users = await UserDao.aget_user_by_ids(user_ids) if user_ids else []
        departments = await DepartmentDao.aget_by_ids(department_ids) if department_ids else []
        groups = await GroupDao.aget_group_by_ids(group_ids) if group_ids else []
        return {
            **{("user", str(row.user_id)): row.user_name for row in users or () if row.user_id is not None},
            **{("department", str(row.id)): row.name for row in departments if row.id is not None},
            **{("user_group", str(row.id)): row.group_name for row in groups if row.id is not None},
        }
