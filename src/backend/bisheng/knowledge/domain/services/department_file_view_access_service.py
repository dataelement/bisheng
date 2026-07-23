from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import DEFAULT_TENANT_ID
from bisheng.database.constants import AdminRole
from bisheng.database.models.department import Department
from bisheng.database.models.department_admin_grant import DepartmentAdminGrant
from bisheng.knowledge.domain.models.department_knowledge_space import (
    DepartmentKnowledgeSpace,
)
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceOwnerTypeEnum,
    KnowledgeSpaceScope,
)
from bisheng.knowledge.domain.repositories.interfaces.department_file_view_grant_repository import (
    DepartmentFileViewGrantRepository,
)
from bisheng.knowledge.domain.services.department_file_view_grant_audit_writer import (
    DepartmentFileViewGrantAuditWriter,
)
from bisheng.permission.domain.services.fine_grained_permission_service import (
    FineGrainedPermissionService,
)
from bisheng.user.domain.models.user_role import UserRole


class DepartmentFileAccessStatus:
    ALLOWED = "allowed"
    APPROVAL_REQUIRED = "approval_required"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class DepartmentFileAccessSource:
    ADMINISTRATOR = "administrator"
    RESOURCE_OWNER = "resource_owner"
    DEPARTMENT_APPROVER = "department_approver"
    PERMISSION_TEMPLATE = "permission_template"
    APPROVAL_GRANT = "approval_grant"


@dataclass(frozen=True)
class DepartmentFileResource:
    file: Any
    space: Any | None
    scope: Any | None
    binding: Any | None
    department: Any | None
    valid: bool
    applicable: bool = True
    invalid_reason: str | None = None

    @property
    def department_id(self) -> int | None:
        value = getattr(self.binding, "department_id", None)
        return int(value) if value is not None else None


@dataclass(frozen=True)
class DepartmentFileAccessDecision:
    file_id: int
    space_id: int
    status: str
    source: str | None = None
    can_download: bool = False
    department_id: int | None = None
    invalid_reason: str | None = None

    @property
    def allowed(self) -> bool:
        return self.status == DepartmentFileAccessStatus.ALLOWED


ResourceLoader = Callable[
    [list[Any]],
    Awaitable[dict[int, DepartmentFileResource]],
]
PermissionResolver = Callable[
    [Any, list[Any]],
    Awaitable[dict[int, set[str]]],
]
ApproverResolver = Callable[
    [set[int]],
    Awaitable[dict[int, set[int]]],
]


