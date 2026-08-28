from __future__ import annotations

import logging
from collections.abc import Iterable

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.permission import (
    PermissionDeniedError,
    PermissionInvalidResourceError,
)
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.permission.domain.repositories.grant_subject_query_repository import (
    GrantSubjectQueryRepository,
)

_CREATION_RESOURCE_TYPES = frozenset({"knowledge_space", "channel"})
_VALID_SUBJECT_TYPES = frozenset({"user", "department", "user_group"})
_VALID_OPERATIONS = {
    "user": frozenset({"list"}),
    "user_group": frozenset({"list"}),
    "department": frozenset({"children", "search", "path_tree"}),
}
_MANAGEMENT_PERMISSION_IDS = {
    "knowledge_space": frozenset({"manage_space_relation"}),
    "channel": frozenset({"manage_channel_owner", "manage_channel_manager", "manage_channel_user"}),
}
_EMPTY_TREE = {"roots": [], "total_matches": 0, "truncated": False}
logger = logging.getLogger(__name__)


class GrantSubjectQueryService:
    """Shared grant-subject query and creation-time validation boundary."""

    def __init__(
        self,
        repository: GrantSubjectQueryRepository | None = None,
        *,
        resource_authorization_service=None,
    ):
        self.repository = repository or GrantSubjectQueryRepository()
        self._resource_authorization_service = resource_authorization_service

    def _authorization_service(self):
        if self._resource_authorization_service is None:
            from bisheng.permission.domain.services.resource_authorization_service import (
                ResourceAuthorizationService,
            )

            self._resource_authorization_service = ResourceAuthorizationService()
        return self._resource_authorization_service

    async def prospective_owner_permission_ids(
        self,
        resource_type: str,
        *,
        relation_models: list[dict] | None = None,
    ) -> set[str]:
        return await self._authorization_service().prospective_owner_permission_ids(
            resource_type,
            relation_models=relation_models,
        )

    async def require_creation_management_access(
        self,
        resource_type: str,
        *,
        relation_models: list[dict] | None = None,
    ) -> set[str]:
        if resource_type not in _CREATION_RESOURCE_TYPES:
            raise PermissionInvalidResourceError()
        permission_ids = await self.prospective_owner_permission_ids(
            resource_type,
            relation_models=relation_models,
        )
        if not (_MANAGEMENT_PERMISSION_IDS[resource_type] & permission_ids):
            raise PermissionDeniedError()
        return permission_ids

    async def resolve_creation_tenant_id(self, login_user: UserPayload) -> int:
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            visible_tenants = await login_user.get_visible_tenants()
            tenant_id = visible_tenants[0] if visible_tenants else None
        if tenant_id is None or not await self.repository.is_active_tenant(int(tenant_id)):
            raise PermissionDeniedError()
        return int(tenant_id)

    async def query_creation_subjects(
        self,
        *,
        resource_type: str,
        subject_type: str,
        operation: str,
        login_user: UserPayload,
        keyword: str = "",
        page: int = 1,
        page_size: int = 1000,
        parent_id: int | None = None,
        department_id: int | None = None,
        limit: int = 50,
    ):
        if subject_type not in _VALID_SUBJECT_TYPES or operation not in _VALID_OPERATIONS.get(subject_type, set()):
            raise PermissionInvalidResourceError()
        tenant_id = await self.resolve_creation_tenant_id(login_user)
        await self.require_creation_management_access(resource_type)

        if subject_type == "user":
            return await self.list_users(
                tenant_id=tenant_id,
                keyword=keyword,
                page=page,
                page_size=page_size,
                include_hidden=login_user.is_admin(),
            )
        if subject_type == "user_group":
            return await self.list_user_groups(
                tenant_id=tenant_id,
                keyword=keyword,
                login_user=login_user,
            )
        if operation == "children":
            return await self.list_departments_children(
                tenant_id=tenant_id,
                parent_id=parent_id,
            )
        if operation == "search":
            return await self.search_departments(
                tenant_id=tenant_id,
                keyword=keyword,
                limit=limit,
            )
        if department_id is None:
            raise PermissionInvalidResourceError()
        return await self.get_departments_path_tree(
            tenant_id=tenant_id,
            dept_id=department_id,
        )

    async def validate_creation_grants(
        self,
        *,
        resource_type: str,
        grants: Iterable,
        login_user: UserPayload,
    ) -> None:
        items = list(grants or [])
        if any(item.subject_type == "user" and int(item.subject_id) == int(login_user.user_id) for item in items):
            raise PermissionDeniedError(msg="不能修改自己的权限")
        tenant_id = await self.validate_creation_grant_request(
            resource_type=resource_type,
            grants=items,
            login_user=login_user,
        )
        await self.validate_creation_grant_subjects(
            resource_type=resource_type,
            grants=items,
            login_user=login_user,
            tenant_id=tenant_id,
        )

    async def validate_creation_grant_request(
        self,
        *,
        resource_type: str,
        grants: Iterable,
        login_user: UserPayload,
    ) -> int:
        """Validate request-level grant structure and inviter capability."""
        if resource_type not in _CREATION_RESOURCE_TYPES:
            raise PermissionInvalidResourceError()
        items = list(grants or [])
        if not items:
            return await self.resolve_creation_tenant_id(login_user)
        if any(
            item.subject_type not in _VALID_SUBJECT_TYPES or (item.relation == "owner" and item.subject_type != "user")
            for item in items
        ):
            raise PermissionDeniedError()
        if any(item.relation not in {"owner", "manager", "editor", "viewer"} for item in items):
            raise PermissionDeniedError()

        authorization_service = self._authorization_service()
        relation_models = await authorization_service.get_relation_models()
        caller_permission_ids = await self.require_creation_management_access(
            resource_type,
            relation_models=relation_models,
        )
        await authorization_service.validate_grants_for_permissions(
            resource_type=resource_type,
            grants=items,
            caller_permission_ids=caller_permission_ids,
            relation_models=relation_models,
        )

        return await self.resolve_creation_tenant_id(login_user)

    async def validate_creation_grant_subjects(
        self,
        *,
        resource_type: str,
        grants: Iterable,
        login_user: UserPayload,
        tenant_id: int,
    ) -> None:
        """Validate only subjects that must fail the whole creation request."""
        if resource_type not in _CREATION_RESOURCE_TYPES:
            raise PermissionInvalidResourceError()
        items = list(grants or [])
        if not items:
            return
        if any(item.subject_type == "user" and int(item.subject_id) == int(login_user.user_id) for item in items):
            raise PermissionDeniedError(msg="不能修改自己的权限")

        user_ids = {int(item.subject_id) for item in items if item.subject_type == "user"}
        department_ids = {int(item.subject_id) for item in items if item.subject_type == "department"}
        user_group_ids = {int(item.subject_id) for item in items if item.subject_type == "user_group"}
        if user_ids and not await self.repository.users_exist_in_tenant(user_ids, tenant_id):
            raise PermissionDeniedError()
        if department_ids and not await self.repository.departments_exist_in_tenant(department_ids, tenant_id):
            raise PermissionDeniedError()
        if user_group_ids and not await self.repository.user_groups_exist_in_tenant(user_group_ids, tenant_id):
            raise PermissionDeniedError()

    async def validate_resource_grants(
        self,
        *,
        resource_type: str,
        resource_id: str,
        grants: Iterable,
    ) -> None:
        """Revalidate grant subjects against the resource tenant before tuple writes."""
        items = list(grants or [])
        if not items:
            return
        if any(item.subject_type not in _VALID_SUBJECT_TYPES for item in items):
            raise PermissionDeniedError()

        from bisheng.permission.domain.services.permission_service import PermissionService

        tenant_id = await PermissionService._resolve_resource_tenant(resource_type, resource_id)
        if tenant_id is None or not await self.repository.is_active_tenant(int(tenant_id)):
            raise PermissionDeniedError()
        tenant_id = int(tenant_id)

        user_ids = {int(item.subject_id) for item in items if item.subject_type == "user"}
        department_ids = {int(item.subject_id) for item in items if item.subject_type == "department"}
        user_group_ids = {int(item.subject_id) for item in items if item.subject_type == "user_group"}
        if user_ids and not await self.repository.users_exist_in_tenant(user_ids, tenant_id):
            raise PermissionDeniedError()
        if department_ids and not await self.repository.departments_exist_in_tenant(department_ids, tenant_id):
            raise PermissionDeniedError()
        if user_group_ids and not await self.repository.user_groups_exist_in_tenant(user_group_ids, tenant_id):
            raise PermissionDeniedError()

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
        return await self.repository.list_users(
            tenant_id=tenant_id,
            keyword=keyword,
            page=page,
            page_size=page_size,
            restrict_dept_path=restrict_dept_path,
            include_hidden=include_hidden,
        )

    async def list_departments_children(
        self,
        *,
        tenant_id: int,
        parent_id: int | None = None,
        restrict_root_path: str | None = None,
    ) -> list[dict]:
        return await self.repository.list_departments_children(
            tenant_id=tenant_id,
            parent_id=parent_id,
            restrict_root_path=restrict_root_path,
        )

    async def search_departments(
        self,
        *,
        tenant_id: int,
        keyword: str,
        limit: int = 50,
        restrict_root_path: str | None = None,
    ) -> dict:
        return await self.repository.search_departments(
            tenant_id=tenant_id,
            keyword=keyword,
            limit=limit,
            restrict_root_path=restrict_root_path,
        )

    async def get_departments_path_tree(
        self,
        *,
        tenant_id: int,
        dept_id: int,
        restrict_root_path: str | None = None,
    ) -> dict:
        return await self.repository.get_departments_path_tree(
            tenant_id=tenant_id,
            dept_id=dept_id,
            restrict_root_path=restrict_root_path,
        )

    async def list_user_groups(
        self,
        *,
        tenant_id: int,
        keyword: str,
        login_user: UserPayload,
    ) -> list[dict]:
        can_view_all = await self._can_view_all_user_groups(login_user)
        return await self.repository.list_user_groups(
            tenant_id=tenant_id,
            keyword=keyword,
            viewer_user_id=int(login_user.user_id),
            can_view_all=can_view_all,
        )

    @staticmethod
    async def _can_view_all_user_groups(login_user: UserPayload) -> bool:
        is_admin = getattr(login_user, "is_admin", None)
        if bool(getattr(login_user, "is_global_super", False)) or (callable(is_admin) and is_admin()):
            return True
        tenant_id = getattr(login_user, "tenant_id", None)
        if tenant_id is None:
            return False
        from bisheng.permission.domain.services.permission_service import PermissionService

        try:
            return await PermissionService.check(
                user_id=login_user.user_id,
                relation="admin",
                object_type="tenant",
                object_id=str(tenant_id),
                login_user=login_user,
            )
        except Exception as error:
            logger.warning(
                "tenant admin permission check failed for user=%s tenant=%s: %s",
                getattr(login_user, "user_id", None),
                tenant_id,
                error,
            )
            return False

    async def query_resource_users(
        self,
        *,
        resource_type: str,
        resource_id: str,
        login_user: UserPayload,
        keyword: str,
        page: int,
        page_size: int,
    ) -> list[dict]:
        tenant_id, restrict_path, empty = await self._resource_query_context(resource_type, resource_id, login_user)
        if empty:
            return []
        return await self.list_users(
            tenant_id=tenant_id,
            keyword=keyword,
            page=page,
            page_size=page_size,
            restrict_dept_path=restrict_path,
            include_hidden=login_user.is_admin(),
        )

    async def query_resource_departments(
        self,
        *,
        resource_type: str,
        resource_id: str,
        login_user: UserPayload,
        operation: str,
        parent_id: int | None = None,
        keyword: str = "",
        limit: int = 50,
        department_id: int | None = None,
    ):
        tenant_id, restrict_path, empty = await self._resource_query_context(resource_type, resource_id, login_user)
        if empty:
            return [] if operation == "children" else dict(_EMPTY_TREE)
        if operation == "children":
            return await self.list_departments_children(
                tenant_id=tenant_id,
                parent_id=parent_id,
                restrict_root_path=restrict_path,
            )
        if operation == "search":
            return await self.search_departments(
                tenant_id=tenant_id,
                keyword=keyword,
                limit=limit,
                restrict_root_path=restrict_path,
            )
        if operation != "path_tree" or department_id is None:
            raise PermissionInvalidResourceError()
        return await self.get_departments_path_tree(
            tenant_id=tenant_id,
            dept_id=department_id,
            restrict_root_path=restrict_path,
        )

    async def query_resource_user_groups(
        self,
        *,
        resource_type: str,
        resource_id: str,
        login_user: UserPayload,
        keyword: str,
    ) -> list[dict]:
        tenant_id, restrict_path, empty = await self._resource_query_context(resource_type, resource_id, login_user)
        if empty or restrict_path is not None:
            return []
        return await self.list_user_groups(
            tenant_id=tenant_id,
            keyword=keyword,
            login_user=login_user,
        )

    async def _resource_query_context(
        self,
        resource_type: str,
        resource_id: str,
        login_user: UserPayload,
    ) -> tuple[int | None, str | None, bool]:
        from bisheng.permission.domain.schemas.permission_schema import VALID_RESOURCE_TYPES
        from bisheng.permission.domain.services.fine_grained_permission_service import (
            FineGrainedPermissionService,
        )
        from bisheng.permission.domain.services.permission_service import PermissionService

        if resource_type not in VALID_RESOURCE_TYPES:
            raise PermissionInvalidResourceError()
        management_ids = self._resource_management_permission_ids(resource_type)
        if management_ids:
            permission_ids = await FineGrainedPermissionService.get_effective_permission_ids_async(
                login_user,
                resource_type,
                resource_id,
                nearest_binding_wins=resource_type in {"folder", "knowledge_file"},
            )
            allowed = bool(management_ids & set(permission_ids))
        else:
            allowed = await PermissionService.check(
                user_id=login_user.user_id,
                relation="can_edit",
                object_type=resource_type,
                object_id=resource_id,
                login_user=login_user,
            )
        if not allowed:
            raise PermissionDeniedError()

        tenant_id = await PermissionService._resolve_resource_tenant(resource_type, resource_id)
        if tenant_id is None:
            tenant_id = get_current_tenant_id()
        if tenant_id is None or not await self.repository.is_active_tenant(int(tenant_id)):
            return None, None, True
        restrict_path = await self.repository.resolve_department_space_path(
            resource_type=resource_type,
            resource_id=resource_id,
        )
        if restrict_path is False:
            return int(tenant_id), None, True
        return int(tenant_id), restrict_path, False

    @staticmethod
    def _resource_management_permission_ids(resource_type: str) -> set[str]:
        direct = {
            "knowledge_space": "manage_space_relation",
            "folder": "manage_folder_relation",
            "knowledge_file": "manage_file_relation",
        }.get(resource_type)
        if direct:
            return {direct}
        tier_prefix = {
            "workflow": "app",
            "assistant": "app",
            "tool": "tool",
            "knowledge_library": "kb",
            "channel": "channel",
        }.get(resource_type)
        if not tier_prefix:
            return set()
        return {
            f"manage_{tier_prefix}_owner",
            f"manage_{tier_prefix}_manager",
            f"manage_{tier_prefix}_{'user' if resource_type == 'channel' else 'viewer'}",
        }