class DepartmentFileViewAccessService:
    def __init__(
        self,
        *,
        grant_repository: DepartmentFileViewGrantRepository,
        session: AsyncSession | None = None,
        resource_loader: ResourceLoader | None = None,
        permission_resolver: PermissionResolver | None = None,
        approver_resolver: ApproverResolver | None = None,
        persist_stale_grant_revalidation: bool = False,
    ):
        self.grant_repository = grant_repository
        self.session = session
        self.resource_loader = resource_loader or self._load_resources
        self.permission_resolver = permission_resolver or self._resolve_permission_ids
        self.approver_resolver = approver_resolver or self._resolve_approvers
        self.persist_stale_grant_revalidation = persist_stale_grant_revalidation

    async def evaluate_file(
        self,
        *,
        login_user: Any,
        file: Any,
    ) -> DepartmentFileAccessDecision:
        decisions = await self.evaluate_files(login_user=login_user, files=[file])
        return decisions[int(file.id)]

    async def evaluate_files(
        self,
        *,
        login_user: Any,
        files: list[Any],
    ) -> dict[int, DepartmentFileAccessDecision]:
        normalized_files = [file for file in files if getattr(file, "id", None) is not None]
        if not normalized_files:
            return {}

        resources = await self.resource_loader(normalized_files)
        valid_resources = {
            file_id: resource for file_id, resource in resources.items() if resource.applicable and resource.valid
        }
        department_ids = {
            int(resource.department_id) for resource in valid_resources.values() if resource.department_id is not None
        }
        tenant_id = int(getattr(login_user, "tenant_id", None) or DEFAULT_TENANT_ID)
        user_id = int(login_user.user_id)
        grant_resources = {
            (int(resource.file.knowledge_id), int(resource.file.id)): int(resource.department_id)
            for resource in valid_resources.values()
            if resource.department_id is not None
        }
        permission_map = await self.permission_resolver(
            login_user,
            normalized_files,
        )
        approver_map = await self.approver_resolver(department_ids)
        grant_map = await self.grant_repository.list_active_by_user_and_files(
            tenant_id=tenant_id,
            user_id=user_id,
            resources=grant_resources,
        )
        if self.persist_stale_grant_revalidation:
            await self._invalidate_stale_grants(
                tenant_id=tenant_id,
                user_id=user_id,
                resources=grant_resources,
            )

        is_admin = bool(callable(getattr(login_user, "is_admin", None)) and login_user.is_admin())
        decisions: dict[int, DepartmentFileAccessDecision] = {}
        for file in normalized_files:
            file_id = int(file.id)
            space_id = int(file.knowledge_id)
            resource = resources.get(file_id)
            if resource is None or not resource.applicable:
                decisions[file_id] = DepartmentFileAccessDecision(
                    file_id=file_id,
                    space_id=space_id,
                    status=DepartmentFileAccessStatus.NOT_APPLICABLE,
                )
                continue
            if not resource.valid or resource.department_id is None:
                decisions[file_id] = DepartmentFileAccessDecision(
                    file_id=file_id,
                    space_id=space_id,
                    status=DepartmentFileAccessStatus.UNAVAILABLE,
                    invalid_reason=resource.invalid_reason or "invalid_binding",
                )
                continue

            permission_ids = permission_map.get(file_id, set())
            can_download = "download_file" in permission_ids
            source: str | None = None
            if is_admin:
                source = DepartmentFileAccessSource.ADMINISTRATOR
            elif user_id in {
                int(getattr(resource.space, "user_id", 0) or 0),
                int(getattr(file, "user_id", 0) or 0),
            }:
                source = DepartmentFileAccessSource.RESOURCE_OWNER
            elif user_id in approver_map.get(int(resource.department_id), set()):
                source = DepartmentFileAccessSource.DEPARTMENT_APPROVER
            elif "view_file" in permission_ids:
                source = DepartmentFileAccessSource.PERMISSION_TEMPLATE
            elif (space_id, file_id) in grant_map:
                source = DepartmentFileAccessSource.APPROVAL_GRANT

            decisions[file_id] = DepartmentFileAccessDecision(
                file_id=file_id,
                space_id=space_id,
                status=(
                    DepartmentFileAccessStatus.ALLOWED
                    if source is not None
                    else DepartmentFileAccessStatus.APPROVAL_REQUIRED
                ),
                source=source,
                can_download=can_download,
                department_id=int(resource.department_id),
            )
        return decisions

    async def _invalidate_stale_grants(
        self,
        *,
        tenant_id: int,
        user_id: int,
        resources: dict[tuple[int, int], int],
    ) -> None:
        if self.session is None:
            raise RuntimeError("DepartmentFileViewAccessService 缺少数据库 session")
        try:
            stale_grants = await self.grant_repository.invalidate_stale_active_by_user_and_files(
                tenant_id=tenant_id,
                user_id=user_id,
                resources=resources,
                reason="read_time_revalidation",
            )
            if not stale_grants:
                return
            audit_writer = DepartmentFileViewGrantAuditWriter(self.session)
            for grant in stale_grants:
                audit_writer.add_transition(
                    grant=grant,
                    operator_id=0,
                    operator_name="system",
                    action="approval.department_file_view.grant.invalidate",
                    old_status="active",
                    new_status=grant.status,
                    reason="read_time_revalidation",
                )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    async def load_resource(self, file: Any) -> DepartmentFileResource:
        resources = await self.resource_loader([file])
        return resources.get(
            int(file.id),
            DepartmentFileResource(
                file=file,
                space=None,
                scope=None,
                binding=None,
                department=None,
                valid=False,
                invalid_reason="invalid_binding",
            ),
        )

    async def resolve_department_approvers(
        self,
        department_id: int,
    ) -> set[int]:
        resolved = await self.approver_resolver({int(department_id)})
        return set(resolved.get(int(department_id), set()))

    async def _load_resources(
        self,
        files: list[Any],
    ) -> dict[int, DepartmentFileResource]:
        if self.session is None:
            raise RuntimeError("DepartmentFileViewAccessService 缺少数据库 session")
        space_ids = {int(file.knowledge_id) for file in files if getattr(file, "knowledge_id", None) is not None}
        spaces_result = await self.session.execute(select(Knowledge).where(Knowledge.id.in_(sorted(space_ids))))
        scopes_result = await self.session.execute(
            select(KnowledgeSpaceScope).where(KnowledgeSpaceScope.space_id.in_(sorted(space_ids)))
        )
        bindings_result = await self.session.execute(
            select(DepartmentKnowledgeSpace).where(DepartmentKnowledgeSpace.space_id.in_(sorted(space_ids)))
        )
        spaces = {int(row.id): row for row in spaces_result.scalars().all()}
        scopes = {int(row.space_id): row for row in scopes_result.scalars().all()}
        bindings = {int(row.space_id): row for row in bindings_result.scalars().all()}
        department_ids = {int(binding.department_id) for binding in bindings.values()}
        department_result = await self.session.execute(
            select(Department).where(Department.id.in_(sorted(department_ids)))
        )
        departments = {int(row.id): row for row in department_result.scalars().all()}

        resources: dict[int, DepartmentFileResource] = {}
        for file in files:
            file_id = int(file.id)
            space_id = int(file.knowledge_id)
            space = spaces.get(space_id)
            scope = scopes.get(space_id)
            binding = bindings.get(space_id)
            scope_level = getattr(getattr(scope, "level", None), "value", getattr(scope, "level", None))
            if scope_level != KnowledgeSpaceLevelEnum.DEPARTMENT.value:
                resources[file_id] = DepartmentFileResource(
                    file=file,
                    space=space,
                    scope=scope,
                    binding=binding,
                    department=None,
                    valid=False,
                    applicable=False,
                )
                continue
            department = departments.get(int(binding.department_id)) if binding is not None else None
            owner_type = getattr(
                getattr(scope, "owner_type", None),
                "value",
                getattr(scope, "owner_type", None),
            )
            tenant_ids = {
                int(value)
                for value in (
                    getattr(file, "tenant_id", None),
                    getattr(space, "tenant_id", None),
                    getattr(scope, "tenant_id", None),
                    getattr(binding, "tenant_id", None),
                    getattr(department, "tenant_id", None),
                )
                if value is not None
            }
            valid = bool(
                space is not None
                and binding is not None
                and department is not None
                and getattr(file, "file_type", None) == FileType.FILE.value
                and getattr(file, "status", None) == KnowledgeFileStatus.SUCCESS.value
                and owner_type == KnowledgeSpaceOwnerTypeEnum.DEPARTMENT.value
                and int(scope.owner_id) == int(binding.department_id)
                and getattr(department, "status", "active") == "active"
                and int(getattr(department, "is_deleted", 0) or 0) == 0
                and len(tenant_ids) <= 1
            )
            resources[file_id] = DepartmentFileResource(
                file=file,
                space=space,
                scope=scope,
                binding=binding,
                department=department,
                valid=valid,
                invalid_reason=None if valid else "invalid_binding",
            )
        return resources

    async def _resolve_permission_ids(
        self,
        login_user: Any,
        files: list[Any],
    ) -> dict[int, set[str]]:
        file_ids = [int(file.id) for file in files]
        view_ids, download_ids = await asyncio.gather(
            FineGrainedPermissionService.filter_object_ids_by_permission_async(
                login_user,
                "knowledge_file",
                file_ids,
                "view_file",
            ),
            FineGrainedPermissionService.filter_object_ids_by_permission_async(
                login_user,
                "knowledge_file",
                file_ids,
                "download_file",
            ),
        )
        result = {file_id: set() for file_id in file_ids}
        for file_id in view_ids:
            result[int(file_id)].add("view_file")
        for file_id in download_ids:
            result[int(file_id)].add("download_file")
        return result

    async def _resolve_approvers(
        self,
        department_ids: set[int],
    ) -> dict[int, set[int]]:
        if not department_ids:
            return {}
        if self.session is None:
            raise RuntimeError("DepartmentFileViewAccessService 缺少数据库 session")
        department_result = await self.session.execute(
            select(Department).where(Department.id.in_(sorted(department_ids)))
        )
        departments = {int(row.id): row for row in department_result.scalars().all()}
        hierarchy_by_department: dict[int, list[int]] = {}
        all_hierarchy_ids: set[int] = set()
        for department_id in department_ids:
            department = departments.get(department_id)
            hierarchy: list[int] = []
            for part in str(getattr(department, "path", "") or "").split("/"):
                if part.isdigit():
                    candidate_id = int(part)
                    if candidate_id not in hierarchy:
                        hierarchy.append(candidate_id)
            if department_id not in hierarchy:
                hierarchy.append(department_id)
            hierarchy_by_department[department_id] = hierarchy
            all_hierarchy_ids.update(hierarchy)

        grants_result = await self.session.execute(
            select(DepartmentAdminGrant).where(DepartmentAdminGrant.department_id.in_(sorted(all_hierarchy_ids)))
        )
        admins_result = await self.session.execute(select(UserRole).where(UserRole.role_id == AdminRole))
        admin_ids_by_department: dict[int, set[int]] = {}
        for row in grants_result.scalars().all():
            admin_ids_by_department.setdefault(
                int(row.department_id),
                set(),
            ).add(int(row.user_id))
        system_admin_ids = {int(row.user_id) for row in admins_result.scalars().all()}

        result: dict[int, set[int]] = {}
        for department_id, hierarchy in hierarchy_by_department.items():
            resolved: set[int] = set()
            for candidate_id in reversed(hierarchy):
                resolved = admin_ids_by_department.get(candidate_id, set())
                if resolved:
                    break
            result[department_id] = set(resolved or system_admin_ids)
        return result

    @staticmethod
    def project_safe_metadata(
        *,
        file_record: Any,
        space_name: str,
        decision: Any,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        file_name = str(getattr(file_record, "file_name", "") or "")
        suffix = PurePosixPath(file_name).suffix.lower().lstrip(".")
        raw_updated_at = getattr(file_record, "update_time", None)
        if isinstance(raw_updated_at, datetime):
            updated_at = raw_updated_at.isoformat()
        elif isinstance(raw_updated_at, str):
            updated_at = raw_updated_at
        else:
            updated_at = ""
        return {
            "id": int(file_record.id),
            "space_id": int(file_record.knowledge_id),
            "file_name": file_name,
            "space_name": space_name,
            "folder_path": str(getattr(file_record, "file_level_path", "") or ""),
            "file_source": getattr(file_record, "file_source", None),
            "file_ext": suffix,
            "file_subcategory_code": getattr(
                file_record,
                "file_subcategory_code",
                None,
            ),
            "tags": list(tags or []),
            "updated_at": updated_at,
            "content_access": decision.status,
            "can_download": bool(decision.can_download),
        }
