import asyncio
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, TYPE_CHECKING

from fastapi import Request
from loguru import logger
from sqlmodel import select

from bisheng.api.v1.schemas import KnowledgeFileOne, FileProcessBase, ExcelRule
from bisheng.common.dependencies.user_deps import UserPayload  # noqa: F401 – kept for type hints
from bisheng.common.errcode.knowledge_space import (
    SpaceLimitError,
    SpaceNotFoundError,
    SpaceFolderNotFoundError,
    SpaceFolderDepthError,
    SpaceFolderDuplicateError,
    SpaceFileNotFoundError,
    SpaceFileExtensionError,
    SpaceFileNameDuplicateError,
    SpaceSubscribePrivateError,
    SpaceSubscribeLimitError,
    SpacePermissionDeniedError,
    SpaceTagExistsError,
    SpaceFileSizeLimitError,
    SpaceTenantMismatchError,
)
from bisheng.common.errcode.llm import WorkbenchEmbeddingError
from bisheng.common.models.space_channel_member import (
    SpaceChannelMember,
    SpaceChannelMemberDao,
    BusinessTypeEnum,
    UserRoleEnum,
    MembershipStatusEnum,
)
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import DepartmentDao
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import TagDao, TagBusinessTypeEnum, Tag
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.department_knowledge_space import (
    DepartmentKnowledgeSpaceDao,
)
from bisheng.knowledge.domain.models.knowledge import (
    Knowledge,
    KnowledgeDao,
    KnowledgeTypeEnum,
    AuthTypeEnum,
    KnowledgeRead,
    KnowledgeState,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileDao,
    KnowledgeFileStatus,
    FileType,
    FileSource,
)
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import (
    KnowledgeDocumentVersion,
)
from bisheng.knowledge.domain.models.knowledge_space_file import SpaceFileDao
from bisheng.knowledge.domain.models.knowledge_space_tag_library import (
    KnowledgeSpaceTagLibraryDao,
)
from bisheng.workstation.domain.services.workstation_service import WorkStationService
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    KnowledgeSpaceInfoResp,
    SpaceMemberResponse,
    SpaceMemberPageResponse,
    UpdateSpaceMemberRoleRequest,
    RemoveSpaceMemberRequest,
    SpaceSubscriptionStatusEnum,
    KnowledgeSpaceFileResponse,
)
from bisheng.common.errcode.knowledge import KnowledgeSpaceTagLibraryInvalidError
from bisheng.knowledge.domain.services.knowledge_audit_telemetry_service import (
    KnowledgeAuditTelemetryService,
)
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.domain.services.knowledge_space_tag_library_service import (
    KnowledgeSpaceTagLibraryService,
)
from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils
from bisheng.approval.domain.services.approval_gate import ApprovalGate
from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateRequest
from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.approval.domain.services.knowledge_space_subscribe_scenario_handler import (
    KnowledgeSpaceSubscribeScenarioHandler,
)
from bisheng.llm.domain import LLMService
from bisheng.permission.domain.knowledge_space_permission_template import (
    default_permission_ids_for_relation,
)
from bisheng.permission.domain.schemas.permission_schema import (
    AuthorizeGrantItem,
    AuthorizeRevokeItem,
)
from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
from bisheng.permission.domain.services.fine_grained_permission_service import (
    FineGrainedPermissionService,
)
from bisheng.permission.domain.services.owner_service import OwnerService
from bisheng.permission.domain.services.permission_service import PermissionService
from bisheng.role.domain.services.quota_service import QuotaService
from bisheng.user.domain.models.user import UserDao
from bisheng.utils import generate_uuid
from bisheng.worker.knowledge import file_worker

if TYPE_CHECKING:
    from bisheng.message.domain.services.message_service import MessageService
    from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_version_repository import (
        KnowledgeDocumentVersionRepository,
    )

# Maximum number of Knowledge Spaces a user can create
_MAX_SPACE_PER_USER = 30
# Maximum number of spaces a user can subscribe to (not as creator)
_MAX_SUBSCRIBE_PER_USER = 50
SPACE_ADMIN_ASSIGNMENT_MESSAGE = "assigned_knowledge_space_admin"
_SPACE_MEMBER_ROLE_TO_RELATION = {
    UserRoleEnum.CREATOR: "owner",
    UserRoleEnum.ADMIN: "manager",
    UserRoleEnum.MEMBER: "viewer",
}
_SPACE_RELATION_LEVEL = {
    "can_read": 1,
    "can_edit": 2,
    "can_manage": 3,
    "can_delete": 4,
}
_SPACE_MEMBER_RELATION_LEVEL = {
    "viewer": 1,
    "editor": 2,
    "manager": 3,
    "owner": 4,
}

_logger = logging.getLogger(__name__)

_PERMISSION_LEVEL_TO_RELATION = {
    "owner": "owner",
    "can_manage": "manager",
    "can_edit": "editor",
    "can_read": "viewer",
}

_CHILD_PERMISSION_SCAN_BATCH_SIZE = 100
_CHILD_PERMISSION_CHECK_CONCURRENCY = 8


class KnowledgeSpaceService(KnowledgeUtils):
    """Service for Knowledge Space operations.
    Instance-based; each method receives login_user as an argument.
    All business logic is async; DB access is delegated to DAO classes.
    """

    def __init__(self, request: Request, login_user: UserPayload):
        self.request = request
        self.login_user = login_user
        self.message_service: Optional["MessageService"] = None
        self.approval_gate: Optional[ApprovalGate] = None
        # Injected by DI factory after construction (same pattern as message_service).
        # When set, list_space_children will exclude non-primary version files and
        # return version enrichment fields.
        self.version_repo: Optional["KnowledgeDocumentVersionRepository"] = None

    def _ensure_space_async_task_tenant_consistency(
        self, space: Knowledge, operation: str
    ) -> None:
        current_tid = get_current_tenant_id()
        space_tid = space.tenant_id
        if space_tid is None or current_tid in (None, space_tid):
            return

        logger.warning(
            "reject knowledge space async operation across tenant boundary: "
            "space_id={} space_tenant_id={} current_tenant_id={} user_id={} operation={}",
            space.id,
            space_tid,
            current_tid,
            self.login_user.user_id,
            operation,
        )
        raise SpaceTenantMismatchError.http_exception()

    # ──────────────────────────── Permission helpers ───────────────────────────

    # Roles with write access to a space
    _WRITE_ROLES = {UserRoleEnum.CREATOR, UserRoleEnum.ADMIN}

    @staticmethod
    def _resolve_subscription_status(
        membership: Optional[SpaceChannelMember],
    ) -> SpaceSubscriptionStatusEnum:
        if membership is None:
            return SpaceSubscriptionStatusEnum.NOT_SUBSCRIBED
        if membership.is_active:
            return SpaceSubscriptionStatusEnum.SUBSCRIBED
        if membership.is_pending:
            return SpaceSubscriptionStatusEnum.PENDING
        if membership.is_recently_rejected():
            return SpaceSubscriptionStatusEnum.REJECTED
        return SpaceSubscriptionStatusEnum.NOT_SUBSCRIBED

    @staticmethod
    def _resolve_subscription_status_from_fields(
        status: Optional[str],
        update_time: Optional[datetime],
    ) -> SpaceSubscriptionStatusEnum:
        """Resolve subscription status from raw DB fields (from SQL JOIN result)."""
        if status is None:
            return SpaceSubscriptionStatusEnum.NOT_SUBSCRIBED
        if status == MembershipStatusEnum.ACTIVE:
            return SpaceSubscriptionStatusEnum.SUBSCRIBED
        if status == MembershipStatusEnum.PENDING:
            return SpaceSubscriptionStatusEnum.PENDING
        if status == MembershipStatusEnum.REJECTED:
            from bisheng.common.models.space_channel_member import (
                REJECTED_STATUS_DISPLAY_WINDOW,
            )

            if (
                update_time
                and update_time >= datetime.now() - REJECTED_STATUS_DISPLAY_WINDOW
            ):
                return SpaceSubscriptionStatusEnum.REJECTED
        return SpaceSubscriptionStatusEnum.NOT_SUBSCRIBED

    @staticmethod
    def _apply_subscription_flags(
        result: KnowledgeSpaceInfoResp,
        subscription_status: SpaceSubscriptionStatusEnum,
    ) -> None:
        result.subscription_status = subscription_status
        result.is_followed = (
            subscription_status == SpaceSubscriptionStatusEnum.SUBSCRIBED
        )
        result.is_pending = subscription_status == SpaceSubscriptionStatusEnum.PENDING

    @staticmethod
    def _permission_level_to_space_user_role(
        permission_level: Optional[str],
    ) -> Optional[UserRoleEnum]:
        if permission_level in ("owner", "can_manage"):
            # The UI only knows creator/admin/member. A direct owner grant must
            # preserve manage semantics without masquerading as the creator.
            return UserRoleEnum.ADMIN
        if permission_level in ("can_edit", "can_read"):
            return UserRoleEnum.MEMBER
        return None

    async def _decorate_department_metadata(
        self,
        spaces: List[KnowledgeSpaceInfoResp],
    ) -> List[KnowledgeSpaceInfoResp]:
        if not spaces:
            return spaces
        space_ids = [int(space.id) for space in spaces]
        bindings = await DepartmentKnowledgeSpaceDao.aget_by_space_ids(space_ids)
        if not bindings:
            return spaces
        binding_map = {binding.space_id: binding for binding in bindings}
        departments = await DepartmentDao.aget_by_ids(
            [binding.department_id for binding in bindings]
        )
        department_name_map = {dept.id: dept.name for dept in departments}
        for space in spaces:
            binding = binding_map.get(int(space.id))
            if binding is None:
                continue
            space.space_kind = "department"
            space.department_id = binding.department_id
            space.department_name = department_name_map.get(binding.department_id)
            space.approval_enabled = binding.approval_enabled
            space.sensitive_check_enabled = binding.sensitive_check_enabled
        return spaces

    async def _format_accessible_spaces(
        self,
        space_ids: List[int],
        order_by: str,
        *,
        memberships: Optional[List[SpaceChannelMember]] = None,
        exclude_created: bool = False,
        required_permission_id: Optional[str] = None,
    ) -> List[KnowledgeRead]:
        if not space_ids:
            return []

        membership_map = {
            int(member.business_id): member for member in (memberships or [])
        }
        spaces = await KnowledgeDao.async_get_spaces_by_ids(space_ids, order_by)
        if exclude_created:
            spaces = [
                space for space in spaces if space.user_id != self.login_user.user_id
            ]
        if not spaces:
            return []

        permission_space_ids = [
            space.id
            for space in spaces
            if space.user_id != self.login_user.user_id
            and space.id not in membership_map
        ]
        permission_id_space_ids = [
            space.id for space in spaces if space.user_id != self.login_user.user_id
        ]
        permission_levels = {}
        permission_ids_map: Dict[int, set[str]] = {}
        if permission_space_ids:
            levels = await asyncio.gather(
                *[
                    PermissionService.get_permission_level(
                        user_id=self.login_user.user_id,
                        object_type="knowledge_space",
                        object_id=str(space_id),
                        login_user=self.login_user,
                    )
                    for space_id in permission_space_ids
                ]
            )
            permission_levels = {
                space_id: level for space_id, level in zip(permission_space_ids, levels)
            }
        if required_permission_id and permission_id_space_ids:
            permission_ids = await asyncio.gather(
                *[
                    self._get_effective_permission_ids(
                        "knowledge_space",
                        space_id,
                    )
                    for space_id in permission_id_space_ids
                ]
            )
            permission_ids_map = {
                space_id: ids
                for space_id, ids in zip(permission_id_space_ids, permission_ids)
            }

        pinned_spaces = []
        normal_spaces = []
        for space in spaces:
            member_conf = membership_map.get(space.id)
            result = KnowledgeSpaceInfoResp(
                **space.model_dump(),
                is_pinned=bool(member_conf and member_conf.is_pinned),
            )

            if space.user_id == self.login_user.user_id:
                result.user_role = UserRoleEnum.CREATOR
                self._apply_subscription_flags(
                    result, SpaceSubscriptionStatusEnum.SUBSCRIBED
                )
            elif member_conf:
                if (
                    required_permission_id
                    and required_permission_id
                    not in permission_ids_map.get(space.id, set())
                ):
                    continue
                result.user_role = member_conf.user_role
                self._apply_subscription_flags(
                    result, self._resolve_subscription_status(member_conf)
                )
            else:
                if (
                    required_permission_id
                    and required_permission_id
                    not in permission_ids_map.get(space.id, set())
                ):
                    continue
                result.user_role = self._permission_level_to_space_user_role(
                    permission_levels.get(space.id),
                )
                if result.user_role is None:
                    continue
                self._apply_subscription_flags(
                    result, SpaceSubscriptionStatusEnum.SUBSCRIBED
                )

            if result.is_pinned:
                pinned_spaces.append(result)
            else:
                normal_spaces.append(result)

        return await self._decorate_department_metadata(pinned_spaces + normal_spaces)

    async def _require_write_permission(self, space_id: int) -> None:
        """
        Verify that the current user has can_edit permission on the space
        via explicit ReBAC or active space membership.
        """
        allowed = await PermissionService.check(
            user_id=self.login_user.user_id,
            relation="can_edit",
            object_type="knowledge_space",
            object_id=str(space_id),
            login_user=self.login_user,
        )
        if not allowed:
            allowed = await self._membership_satisfies_relation(space_id, "can_edit")
        if not allowed:
            raise SpacePermissionDeniedError()

    async def _require_manage_permission(self, space_id: int) -> None:
        """
        Verify that the current user has can_manage permission on the space
        (required for member management operations).
        """
        allowed = await PermissionService.check(
            user_id=self.login_user.user_id,
            relation="can_manage",
            object_type="knowledge_space",
            object_id=str(space_id),
            login_user=self.login_user,
        )
        if not allowed:
            allowed = await self._membership_satisfies_relation(space_id, "can_manage")
        if not allowed:
            raise SpacePermissionDeniedError()

    async def _require_delete_permission(self, space_id: int) -> Knowledge:
        """
        Verify that the current user has can_delete permission on the space.
        """
        space = await KnowledgeDao.aquery_by_id(space_id)
        if not space or space.type != KnowledgeTypeEnum.SPACE.value:
            raise SpaceNotFoundError()
        allowed = await PermissionService.check(
            user_id=self.login_user.user_id,
            relation="can_delete",
            object_type="knowledge_space",
            object_id=str(space_id),
            login_user=self.login_user,
        )
        if not allowed:
            allowed = await self._membership_satisfies_relation(space_id, "can_delete")
        if not allowed:
            raise SpacePermissionDeniedError()
        return space

    async def _require_resource_permission(
        self,
        relation: str,
        object_type: str,
        object_id: int,
    ) -> None:
        if relation == "can_read" and object_type in {"folder", "knowledge_file"}:
            permission_ids = await self._get_effective_permission_ids(
                object_type, object_id
            )
            required_permission = (
                "view_folder" if object_type == "folder" else "view_file"
            )
            if required_permission in permission_ids:
                return
            raise SpacePermissionDeniedError()

        allowed = await PermissionService.check(
            user_id=self.login_user.user_id,
            relation=relation,
            object_type=object_type,
            object_id=str(object_id),
            login_user=self.login_user,
        )
        if not allowed:
            space_id = await self._space_id_for_resource(object_type, object_id)
            if space_id is not None:
                allowed = await self._membership_satisfies_relation(space_id, relation)
        if not allowed:
            raise SpacePermissionDeniedError()

    @staticmethod
    def _dedupe_ids(resource_ids: List[int]) -> List[int]:
        return list(dict.fromkeys(resource_ids))

    @staticmethod
    def _ensure_space_folder(
        folder: Optional[KnowledgeFile], space_id: int
    ) -> KnowledgeFile:
        if (
            not folder
            or folder.file_type != FileType.DIR.value
            or folder.knowledge_id != space_id
        ):
            raise SpaceFolderNotFoundError()
        return folder

    @staticmethod
    def _ensure_space_file(
        file_record: Optional[KnowledgeFile],
        space_id: int,
        *,
        allow_folder: bool = False,
    ) -> KnowledgeFile:
        if not file_record or file_record.knowledge_id != space_id:
            raise SpaceFileNotFoundError()
        if not allow_folder and file_record.file_type != FileType.FILE.value:
            raise SpaceFileNotFoundError()
        return file_record

    async def _get_space_files_or_raise(
        self, space_id: int, file_ids: List[int]
    ) -> List[KnowledgeFile]:
        unique_file_ids = self._dedupe_ids(file_ids)
        if not unique_file_ids:
            return []
        file_records = await KnowledgeFileDao.aget_file_by_ids(unique_file_ids)
        if len(file_records) != len(unique_file_ids):
            raise SpaceFileNotFoundError()
        for file_record in file_records:
            self._ensure_space_file(file_record, space_id)
        return file_records

    async def _require_folder_relation(
        self,
        space_id: int,
        folder_id: int,
        relation: str,
    ) -> KnowledgeFile:
        await self._require_read_permission(space_id)
        folder = await KnowledgeFileDao.query_by_id(folder_id)
        folder = self._ensure_space_folder(folder, space_id)
        await self._require_resource_permission(relation, "folder", folder.id)
        return folder

    async def _get_folder_for_action(
        self, space_id: int, folder_id: int
    ) -> KnowledgeFile:
        folder = await KnowledgeFileDao.query_by_id(folder_id)
        return self._ensure_space_folder(folder, space_id)

    async def _require_file_relation(
        self,
        file_id: int,
        relation: str,
        *,
        space_id: Optional[int] = None,
    ) -> KnowledgeFile:
        file_record = await KnowledgeFileDao.query_by_id(file_id)
        if not file_record:
            raise SpaceFileNotFoundError()
        actual_space_id = space_id or file_record.knowledge_id
        await self._require_read_permission(actual_space_id)
        file_record = self._ensure_space_file(file_record, actual_space_id)
        await self._require_resource_permission(
            relation, "knowledge_file", file_record.id
        )
        return file_record

    async def _get_file_for_action(
        self,
        file_id: int,
        *,
        space_id: Optional[int] = None,
    ) -> KnowledgeFile:
        file_record = await KnowledgeFileDao.query_by_id(file_id)
        if not file_record:
            raise SpaceFileNotFoundError()
        return self._ensure_space_file(
            file_record, space_id or file_record.knowledge_id
        )

    async def _require_file_or_folder_relation(
        self,
        space_id: int,
        resource_id: int,
        relation: str,
    ) -> KnowledgeFile:
        resource = await KnowledgeFileDao.query_by_id(resource_id)
        if not resource:
            raise SpaceFileNotFoundError()
        if resource.file_type == FileType.DIR.value:
            return await self._require_folder_relation(space_id, resource_id, relation)
        return await self._require_file_relation(
            resource_id, relation, space_id=space_id
        )

    async def _get_active_space_membership(
        self, space_id: int
    ) -> Optional[SpaceChannelMember]:
        member = await SpaceChannelMemberDao.async_find_member(
            space_id, self.login_user.user_id
        )
        if member and member.is_active:
            return member
        return None

    async def _membership_satisfies_relation(
        self, space_id: int, relation: str
    ) -> bool:
        required_level = _SPACE_RELATION_LEVEL.get(relation)
        if required_level is None:
            return False
        member = await self._get_active_space_membership(space_id)
        if not member:
            return False
        member_relation = _SPACE_MEMBER_ROLE_TO_RELATION.get(member.user_role)
        return (
            _SPACE_MEMBER_RELATION_LEVEL.get(member_relation or "", 0) >= required_level
        )

    async def _membership_permission_ids(self, space_id: int) -> set[str]:
        member = await self._get_active_space_membership(space_id)
        if not member:
            return set()
        relation = _SPACE_MEMBER_ROLE_TO_RELATION.get(member.user_role)
        return default_permission_ids_for_relation(relation or "")

    @staticmethod
    def _build_item_lineage(
        item: KnowledgeFile, space_id: int
    ) -> List[tuple[str, int]]:
        object_type = (
            "folder" if item.file_type == FileType.DIR.value else "knowledge_file"
        )
        ancestor_ids = [
            int(part) for part in (item.file_level_path or "").split("/") if part
        ]
        return (
            [(object_type, item.id)]
            + [("folder", fid) for fid in reversed(ancestor_ids)]
            + [
                ("knowledge_space", space_id),
            ]
        )

    async def _space_id_for_resource(
        self, object_type: str, object_id: int
    ) -> Optional[int]:
        if object_type == "knowledge_space":
            return int(object_id)
        if object_type in {"folder", "knowledge_file"}:
            resource = await KnowledgeFileDao.query_by_id(object_id)
            if resource:
                return resource.knowledge_id
        return None

    async def _write_resource_parent_tuple(
        self,
        object_type: str,
        object_id: int,
        parent_type: str,
        parent_id: int,
    ) -> None:
        try:
            await PermissionService.batch_write_tuples(
                [
                    TupleOperation(
                        action="write",
                        user=f"{parent_type}:{parent_id}",
                        relation="parent",
                        object=f"{object_type}:{object_id}",
                    ),
                ],
                crash_safe=True,
                raise_on_failure=True,
                stop_on_failure=True,
            )
        except Exception as e:
            _logger.exception(
                "Failed to write parent tuple %s:%s -> %s:%s: %s",
                parent_type,
                parent_id,
                object_type,
                object_id,
                e,
            )
            raise

    async def _initialize_child_resource_permissions(
        self,
        object_type: str,
        object_id: int,
        parent_type: str,
        parent_id: int,
    ) -> None:
        await self._write_resource_parent_tuple(
            object_type, object_id, parent_type, parent_id
        )
        try:
            await OwnerService.write_owner_tuple(
                self.login_user.user_id,
                object_type,
                str(object_id),
                enforce_fga_success=True,
            )
        except Exception as e:
            _logger.exception(
                "Failed to write owner tuple for %s %s: %s",
                object_type,
                object_id,
                e,
            )
            raise

    async def _cleanup_resource_tuples(self, resources: List[tuple[str, int]]) -> None:
        for resource_type, resource_id in resources:
            try:
                await OwnerService.delete_resource_tuples(
                    resource_type, str(resource_id)
                )
            except Exception as e:
                _logger.warning(
                    "Failed to delete FGA tuples for %s %s: %s",
                    resource_type,
                    resource_id,
                    e,
                )

    async def _get_relation_models_map(self) -> Dict[str, dict]:
        if hasattr(self, "_relation_models_map_cache"):
            return self._relation_models_map_cache
        from bisheng.permission.api.endpoints.resource_permission import (
            _get_relation_models,
            _normalize_model_dict,
        )

        raw_models = await _get_relation_models()
        self._relation_models_map_cache = {
            m["id"]: _normalize_model_dict(m) for m in raw_models
        }
        return self._relation_models_map_cache

    async def _get_relation_bindings(self) -> List[dict]:
        if hasattr(self, "_relation_bindings_cache"):
            return self._relation_bindings_cache
        from bisheng.permission.api.endpoints.resource_permission import _get_bindings

        self._relation_bindings_cache = await _get_bindings()
        return self._relation_bindings_cache

    @staticmethod
    def _is_direct_space_user_binding(
        binding: dict, space_id: int, user_id: int
    ) -> bool:
        return (
            binding.get("resource_type") == "knowledge_space"
            and str(binding.get("resource_id")) == str(space_id)
            and binding.get("subject_type") == "user"
            and str(binding.get("subject_id")) == str(user_id)
        )

    @classmethod
    async def sync_direct_space_user_permissions(
        cls,
        space_id: int,
        user_id: int,
        user_role: Optional[UserRoleEnum],
        *,
        is_active: bool,
    ) -> None:
        """Keep direct space memberships and ReBAC grants in sync."""
        from bisheng.permission.api.endpoints.resource_permission import (
            _binding_key_with_scope,
            _get_bindings,
            _save_bindings,
        )

        desired_relation = None
        if is_active and user_role is not None:
            desired_relation = _SPACE_MEMBER_ROLE_TO_RELATION.get(user_role)
            if desired_relation == "owner":
                desired_relation = None

        relations_to_revoke = {"viewer", "editor", "manager"}
        if desired_relation:
            relations_to_revoke.discard(desired_relation)

        revokes = [
            AuthorizeRevokeItem(
                subject_type="user",
                subject_id=int(user_id),
                relation=relation,
                include_children=False,
            )
            for relation in sorted(relations_to_revoke)
        ]
        grants = []
        if desired_relation:
            grants.append(
                AuthorizeGrantItem(
                    subject_type="user",
                    subject_id=int(user_id),
                    relation=desired_relation,
                    include_children=False,
                    model_id=desired_relation,
                )
            )

        await PermissionService.authorize(
            object_type="knowledge_space",
            object_id=str(space_id),
            grants=grants,
            revokes=revokes,
            enforce_fga_success=True,
        )

        bindings = await _get_bindings()
        updated_bindings = [
            binding
            for binding in bindings
            if not cls._is_direct_space_user_binding(binding, space_id, user_id)
        ]
        if desired_relation:
            key = _binding_key_with_scope(
                "knowledge_space",
                str(space_id),
                "user",
                int(user_id),
                desired_relation,
                None,
            )
            updated_bindings.append(
                {
                    "key": key,
                    "resource_type": "knowledge_space",
                    "resource_id": str(space_id),
                    "subject_type": "user",
                    "subject_id": int(user_id),
                    "relation": desired_relation,
                    "include_children": None,
                    "model_id": desired_relation,
                }
            )
        await _save_bindings(updated_bindings)

    @staticmethod
    def _should_preserve_private_space_tuple(
        creator_user_id: int,
        resource_type: str,
        tuple_item: dict,
    ) -> bool:
        relation = tuple_item.get("relation")
        tuple_user = tuple_item.get("user")
        if resource_type == "knowledge_space":
            return relation == "owner" and tuple_user == f"user:{creator_user_id}"
        if resource_type in {"folder", "knowledge_file"}:
            return relation == "parent"
        return False

    @classmethod
    async def clear_space_authorization_for_private(
        cls,
        *,
        space: Knowledge,
        child_resources: List[tuple[str, int]],
    ) -> None:
        """Remove non-owner space permissions when a space becomes private."""
        from bisheng.permission.api.endpoints.resource_permission import (
            _get_bindings,
            _save_bindings,
        )

        resources = [("knowledge_space", int(space.id))] + list(child_resources)
        resource_keys = {
            (resource_type, str(resource_id))
            for resource_type, resource_id in resources
        }

        bindings = await _get_bindings()
        await _save_bindings(
            [
                binding
                for binding in bindings
                if (binding.get("resource_type"), str(binding.get("resource_id")))
                not in resource_keys
            ]
        )

        fga = await PermissionService._aget_fga()
        if fga is None:
            raise RuntimeError(
                "FGAClient not available while clearing private-space permissions"
            )

        operations: List[TupleOperation] = []
        for resource_type, resource_id in resources:
            tuples = await fga.read_tuples(object=f"{resource_type}:{resource_id}")
            for tuple_item in tuples:
                if cls._should_preserve_private_space_tuple(
                    space.user_id, resource_type, tuple_item
                ):
                    continue
                operations.append(
                    TupleOperation(
                        action="delete",
                        user=tuple_item["user"],
                        relation=tuple_item["relation"],
                        object=tuple_item["object"],
                    )
                )

        if operations:
            await PermissionService.batch_write_tuples(
                operations,
                crash_safe=True,
                raise_on_failure=True,
                stop_on_failure=True,
            )

        await OwnerService.write_owner_tuple(
            space.user_id,
            "knowledge_space",
            str(space.id),
            enforce_fga_success=True,
        )

    async def _revoke_direct_space_user_permissions(
        self, space_id: int, user_id: int
    ) -> None:
        """Remove direct ReBAC grants and UI binding metadata for a space user."""
        await self.__class__.sync_direct_space_user_permissions(
            space_id,
            user_id,
            None,
            is_active=False,
        )
        if hasattr(self, "_relation_bindings_cache"):
            delattr(self, "_relation_bindings_cache")

    async def _get_current_user_subject_strings(self) -> set[str]:
        if hasattr(self, "_current_user_subjects_cache"):
            return self._current_user_subjects_cache

        self._current_user_subjects_cache = (
            await FineGrainedPermissionService.get_current_user_subject_strings(
                self.login_user,
            )
        )
        return self._current_user_subjects_cache

    async def _get_binding_department_paths(
        self, bindings: List[dict]
    ) -> Dict[int, str]:
        if hasattr(self, "_binding_department_paths_cache"):
            return self._binding_department_paths_cache

        department_ids = {
            int(binding["subject_id"])
            for binding in bindings
            if binding.get("subject_type") == "department"
            and binding.get("include_children")
        }
        departments = await DepartmentDao.aget_by_ids(list(department_ids))
        self._binding_department_paths_cache = {
            dept.id: dept.path or "" for dept in departments
        }
        return self._binding_department_paths_cache

    @staticmethod
    def _permission_ids_for_relation(
        relation: str,
        model: Optional[dict] = None,
    ) -> set[str]:
        # Runtime is permission-first. If a relation model explicitly defines
        # permissions[], those ids are authoritative for action checks.
        if model is not None:
            permissions = model.get("permissions") or []
            if permissions:
                return set(permissions)
            # Built-in system models still rely on their canonical defaults.
            if model.get("is_system"):
                return default_permission_ids_for_relation(model.get("relation"))
            return set()
        # Legacy tuples without binding metadata fall back to system defaults so
        # old data remains readable during migration.
        return default_permission_ids_for_relation(relation)

    @staticmethod
    def _user_matches_binding(
        binding: dict,
        tuple_user: str,
        user_subject_strings: set[str],
    ) -> bool:
        if tuple_user not in user_subject_strings:
            return False

        expected = (
            f"user:{binding['subject_id']}"
            if binding.get("subject_type") == "user"
            else f"{binding.get('subject_type')}:{binding['subject_id']}#member"
        )
        return tuple_user == expected

    async def _resolve_binding_for_tuple(
        self,
        resource_type: str,
        resource_id: int,
        tuple_user: str,
        relation: str,
        bindings: List[dict],
        binding_department_paths: Dict[int, str],
        user_subject_strings: set[str],
    ) -> Optional[dict]:
        exact_subject_type = "user"
        exact_subject_id = None
        if tuple_user.startswith("user_group:"):
            exact_subject_type = "user_group"
            exact_subject_id = int(tuple_user.split(":", 1)[1].split("#", 1)[0])
        elif tuple_user.startswith("department:"):
            exact_subject_type = "department"
            exact_subject_id = int(tuple_user.split(":", 1)[1].split("#", 1)[0])
        elif tuple_user.startswith("user:"):
            exact_subject_id = int(tuple_user.split(":", 1)[1])

        for binding in bindings:
            if binding.get("resource_type") != resource_type or str(
                binding.get("resource_id")
            ) != str(resource_id):
                continue
            if binding.get("relation") != relation:
                continue
            if exact_subject_id is not None and not binding.get("include_children"):
                if (
                    binding.get("subject_type") == exact_subject_type
                    and int(binding.get("subject_id")) == exact_subject_id
                    and self._user_matches_binding(
                        binding,
                        tuple_user,
                        user_subject_strings,
                    )
                ):
                    return binding

        if tuple_user.startswith("department:"):
            tuple_department_id = int(tuple_user.split(":", 1)[1].split("#", 1)[0])
            tuple_department_rows = await DepartmentDao.aget_by_ids(
                [tuple_department_id]
            )
            tuple_department_path = (
                tuple_department_rows[0].path if tuple_department_rows else ""
            )
            for binding in bindings:
                if binding.get("resource_type") != resource_type or str(
                    binding.get("resource_id")
                ) != str(resource_id):
                    continue
                if binding.get("relation") != relation:
                    continue
                if binding.get("subject_type") != "department" or not binding.get(
                    "include_children"
                ):
                    continue
                binding_path = binding_department_paths.get(
                    int(binding.get("subject_id"))
                )
                if (
                    binding_path
                    and tuple_department_path
                    and tuple_department_path.startswith(binding_path)
                ):
                    return binding
        return None

    async def _build_resource_lineage(
        self,
        object_type: str,
        object_id: int,
        *,
        space_id: Optional[int] = None,
    ) -> List[tuple[str, int]]:
        if object_type == "knowledge_space":
            return [("knowledge_space", object_id)]

        if object_type == "folder":
            folder = await KnowledgeFileDao.query_by_id(object_id)
            folder = self._ensure_space_folder(folder, space_id or folder.knowledge_id)
            ancestor_ids = [
                int(part) for part in (folder.file_level_path or "").split("/") if part
            ]
            return (
                [("folder", folder.id)]
                + [("folder", fid) for fid in reversed(ancestor_ids)]
                + [
                    ("knowledge_space", folder.knowledge_id),
                ]
            )

        if object_type == "knowledge_file":
            file_record = await KnowledgeFileDao.query_by_id(object_id)
            file_record = self._ensure_space_file(
                file_record, space_id or file_record.knowledge_id
            )
            ancestor_ids = [
                int(part)
                for part in (file_record.file_level_path or "").split("/")
                if part
            ]
            return (
                [("knowledge_file", file_record.id)]
                + [("folder", fid) for fid in reversed(ancestor_ids)]
                + [
                    ("knowledge_space", file_record.knowledge_id),
                ]
            )

        return [(object_type, object_id)]

    async def _get_effective_permission_ids(
        self,
        object_type: str,
        object_id: int,
        *,
        space_id: Optional[int] = None,
    ) -> set[str]:
        # Evaluate permissions across the resource lineage from child -> parent.
        # For a tuple backed by a custom relation model, permissions[] controls
        # runtime actions. Relation-only defaults are kept only as a legacy
        # fallback for old tuples or built-in system models.
        lineage = await self._build_resource_lineage(
            object_type, object_id, space_id=space_id
        )
        user_subject_strings = await self._get_current_user_subject_strings()
        bindings = await self._get_relation_bindings()
        binding_department_paths = await self._get_binding_department_paths(bindings)
        models = await self._get_relation_models_map()
        lineage_binding_can_override = object_type in {"folder", "knowledge_file"}
        (
            effective_permissions,
            matched_lineage_binding,
        ) = await FineGrainedPermissionService.get_effective_permission_ids_async(
            self.login_user,
            object_type,
            object_id,
            models=models,
            bindings=bindings,
            binding_department_paths=binding_department_paths,
            user_subject_strings=user_subject_strings,
            lineage=lineage,
            nearest_binding_wins=lineage_binding_can_override,
            return_match_metadata=True,
        )
        for lineage_type, lineage_id in lineage:
            if lineage_type == "knowledge_space":
                if not (lineage_binding_can_override and matched_lineage_binding):
                    effective_permissions.update(
                        await self._membership_permission_ids(int(lineage_id))
                    )
                break
        effective_permissions.update(
            await self._public_space_viewer_permission_ids(lineage)
        )
        return effective_permissions

    async def _build_child_permission_context(self, space_id: int) -> dict:
        user_subject_strings = await self._get_current_user_subject_strings()
        bindings = await self._get_relation_bindings()
        binding_department_paths = await self._get_binding_department_paths(bindings)
        models = await self._get_relation_models_map()
        membership_permission_ids = await self._membership_permission_ids(space_id)
        public_space_permission_ids = await self._public_space_viewer_permission_ids(
            [("knowledge_space", space_id)]
        )
        return {
            "models": models,
            "bindings": bindings,
            "binding_department_paths": binding_department_paths,
            "user_subject_strings": user_subject_strings,
            "membership_permission_ids": membership_permission_ids,
            "public_space_permission_ids": public_space_permission_ids,
            "tuple_cache": {},
            "tuple_department_paths": {},
        }

    async def _get_child_item_effective_permission_ids(
        self,
        item: KnowledgeFile,
        *,
        space_id: int,
        context: dict,
    ) -> set[str]:
        object_type = (
            "folder" if item.file_type == FileType.DIR.value else "knowledge_file"
        )
        lineage = self._build_item_lineage(item, space_id)
        (
            effective_permissions,
            matched_lineage_binding,
        ) = await FineGrainedPermissionService.get_effective_permission_ids_async(
            self.login_user,
            object_type,
            item.id,
            models=context["models"],
            bindings=context["bindings"],
            binding_department_paths=context["binding_department_paths"],
            user_subject_strings=context["user_subject_strings"],
            lineage=lineage,
            nearest_binding_wins=True,
            return_match_metadata=True,
            tuple_cache=context["tuple_cache"],
            tuple_department_paths=context["tuple_department_paths"],
        )
        if not matched_lineage_binding:
            effective_permissions.update(context["membership_permission_ids"])
        effective_permissions.update(context["public_space_permission_ids"])
        return effective_permissions

    async def _public_space_viewer_permission_ids(
        self, lineage: List[tuple[str, int]]
    ) -> set[str]:
        space_id = next(
            (
                lineage_id
                for lineage_type, lineage_id in lineage
                if lineage_type == "knowledge_space"
            ),
            None,
        )
        if space_id is None:
            return set()
        space = await KnowledgeDao.aquery_by_id(int(space_id))
        if (
            space
            and space.type == KnowledgeTypeEnum.SPACE.value
            and space.is_released
            and space.auth_type == AuthTypeEnum.PUBLIC
        ):
            return default_permission_ids_for_relation("viewer")
        return set()

    async def _require_permission_id(
        self,
        object_type: str,
        object_id: int,
        permission_id: str,
        *,
        space_id: Optional[int] = None,
    ) -> None:
        effective_permissions = await self._get_effective_permission_ids(
            object_type,
            object_id,
            space_id=space_id,
        )
        if permission_id not in effective_permissions:
            raise SpacePermissionDeniedError()

    async def _list_space_child_resources(self, space_id: int) -> List[tuple[str, int]]:
        async with get_async_db_session() as session:
            rows = (
                await session.exec(
                    select(KnowledgeFile.id, KnowledgeFile.file_type).where(
                        KnowledgeFile.knowledge_id == space_id,
                    )
                )
            ).all()
        return [
            ("folder", resource_id)
            if file_type == FileType.DIR.value
            else ("knowledge_file", resource_id)
            for resource_id, file_type in rows
        ]

    async def _require_read_permission(self, space_id: int) -> Knowledge:
        space = await KnowledgeDao.aquery_by_id(space_id)
        if not space or space.type != KnowledgeTypeEnum.SPACE.value:
            raise SpaceNotFoundError()
        effective_permissions = await self._get_effective_permission_ids(
            "knowledge_space", space_id
        )
        if "view_space" not in effective_permissions:
            raise SpacePermissionDeniedError()
        return space

    @staticmethod
    def _is_square_preview_space(space: Knowledge) -> bool:
        return space.is_released and space.auth_type in {
            AuthTypeEnum.PUBLIC,
            AuthTypeEnum.APPROVAL,
        }

    async def _require_space_info_permission(
        self, space_id: int
    ) -> tuple[Knowledge, bool]:
        space = await KnowledgeDao.aquery_by_id(space_id)
        if not space or space.type != KnowledgeTypeEnum.SPACE.value:
            raise SpaceNotFoundError()
        effective_permissions = await self._get_effective_permission_ids(
            "knowledge_space", space_id
        )
        if "view_space" in effective_permissions:
            return space, True
        if self._is_square_preview_space(space):
            return space, False
        raise SpacePermissionDeniedError()

    # ──────────────────────────── Space CRUD ──────────────────────────────────

    @staticmethod
    async def _is_auto_tag_feature_visible() -> bool:
        (
            cfg,
            _inherited,
            _src,
            _has_override,
        ) = await WorkStationService.get_knowledge_space_config_with_meta()
        return bool(getattr(cfg, "auto_tag_visible", False)) if cfg else False

    @staticmethod
    async def _decorate_auto_tag_for_info(result: KnowledgeSpaceInfoResp) -> None:
        """Populate ``auto_tag_mode`` / ``auto_tag_custom_tags`` for the detail
        view and mask private library ids from the wire.

        A space is in "custom" mode when its bound library is the private one
        whose ``owner_knowledge_id`` equals the space id. In that case the
        client never sees the private library id — only the resolved tag list
        — so it cannot be re-bound from another space.
        """
        library_id = result.auto_tag_library_id
        if not library_id:
            result.auto_tag_mode = "library"
            result.auto_tag_custom_tags = None
            return
        library = await KnowledgeSpaceTagLibraryDao.aget(library_id)
        if (
            library
            and library.owner_knowledge_id is not None
            and library.owner_knowledge_id == result.id
        ):
            result.auto_tag_mode = "custom"
            result.auto_tag_custom_tags = list(library.tags or [])
            result.auto_tag_library_id = None
        else:
            result.auto_tag_mode = "library"
            result.auto_tag_custom_tags = None

    @classmethod
    async def _apply_auto_tag_binding(
        cls,
        *,
        knowledge: Knowledge,
        auto_tag_enabled: bool,
        auto_tag_library_id: Optional[int],
        auto_tag_custom_tags: Optional[List[str]],
        user_id: int,
        tenant_id: Optional[int],
    ) -> tuple[bool, Optional[int]]:
        """Resolve the auto-tag fields for a knowledge space.

        Handles three modes for the *desired* state and reconciles any
        existing private library bound to ``knowledge.id``:

        * ``auto_tag_enabled=False`` — tear down any private library and
          unbind ``auto_tag_library_id``.
        * ``auto_tag_custom_tags`` provided — upsert a private library and
          point ``auto_tag_library_id`` at it. Any prior private library row
          for this knowledge id is overwritten in place.
        * ``auto_tag_library_id`` provided — validate the public library,
          then delete any orphan private library for this space.

        Returns the resolved ``(enabled, library_id)`` pair to persist.
        """
        if not auto_tag_enabled:
            await KnowledgeSpaceTagLibraryDao.adelete_private_for_knowledge(
                knowledge.id
            )
            return False, None

        if auto_tag_library_id is not None and auto_tag_custom_tags is not None:
            raise KnowledgeSpaceTagLibraryInvalidError(
                message="不能同时指定标签库与自定义标签"
            )

        if auto_tag_custom_tags is not None:
            normalized = KnowledgeSpaceTagLibraryService.normalize_tags(
                auto_tag_custom_tags
            )
            if not normalized:
                raise KnowledgeSpaceTagLibraryInvalidError(
                    message="开启自动标签时必须提供至少一个自定义标签"
                )
            private = await KnowledgeSpaceTagLibraryDao.aupsert_private(
                knowledge_id=knowledge.id,
                tenant_id=tenant_id,
                user_id=user_id,
                tags=normalized,
            )
            return True, private.id

        # library mode
        await KnowledgeSpaceTagLibraryService.validate_bindable_library(
            auto_tag_library_id
        )
        # Clean up any leftover private library when switching custom → library
        await KnowledgeSpaceTagLibraryDao.adelete_private_for_knowledge(knowledge.id)
        return True, auto_tag_library_id

    async def create_knowledge_space(
        self,
        name: str,
        description: Optional[str] = None,
        icon: Optional[str] = None,
        auth_type: AuthTypeEnum = AuthTypeEnum.PUBLIC,
        is_released: bool = False,
        auto_tag_enabled: bool = False,
        auto_tag_library_id: Optional[int] = None,
        auto_tag_custom_tags: Optional[List[str]] = None,
        share_to_children: Optional[bool] = None,
        skip_user_limit: bool = False,
    ) -> Knowledge:
        """Create a new knowledge space (max 30 per user).

        F017: when the creator's leaf tenant is Root, ``share_to_children``
        controls whether the new space is shared with all active Child Tenants.
        ``None`` means "use ``Root.share_default_to_children``"; ``True`` / ``False``
        override. Child-tenant creators never share (caller value ignored).
        """

        if not skip_user_limit:
            count = await KnowledgeDao.async_count_spaces_by_user(
                self.login_user.user_id,
                exclude_department_spaces=True,
            )
            if count >= _MAX_SPACE_PER_USER:
                raise SpaceLimitError()

        workbench_llm = await LLMService.get_workbench_llm()
        if not workbench_llm or not workbench_llm.embedding_model:
            raise WorkbenchEmbeddingError()

        # Defence-in-depth: a tenant with the feature flag off must not be able to
        # configure auto-tag by hand-crafting requests.
        if not await self._is_auto_tag_feature_visible():
            auto_tag_enabled = False
            auto_tag_library_id = None
            auto_tag_custom_tags = None
        # Library-id needs the freshly minted knowledge.id when we are upserting
        # a private library, so defer the auto-tag fields until after insert.
        db_knowledge = Knowledge(
            name=name,
            description=description,
            icon=icon,
            auth_type=auth_type,
            type=KnowledgeTypeEnum.SPACE.value,
            model=workbench_llm.embedding_model.id,
            is_released=is_released,
            auto_tag_enabled=False,
            auto_tag_library_id=None,
        )

        knowledge_space = KnowledgeService.create_knowledge_base(
            self.request, self.login_user, db_knowledge, skip_hook=True
        )

        if (
            auto_tag_enabled
            or auto_tag_library_id is not None
            or auto_tag_custom_tags is not None
        ):
            resolved_enabled, resolved_library_id = await self._apply_auto_tag_binding(
                knowledge=knowledge_space,
                auto_tag_enabled=auto_tag_enabled,
                auto_tag_library_id=auto_tag_library_id,
                auto_tag_custom_tags=auto_tag_custom_tags,
                user_id=self.login_user.user_id,
                tenant_id=self.login_user.tenant_id,
            )
            if resolved_enabled or resolved_library_id is not None:
                knowledge_space.auto_tag_enabled = resolved_enabled
                knowledge_space.auto_tag_library_id = resolved_library_id
                knowledge_space = await KnowledgeDao.async_update_space(knowledge_space)

        member = SpaceChannelMember(
            business_id=str(knowledge_space.id),
            business_type=BusinessTypeEnum.SPACE,
            user_id=self.login_user.user_id,
            user_role=UserRoleEnum.CREATOR,
            status=MembershipStatusEnum.ACTIVE,
        )
        await SpaceChannelMemberDao.async_insert_member(member)

        # F008: Write owner tuple to OpenFGA (INV-2)
        try:
            await OwnerService.write_owner_tuple(
                self.login_user.user_id,
                "knowledge_space",
                str(knowledge_space.id),
            )
        except Exception as e:
            _logger.warning(
                "Failed to write owner tuple for knowledge_space %s: %s",
                knowledge_space.id,
                e,
            )

        # F017: fan out group-sharing for Root-created resources.
        # share_on_create handles the Root-only gate, FGA writes, is_shared
        # DB flip, and audit_log in one shot.
        from bisheng.tenant.domain.services.resource_share_service import (
            ResourceShareService,
        )

        await ResourceShareService.share_on_create(
            "knowledge_space",
            str(knowledge_space.id),
            creator_tenant_id=self.login_user.tenant_id,
            operator_id=self.login_user.user_id,
            operator_tenant_id=self.login_user.tenant_id,
            explicit=share_to_children,
        )

        # Audit log for knowledge space creation
        await KnowledgeAuditTelemetryService.audit_create_knowledge_space(
            self.login_user, self.request, knowledge_space
        )

        return knowledge_space

    async def get_space_info(self, space_id: int) -> KnowledgeSpaceInfoResp:
        from bisheng.worker import rebuild_knowledge_celery

        space, has_content_permission = await self._require_space_info_permission(
            space_id
        )

        follower_num = await SpaceChannelMemberDao.async_count_space_members(space_id)
        total_file_num = (
            await KnowledgeFileDao.async_count_success_files_batch([space_id])
        ).get(space_id, 0)
        result = KnowledgeSpaceInfoResp(**space.model_dump())
        if space.user_id != self.login_user.user_id:
            create_user = await UserDao.aget_user(space.user_id)
            result.user_name = (
                create_user.user_name if create_user else str(space.user_id)
            )
        else:
            result.user_name = self.login_user.user_name
        if space.user_id == self.login_user.user_id:
            result.user_role = UserRoleEnum.CREATOR
            self._apply_subscription_flags(
                result, SpaceSubscriptionStatusEnum.SUBSCRIBED
            )
        else:
            member_info = await SpaceChannelMemberDao.async_find_member(
                space_id=space.id,
                user_id=self.login_user.user_id,
            )
            if member_info:
                self._apply_subscription_flags(
                    result, self._resolve_subscription_status(member_info)
                )
                if member_info.is_active:
                    result.user_role = member_info.user_role
            elif has_content_permission and not self.login_user.is_admin():
                self._apply_subscription_flags(
                    result, SpaceSubscriptionStatusEnum.SUBSCRIBED
                )
            if result.user_role is None and has_content_permission:
                level = await PermissionService.get_permission_level(
                    user_id=self.login_user.user_id,
                    object_type="knowledge_space",
                    object_id=str(space_id),
                    login_user=self.login_user,
                )
                result.user_role = self._permission_level_to_space_user_role(level)
            if result.user_role is None and has_content_permission:
                result.user_role = UserRoleEnum.MEMBER
        result.follower_num = follower_num
        result.file_num = total_file_num
        await self._decorate_department_metadata([result])
        await self._decorate_auto_tag_for_info(result)

        if space.state != KnowledgeState.PUBLISHED.value:
            current_tid = get_current_tenant_id()
            if space.tenant_id is None or current_tid in (None, space.tenant_id):
                rebuild_knowledge_celery.delay(
                    space_id,
                    new_model_id=space.model,
                    invoke_user_id=self.login_user.user_id,
                )
            else:
                logger.warning(
                    "skip knowledge space rebuild across tenant boundary: "
                    "space_id={} space_tenant_id={} current_tenant_id={} user_id={}",
                    space.id,
                    space.tenant_id,
                    current_tid,
                    self.login_user.user_id,
                )

        return result

    async def delete_space(self, space_id: int) -> None:
        space = await KnowledgeDao.aquery_by_id(space_id)
        if not space or space.type != KnowledgeTypeEnum.SPACE.value:
            raise SpaceNotFoundError()
        await self._require_permission_id("knowledge_space", space_id, "delete_space")
        child_resources = await self._list_space_child_resources(space_id)

        # Cleaned vectorData in
        await asyncio.to_thread(KnowledgeService.delete_knowledge_file_in_vector, space)

        # CleanedminioData
        await asyncio.to_thread(
            KnowledgeService.delete_knowledge_file_in_minio, space_id
        )

        await KnowledgeDao.async_delete_knowledge(knowledge_id=space_id)

        # Drop the private auto-tag library bound to this space (if any) so
        # we never leave orphan rows in knowledge_space_tag_library.
        try:
            await KnowledgeSpaceTagLibraryDao.adelete_private_for_knowledge(space_id)
        except Exception as e:
            _logger.warning(
                "Failed to delete private tag library for space %s: %s",
                space_id,
                e,
            )

        # F008: Delete all FGA tuples for this space and its child resources
        await self._cleanup_resource_tuples(
            child_resources + [("knowledge_space", space_id)]
        )

        # delete space channel memeber
        await SpaceChannelMemberDao.clean_space_member(space_id)

        # TC-040: prune channel ➜ knowledge-space sync bindings that target
        # this space so the channel UI and the Celery sync worker stop
        # referencing a tombstone. Import lazily to avoid pulling the channel
        # module into the knowledge module's import graph.
        from bisheng.channel.domain.models.channel_knowledge_sync import (
            ChannelKnowledgeSyncDao,
        )

        try:
            await ChannelKnowledgeSyncDao.adelete_by_space_id(str(space_id))
        except Exception as e:
            _logger.warning(
                "Failed to cleanup channel knowledge sync bindings for space %s: %s",
                space_id,
                e,
            )

        # Audit log and telemetry
        await KnowledgeAuditTelemetryService.audit_delete_knowledge_space(
            self.login_user, self.request, space
        )
        KnowledgeAuditTelemetryService.telemetry_delete_knowledge(self.login_user)
        return

    async def update_knowledge_space(
        self,
        space_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        icon: Optional[str] = None,
        auth_type: Optional[AuthTypeEnum] = None,
        is_released: bool = False,
        auto_tag_enabled: Optional[bool] = None,
        auto_tag_library_id: Optional[int] = None,
        auto_tag_custom_tags: Optional[List[str]] = None,
    ) -> Knowledge:
        """Modify an existing knowledge space."""
        space = await KnowledgeDao.aquery_by_id(space_id)
        if not space or space.type != KnowledgeTypeEnum.SPACE.value:
            raise SpaceNotFoundError()

        await self._require_permission_id("knowledge_space", space_id, "edit_space")

        old_auth_type = space.auth_type

        if name is not None:
            space.name = name
        if description is not None:
            space.description = description
        if icon is not None:
            space.icon = icon
        if auth_type is not None:
            space.auth_type = auth_type
        space.is_released = is_released

        auto_tag_touched = (
            auto_tag_enabled is not None
            or auto_tag_library_id is not None
            or auto_tag_custom_tags is not None
        )
        if auto_tag_touched:
            if not await self._is_auto_tag_feature_visible():
                # Tenant has the feature gated off — force-disable instead of
                # honouring the request payload.
                desired_enabled = False
                desired_library_id: Optional[int] = None
                desired_custom_tags: Optional[List[str]] = None
            else:
                desired_enabled = (
                    space.auto_tag_enabled
                    if auto_tag_enabled is None
                    else auto_tag_enabled
                )
                desired_library_id = auto_tag_library_id
                desired_custom_tags = auto_tag_custom_tags
                if (
                    desired_enabled
                    and desired_library_id is None
                    and desired_custom_tags is None
                ):
                    # Toggling enabled without choosing a source — fall back to
                    # the currently bound library so validate_bindable_library
                    # still runs (and rejects empty libraries).
                    desired_library_id = space.auto_tag_library_id

            resolved_enabled, resolved_library_id = await self._apply_auto_tag_binding(
                knowledge=space,
                auto_tag_enabled=desired_enabled,
                auto_tag_library_id=desired_library_id,
                auto_tag_custom_tags=desired_custom_tags,
                user_id=self.login_user.user_id,
                tenant_id=self.login_user.tenant_id,
            )
            space.auto_tag_enabled = resolved_enabled
            space.auto_tag_library_id = resolved_library_id

        space = await KnowledgeDao.async_update_space(space)
        new_auth_type = space.auth_type

        # When switching to PRIVATE, remove all non-creator members
        if (
            old_auth_type != AuthTypeEnum.PRIVATE
            and new_auth_type == AuthTypeEnum.PRIVATE
        ):
            child_resources = await self._list_space_child_resources(space_id)
            await self.__class__.clear_space_authorization_for_private(
                space=space,
                child_resources=child_resources,
            )
            await SpaceChannelMemberDao.async_delete_non_creator_members(space_id)
        elif (
            old_auth_type == AuthTypeEnum.APPROVAL
            and new_auth_type == AuthTypeEnum.PUBLIC
        ):
            pending_members = await SpaceChannelMemberDao.async_get_members_by_space(
                space_id,
                status=MembershipStatusEnum.PENDING,
            )
            for member in pending_members:
                member.status = MembershipStatusEnum.ACTIVE
                await SpaceChannelMemberDao.update(member)
                await self.__class__.sync_direct_space_user_permissions(
                    space_id,
                    member.user_id,
                    member.user_role,
                    is_active=True,
                )
            await SpaceChannelMemberDao.async_delete_rejected_members(space_id)

        return space

    # ──────────────────────────── Listings ────────────────────────────────────

    async def _format_member_spaces(
        self, members: List[SpaceChannelMember], order_by: str
    ) -> List[KnowledgeRead]:
        if not members:
            return []

        members_map = {int(one.business_id): one for one in members}
        res = await KnowledgeDao.async_get_spaces_by_ids(
            list(members_map.keys()), order_by
        )
        pinned_spaces = []
        normal_spaces = []
        for one in res:
            member_conf = members_map.get(one.id)
            if not member_conf:
                continue

            if member_conf.is_pinned:
                pinned_spaces.append(
                    KnowledgeSpaceInfoResp(
                        **one.model_dump(),
                        is_pinned=True,
                        user_role=member_conf.user_role,
                        subscription_status=SpaceSubscriptionStatusEnum.SUBSCRIBED,
                        is_followed=True,
                    )
                )
            else:
                normal_spaces.append(
                    KnowledgeSpaceInfoResp(
                        **one.model_dump(),
                        is_pinned=False,
                        user_role=member_conf.user_role,
                        subscription_status=SpaceSubscriptionStatusEnum.SUBSCRIBED,
                        is_followed=True,
                    )
                )
        return await self._decorate_department_metadata(pinned_spaces + normal_spaces)

    async def get_my_created_spaces(
        self, order_by: str = "update_time"
    ) -> List[KnowledgeRead]:
        members = await SpaceChannelMemberDao.async_get_user_created_members(
            self.login_user.user_id
        )
        if members:
            department_space_ids = set(
                (
                    await DepartmentKnowledgeSpaceDao.aget_department_ids_by_space_ids(
                        [int(member.business_id) for member in members]
                    )
                ).keys()
            )
            members = [
                member
                for member in members
                if int(member.business_id) not in department_space_ids
            ]
        return await self._format_member_spaces(members, order_by)

    async def get_my_managed_spaces(
        self, order_by: str = "name"
    ) -> List[KnowledgeRead]:
        members = await SpaceChannelMemberDao.async_get_user_managed_members(
            self.login_user.user_id
        )
        accessible_ids = await PermissionService.list_accessible_ids(
            user_id=self.login_user.user_id,
            relation="can_manage",
            object_type="knowledge_space",
            login_user=self.login_user,
        )
        space_ids = {int(member.business_id) for member in members}
        if accessible_ids is not None:
            space_ids |= {
                int(space_id) for space_id in accessible_ids if str(space_id).isdigit()
            }
        return await self._format_accessible_spaces(
            list(space_ids),
            order_by,
            memberships=members,
            required_permission_id="manage_space_relation",
        )

    async def get_my_followed_spaces(
        self, order_by: str = "update_time"
    ) -> List[KnowledgeRead]:
        """
        Return the spaces the current user follows (non-creator).
        Pinned spaces always appear first; within each pinned/non-pinned group
        the caller-specified order_by is applied.
        """
        # Fetch members ordered by is_pinned DESC so we know which are pinned
        members = await SpaceChannelMemberDao.async_get_user_followed_members(
            self.login_user.user_id
        )
        accessible_ids = await PermissionService.list_accessible_ids(
            user_id=self.login_user.user_id,
            relation="can_read",
            object_type="knowledge_space",
            login_user=self.login_user,
        )
        space_ids = {int(member.business_id) for member in members}
        if accessible_ids is not None:
            space_ids |= {
                int(space_id) for space_id in accessible_ids if str(space_id).isdigit()
            }
        return await self._format_accessible_spaces(
            list(space_ids),
            order_by,
            memberships=members,
            exclude_created=True,
            required_permission_id="view_space",
        )

    async def pin_space(self, space_id: int, is_pinned: bool = True) -> bool:
        return await SpaceChannelMemberDao.pin_space_id(
            space_id, self.login_user.user_id, is_pinned
        )

    async def get_knowledge_square(
        self, keyword: str = None, page: int = 1, page_size: int = 20
    ) -> dict:
        from bisheng.user.domain.services.user import UserService

        """
        Return PUBLIC/APPROVAL spaces for the Knowledge Square with pagination, sorted by:
        1. Not-joined first (easier to explore)
        2. Already-joined or pending last
        3. Within each group: sorted by update_time DESC
        Sorting and pagination are handled at the SQL level for efficiency.
        Returns: {"total": int, "page": int, "page_size": int, "data": List[KnowledgeSpaceInfoResp]}
        """
        # 1. SQL-level paginated query with multi-table JOIN
        rows, total = await asyncio.gather(
            KnowledgeDao.async_get_public_spaces_paginated(
                user_id=self.login_user.user_id,
                keyword=keyword,
                page=page,
                page_size=page_size,
            ),
            KnowledgeDao.async_count_public_spaces(keyword=keyword),
        )

        if not rows:
            return {"total": 0, "page": page, "page_size": page_size, "data": []}

        # 2. Collect current page space IDs and creator IDs for enrichment
        space_ids_int = [row[0].id for row in rows]
        creator_ids = list({row[0].user_id for row in rows if row[0].user_id})

        # 3. Batch fetch creator info and file counts for the current page only
        creator_users_task = (
            UserDao.aget_user_by_ids(creator_ids) if creator_ids else None
        )
        if self.login_user.is_admin():
            if creator_users_task:
                creator_users, success_file_map = await asyncio.gather(
                    creator_users_task,
                    KnowledgeFileDao.async_count_success_files_batch(space_ids_int),
                )
            else:
                creator_users = []
                success_file_map = (
                    await KnowledgeFileDao.async_count_success_files_batch(
                        space_ids_int
                    )
                )
            readable_space_ids = None
        else:
            if creator_users_task:
                (
                    creator_users,
                    success_file_map,
                    readable_space_ids,
                ) = await asyncio.gather(
                    creator_users_task,
                    KnowledgeFileDao.async_count_success_files_batch(space_ids_int),
                    PermissionService.list_accessible_ids(
                        user_id=self.login_user.user_id,
                        relation="can_read",
                        object_type="knowledge_space",
                        login_user=self.login_user,
                    ),
                )
            else:
                success_file_map, readable_space_ids = await asyncio.gather(
                    KnowledgeFileDao.async_count_success_files_batch(space_ids_int),
                    PermissionService.list_accessible_ids(
                        user_id=self.login_user.user_id,
                        relation="can_read",
                        object_type="knowledge_space",
                        login_user=self.login_user,
                    ),
                )
                creator_users = []
        user_map = {u.user_id: u for u in (creator_users or [])}
        resolved_subscription_status = {
            row[0].id: self._resolve_subscription_status_from_fields(row[1], row[2])
            for row in rows
        }
        readable_space_id_set = set()
        readable_space_with_view_permission = set()
        if readable_space_ids is not None:
            readable_space_id_set = {
                int(space_id)
                for space_id in readable_space_ids
                if str(space_id).isdigit()
            }
        readable_candidates = [
            space_id
            for space_id in readable_space_id_set
            if resolved_subscription_status.get(space_id)
            != SpaceSubscriptionStatusEnum.SUBSCRIBED
        ]
        if readable_candidates:
            effective_permission_ids = await asyncio.gather(
                *[
                    self._get_effective_permission_ids("knowledge_space", space_id)
                    for space_id in readable_candidates
                ]
            )
            readable_space_with_view_permission = {
                space_id
                for space_id, permission_ids in zip(
                    readable_candidates, effective_permission_ids
                )
                if "view_space" in permission_ids
            }

        # 4. Build response items
        result_list: list = []
        for row in rows:
            space = row[0]
            user_subscription_status = row[1]
            user_subscription_update_time = row[2]
            subscriber_count = row[3]

            creator = user_map.get(space.user_id)

            subscription_status = resolved_subscription_status.get(
                space.id
            ) or self._resolve_subscription_status_from_fields(
                user_subscription_status,
                user_subscription_update_time,
            )
            if space.id in readable_space_with_view_permission:
                subscription_status = SpaceSubscriptionStatusEnum.SUBSCRIBED

            result_list.append(
                KnowledgeSpaceInfoResp(
                    **space.model_dump(),
                    **{
                        "space": space,
                        "is_followed": subscription_status
                        == SpaceSubscriptionStatusEnum.SUBSCRIBED,
                        "is_pending": subscription_status
                        == SpaceSubscriptionStatusEnum.PENDING,
                        "subscription_status": subscription_status,
                        "user_name": creator.user_name
                        if creator
                        else str(space.user_id),
                        "avatar": await UserService.get_avatar_share_link(
                            creator.avatar
                        )
                        if creator
                        else None,
                        "file_num": success_file_map.get(space.id, 0),
                        "follower_num": subscriber_count,
                    },
                )
            )

        await self._decorate_department_metadata(result_list)
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "data": result_list,
        }

    # ──────────────────────────── Members ─────────────────────────────────────

    async def get_space_members(
        self, space_id: int, page: int, page_size: int, keyword: Optional[str] = None
    ) -> SpaceMemberPageResponse:
        from bisheng.user.domain.services.user import UserService

        """
        Paginate through the list of space members.
        - Verify if the current user has read permission
        - Support fuzzy search by username
        - Return user information and associated user groups
        - Sorting: Creators and administrators at the top, regular members sorted by user_id
        """
        await self._require_permission_id(
            "knowledge_space", space_id, "manage_space_relation"
        )

        search_user_ids = None
        if keyword:
            matched_users = await UserDao.afilter_users(user_ids=[], keyword=keyword)
            search_user_ids = [u.user_id for u in matched_users]
            if not search_user_ids:
                return SpaceMemberPageResponse(data=[], total=0)

        members = await SpaceChannelMemberDao.find_space_members_paginated(
            space_id=space_id, user_ids=search_user_ids, page=page, page_size=page_size
        )

        total = await SpaceChannelMemberDao.count_space_members_with_keyword(
            space_id=space_id, user_ids=search_user_ids
        )

        if not members:
            return SpaceMemberPageResponse(data=[], total=total)

        member_user_ids = [m.user_id for m in members]
        users = await UserDao.aget_user_by_ids(member_user_ids)
        user_map = {u.user_id: u for u in (users or [])}

        result_list = []
        for member in members:
            user = user_map.get(member.user_id)
            user_name = user.user_name if user else f"User {member.user_id}"

            # Query user groups the user belongs to
            user_groups = await self.login_user.get_user_groups(member.user_id)

            result_list.append(
                SpaceMemberResponse(
                    user_id=member.user_id,
                    user_name=user_name,
                    user_avatar=await UserService.get_avatar_share_link(user.avatar)
                    if user
                    else None,
                    user_role=member.user_role.value,
                    user_groups=user_groups,
                )
            )

        return SpaceMemberPageResponse(data=result_list, total=total)

    async def update_member_role(self, req: UpdateSpaceMemberRoleRequest) -> bool:
        """
        Set member role (admin/regular member).
        Permissions:
        - Creators can set anyone as an admin or member
        - Admins cannot promote others to admin, nor can they modify the roles of other admins or creators
        - Modifying the creator's role is not allowed
        """
        # 1. Verify can_manage permission via ReBAC
        await self._require_permission_id(
            "knowledge_space", req.space_id, "manage_space_relation"
        )

        # Get current user's SCM role for business logic decisions
        current_role = await SpaceChannelMemberDao.async_get_active_member_role(
            req.space_id, self.login_user.user_id
        )

        # 2. Query target member
        target_membership = await SpaceChannelMemberDao.async_find_member(
            space_id=req.space_id, user_id=req.user_id
        )
        if not target_membership or not target_membership.is_active:
            raise ValueError("The target user is not a member of this space")

        # 3. Modifying the creator's role is not allowed
        if target_membership.user_role == UserRoleEnum.CREATOR:
            raise ValueError("Modifying the creator's role is not allowed")

        # 4. Admin permission limits
        if current_role == UserRoleEnum.ADMIN:
            # Admins cannot set others as admins
            if req.role == UserRoleEnum.ADMIN.value:
                raise ValueError(
                    "Admins do not have permission to set others as admins"
                )
            # Admins cannot modify the roles of other admins
            if target_membership.user_role == UserRoleEnum.ADMIN:
                raise ValueError(
                    "Admins do not have permission to modify the roles of other admins"
                )

        # 5. Check maximum limit when setting as an admin
        if req.role == UserRoleEnum.ADMIN.value:
            current_admins = await SpaceChannelMemberDao.async_get_members_by_space(
                space_id=req.space_id, user_roles=[UserRoleEnum.ADMIN]
            )
            if len(current_admins) >= 5:
                raise ValueError("Maximum number of administrators reached")

        should_notify_admin_assignment = (
            target_membership.user_role == UserRoleEnum.MEMBER
            and req.role == UserRoleEnum.ADMIN.value
        )

        # 6. Update role in SpaceChannelMember
        target_membership.user_role = UserRoleEnum(req.role)
        await SpaceChannelMemberDao.update(target_membership)

        if should_notify_admin_assignment:
            await self._send_admin_assignment_notification(
                space_id=req.space_id,
                target_user_id=target_membership.user_id,
            )

        return True

    async def remove_member(self, req: RemoveSpaceMemberRequest) -> bool:
        """
        Remove a member (hard delete).
        Permissions:
        - Creators can remove anyone (except themselves)
        - Admins can remove regular members
        - Admins cannot remove other admins or creators
        """
        # 1. Verify can_manage permission via ReBAC
        await self._require_permission_id(
            "knowledge_space", req.space_id, "manage_space_relation"
        )

        # Get current user's SCM role for business logic decisions
        current_role = await SpaceChannelMemberDao.async_get_active_member_role(
            req.space_id, self.login_user.user_id
        )

        # 2. Cannot remove yourself
        if req.user_id == self.login_user.user_id:
            raise ValueError("Cannot remove yourself")

        # 3. Query target member
        target_membership = await SpaceChannelMemberDao.async_find_member(
            space_id=req.space_id, user_id=req.user_id
        )
        if not target_membership or not target_membership.is_active:
            raise ValueError("The target user is not a member of this space")

        # 4. Removing the creator is not allowed
        if target_membership.user_role == UserRoleEnum.CREATOR:
            raise ValueError("Removing the creator is not allowed")

        # 5. Admins cannot remove other admins
        if current_role == UserRoleEnum.ADMIN:
            if target_membership.user_role == UserRoleEnum.ADMIN:
                raise ValueError("Admins do not have permission to remove other admins")

        await self._revoke_direct_space_user_permissions(req.space_id, req.user_id)

        # 6. Hard delete: remove from database
        await SpaceChannelMemberDao.delete_space_member(
            space_id=req.space_id, user_id=req.user_id
        )
        return True

    async def _send_admin_assignment_notification(
        self,
        space_id: int,
        target_user_id: int,
    ) -> None:
        """Notify a space member after being promoted from member to admin."""
        space = await KnowledgeDao.aquery_by_id(space_id)
        if not space or space.type != KnowledgeTypeEnum.SPACE.value:
            raise SpaceNotFoundError()

        user = await UserDao.aget_user(target_user_id)
        target_user_name = user.user_name if user else f"User {target_user_id}"

        content = [
            {
                "type": "user",
                "content": f"@{target_user_name}",
                "metadata": {"user_id": target_user_id},
            },
            {
                "type": "system_text",
                "content": SPACE_ADMIN_ASSIGNMENT_MESSAGE,
            },
            {
                "type": "business_url",
                "content": f"--{space.name}",
                "metadata": {
                    "business_type": "knowledge_space_id",
                    "data": {"knowledge_space_id": str(space.id)},
                },
            },
        ]

        if not self.message_service:
            return

        await self.message_service.send_generic_notify(
            sender=self.login_user.user_id,
            receiver_user_ids=[target_user_id],
            content_item_list=content,
        )

    async def _enrich_with_version_info(
        self, items: List[KnowledgeFile]
    ) -> List[KnowledgeFile]:
        """Attach version_no / is_multi_version / has_similar to file items in-place.

        Requires self.version_repo to be set.  Folders are skipped (file_type==0).
        The method mutates each KnowledgeFile object by setting dynamic attributes;
        these are picked up by _handle_file_folder_extra_info when it calls
        model_dump() because it updates the dict with the extra fields.
        Returns the same list for convenience.
        """
        if not self.version_repo:
            return items

        file_items = [it for it in items if it.file_type != FileType.DIR.value]
        if not file_items:
            return items

        file_id_list = [f.id for f in file_items]
        # Fetch primary version rows for all visible file-page items in one query.
        primary_versions = await self.version_repo.find_primary_versions_by_file_ids(
            file_id_list
        )
        # Map: knowledge_file_id -> KnowledgeDocumentVersion
        ver_by_file: Dict[int, KnowledgeDocumentVersion] = {
            v.knowledge_file_id: v for v in primary_versions
        }

        # Count all versions per document to determine is_multi_version.
        # Batch by unique document_ids to avoid N queries.
        # Uses the module-level get_async_db_session so that tests can patch it.
        from sqlalchemy import func as _func

        doc_ids = list({v.document_id for v in primary_versions})
        doc_version_counts: Dict[int, int] = {}
        if doc_ids:
            stmt = (
                select(
                    KnowledgeDocumentVersion.document_id,
                    _func.count(KnowledgeDocumentVersion.id),
                )
                .where(KnowledgeDocumentVersion.document_id.in_(doc_ids))
                .group_by(KnowledgeDocumentVersion.document_id)
            )
            async with get_async_db_session() as session:
                rows = (await session.execute(stmt)).all()
            doc_version_counts = {row[0]: row[1] for row in rows}

        for item in file_items:
            ver = ver_by_file.get(item.id)
            if ver is not None:
                count = doc_version_counts.get(ver.document_id, 1)
                item._version_no = ver.version_no
                item._is_multi_version = count > 1
            else:
                item._version_no = None
                item._is_multi_version = False
            item._has_similar = item.similar_status == 1

        return items

    async def _handle_file_folder_extra_info(
        self, res: List[KnowledgeFile]
    ) -> List[Dict]:
        folder_ids = []
        file_ids = []
        for one in res:
            if one.file_type == FileType.DIR:
                folder_ids.append(one.id)
            else:
                file_ids.append(one.id)

        # folder need find all success file num and all file num
        folder_counts = {}
        if folder_ids:
            from sqlmodel import select, col
            from sqlalchemy import func, or_
            from bisheng.core.database import get_async_db_session

            async def count_folder(folder: KnowledgeFile):
                prefix = f"{folder.file_level_path or ''}/{folder.id}"
                stmt = (
                    select(KnowledgeFile.status, func.count(KnowledgeFile.id))
                    .where(
                        KnowledgeFile.knowledge_id == folder.knowledge_id,
                        KnowledgeFile.file_type == 1,
                        or_(
                            col(KnowledgeFile.file_level_path) == prefix,
                            col(KnowledgeFile.file_level_path).like(f"{prefix}/%"),
                        ),
                    )
                    .group_by(KnowledgeFile.status)
                )

                async with get_async_db_session() as session:
                    rows = (await session.exec(stmt)).all()
                    total = sum(r[1] for r in rows)
                    success = sum(
                        r[1] for r in rows if r[0] == KnowledgeFileStatus.SUCCESS.value
                    )
                    folder_counts[folder.id] = {
                        "file_num": total,
                        "success_file_num": success,
                    }

            folders = [f for f in res if f.file_type == FileType.DIR]
            await asyncio.gather(*(count_folder(f) for f in folders))

        # file need find all tags
        file_tags = {}
        if file_ids:
            tag_dict = await asyncio.to_thread(
                TagDao.get_tags_by_resource_batch,
                [ResourceTypeEnum.SPACE_FILE],
                [str(fid) for fid in file_ids],
            )
            for fid_str, tags in tag_dict.items():
                file_tags[int(fid_str)] = [{"id": t.id, "name": t.name} for t in tags]

        result = []
        for one in res:
            item = one.model_dump()
            if one.file_type == FileType.DIR:
                counts = folder_counts.get(
                    one.id, {"file_num": 0, "success_file_num": 0}
                )
                item.update(counts)
            else:
                item["thumbnails"] = self.get_logo_share_link(one.thumbnails)
                item["tags"] = file_tags.get(one.id, [])
                # Version enrichment fields set by _enrich_with_version_info (if version_repo is set).
                item["version_no"] = getattr(one, "_version_no", None)
                item["is_multi_version"] = getattr(one, "_is_multi_version", False)
                item["has_similar"] = getattr(
                    one, "_has_similar", (one.similar_status == 1)
                )
            result.append(item)

        return result

    async def _filter_visible_child_items(
        self,
        items: List[KnowledgeFile],
        *,
        space_id: int,
        context: Optional[dict] = None,
    ) -> List[KnowledgeFile]:
        semaphore = asyncio.Semaphore(_CHILD_PERMISSION_CHECK_CONCURRENCY)
        permission_context = context or await self._build_child_permission_context(
            space_id
        )

        async def can_view(item: KnowledgeFile) -> bool:
            async with semaphore:
                permission_id = (
                    "view_folder"
                    if item.file_type == FileType.DIR.value
                    else "view_file"
                )
                effective_permissions = (
                    await self._get_child_item_effective_permission_ids(
                        item,
                        space_id=space_id,
                        context=permission_context,
                    )
                )
                return permission_id in effective_permissions

        visibility = await asyncio.gather(*(can_view(item) for item in items))
        return [item for item, allowed in zip(items, visibility) if allowed]

    @staticmethod
    def _paginate_items(
        items: List[KnowledgeFile], page: int, page_size: int
    ) -> List[KnowledgeFile]:
        if not page or not page_size:
            return items
        start = (page - 1) * page_size
        return items[start : start + page_size]

    async def _scan_visible_child_items(
        self,
        *,
        space_id: int,
        parent_id: Optional[int],
        file_ids: Optional[List[int]],
        order_field: str,
        order_sort: str,
        file_status: Optional[List[int]],
        file_type: Optional[int],
        page: int,
        page_size: int,
        exclude_file_ids: Optional[List[int]] = None,
    ) -> tuple[int, List[KnowledgeFile]]:
        target_start = max(page - 1, 0) * page_size if page_size else 0
        target_end = target_start + page_size if page_size else None

        scan_page = 1
        visible_total = 0
        visible_page_items: List[KnowledgeFile] = []
        permission_context = await self._build_child_permission_context(space_id)

        while True:
            batch_items = await SpaceFileDao.async_list_children(
                space_id,
                parent_id,
                file_ids=file_ids,
                order_field=order_field,
                order_sort=order_sort,
                file_status=file_status,
                page=scan_page,
                page_size=_CHILD_PERMISSION_SCAN_BATCH_SIZE,
                file_type=file_type,
                exclude_file_ids=exclude_file_ids,
            )
            if not batch_items:
                break

            visible_batch = await self._filter_visible_child_items(
                batch_items,
                space_id=space_id,
                context=permission_context,
            )
            for item in visible_batch:
                if target_end is None or (target_start <= visible_total < target_end):
                    visible_page_items.append(item)
                visible_total += 1

            if len(batch_items) < _CHILD_PERMISSION_SCAN_BATCH_SIZE:
                break
            scan_page += 1

        return visible_total, visible_page_items

    async def list_space_children(
        self,
        space_id: int,
        parent_id: Optional[int] = None,
        file_ids: Optional[List[int]] = None,
        order_field: str = "file_type",
        order_sort: str = "asc",
        file_status: List[int] = None,
        page: int = 1,
        page_size: int = 20,
        file_type: Optional[int] = None,
    ) -> dict:
        """
        Return direct children (folders first, then files) under a parent folder.
        When parent_id is None, returns root-level items of the space.
        Returns: {"total": int, "page": int, "page_size": int, "data": List[KnowledgeFile]}
        """
        await self._require_read_permission(space_id)
        if parent_id:
            await self._require_folder_relation(space_id, parent_id, "can_read")
            await self._require_permission_id(
                "folder", parent_id, "view_folder", space_id=space_id
            )
        else:
            await self._require_permission_id("knowledge_space", space_id, "view_space")

        # Exclude non-primary version files so only the current primary revision is visible.
        exclude_file_ids: Optional[List[int]] = None
        if self.version_repo is not None:
            exclude_file_ids = (
                await self.version_repo.find_non_primary_file_ids() or None
            )

        total, visible_page_items = await self._scan_visible_child_items(
            space_id=space_id,
            parent_id=parent_id,
            file_ids=file_ids,
            order_field=order_field,
            order_sort=order_sort,
            file_status=file_status,
            file_type=file_type,
            page=page,
            page_size=page_size,
            exclude_file_ids=exclude_file_ids,
        )

        # Enrich page items with version fields (version_no, is_multi_version, has_similar).
        await self._enrich_with_version_info(visible_page_items)

        data = await self._handle_file_folder_extra_info(visible_page_items)
        return {"total": total, "page": page, "page_size": page_size, "data": data}

    async def search_space_children(
        self,
        space_id: int,
        parent_id: Optional[int] = None,
        tag_ids: List[int] = None,
        keyword: str = None,
        page: int = 1,
        page_size: int = 20,
        file_status: List[int] = None,
        order_field: str = "file_type",
        order_sort: str = "asc",
    ) -> Dict:
        space = await self._require_read_permission(space_id)
        if not parent_id:
            await self._require_permission_id("knowledge_space", space_id, "view_space")

        file_level_path = None
        filter_files = []

        if parent_id:
            parent_folder = await self._require_folder_relation(
                space_id, parent_id, "can_read"
            )
            await self._require_permission_id(
                "folder", parent_id, "view_folder", space_id=space_id
            )
            file_level_path = f"{parent_folder.file_level_path}/{parent_folder.id}"
            children_ids = await SpaceFileDao.get_children_by_prefix(
                space_id, file_level_path
            )
            if not children_ids:
                return {"total": 0, "page": page, "page_size": page_size, "data": []}
            filter_files = [one.id for one in children_ids]

        if tag_ids:
            resources = await TagDao.aget_resources_by_tags(
                tag_ids, ResourceTypeEnum.SPACE_FILE
            )
            if not resources:
                return {"total": 0, "page": page, "page_size": page_size, "data": []}
            if filter_files:
                filter_files = list(
                    set(filter_files) & set([int(one.resource_id) for one in resources])
                )
            else:
                filter_files = [int(one.resource_id) for one in resources]
            if not filter_files:
                return {"total": 0, "page": page, "page_size": page_size, "data": []}

        extra_file_ids = []
        if keyword:
            query = {"match_phrase": {"text": keyword}}
            if filter_files:
                query = {
                    "bool": {
                        "must": [
                            query,
                            {"terms": {"metadata.document_id": filter_files}},
                        ]
                    }
                }
            es_vector = await KnowledgeRag.init_knowledge_es_vectorstore(
                knowledge=space
            )
            es_result = await es_vector.client.search(
                index=space.index_name,
                body={
                    "query": query,
                    "aggs": {
                        "document_ids": {
                            "terms": {
                                "field": "metadata.document_id",
                            }
                        }
                    },
                    "size": 0,
                },
            )
            aggregations = es_result.get("aggregations")
            if aggregations:
                for one in aggregations.get("document_ids", {}).get("buckets", []):
                    extra_file_ids.append(one["key"])
            if filter_files:
                extra_file_ids = list(set(filter_files) & set(extra_file_ids))

        # Exclude non-primary version files so only the current primary revision is visible.
        exclude_file_ids: Optional[List[int]] = None
        if self.version_repo is not None:
            exclude_file_ids = (
                await self.version_repo.find_non_primary_file_ids() or None
            )

        res = await KnowledgeFileDao.aget_file_by_filters(
            space_id,
            file_name=keyword,
            file_ids=filter_files,
            extra_file_ids=extra_file_ids,
            status=file_status,
            file_level_path=file_level_path,
            order_by="file_type",
            order_field=order_field,
            order_sort=order_sort,
            exclude_file_ids=exclude_file_ids,
        )
        visible_items = await self._filter_visible_child_items(res, space_id=space_id)
        total = len(visible_items)
        page_items = self._paginate_items(visible_items, page, page_size)

        # Enrich page items with version fields (version_no, is_multi_version, has_similar).
        await self._enrich_with_version_info(page_items)

        data = await self._handle_file_folder_extra_info(page_items)
        return {"total": total, "page": page, "page_size": page_size, "data": data}

    # ──────────────────────────── Folders ─────────────────────────────────────

    async def add_folder(
        self,
        knowledge_id: int,
        folder_name: str,
        parent_id: Optional[int] = None,
    ) -> KnowledgeFile:
        if parent_id:
            await self._require_permission_id(
                "folder", parent_id, "create_folder", space_id=knowledge_id
            )
        else:
            await self._require_permission_id(
                "knowledge_space", knowledge_id, "create_folder"
            )
        level = 0
        file_level_path = ""
        parent_type = "knowledge_space"
        parent_resource_id = knowledge_id

        if parent_id:
            parent_folder = await self._get_folder_for_action(knowledge_id, parent_id)
            level = parent_folder.level + 1
            if level > 10:
                raise SpaceFolderDepthError()
            file_level_path = f"{parent_folder.file_level_path}/{parent_id}"
            parent_type = "folder"
            parent_resource_id = parent_id

        if (
            await SpaceFileDao.count_folder_by_name(
                knowledge_id, folder_name, file_level_path
            )
            > 0
        ):
            raise SpaceFolderDuplicateError()

        added_folder = await KnowledgeFileDao.aadd_file(
            KnowledgeFile(
                knowledge_id=knowledge_id,
                user_id=self.login_user.user_id,
                user_name=self.login_user.user_name,
                updater_id=self.login_user.user_id,
                updater_name=self.login_user.user_name,
                file_name=folder_name,
                file_type=0,
                level=level,
                file_level_path=file_level_path,
                status=KnowledgeFileStatus.SUCCESS.value,
            )
        )
        try:
            await self._initialize_child_resource_permissions(
                "folder",
                added_folder.id,
                parent_type,
                parent_resource_id,
            )
        except Exception:
            await self._cleanup_resource_tuples([("folder", added_folder.id)])
            await KnowledgeFileDao.adelete_batch([added_folder.id])
            raise
        await KnowledgeDao.async_update_knowledge_update_time_by_id(knowledge_id)
        return added_folder

    async def rename_folder(self, folder_id: int, new_name: str) -> KnowledgeFile:
        folder = await KnowledgeFileDao.query_by_id(folder_id)
        if not folder or folder.file_type != 0:
            raise SpaceFolderNotFoundError()
        folder = self._ensure_space_folder(folder, folder.knowledge_id)
        await self._require_permission_id(
            "folder", folder_id, "rename_folder", space_id=folder.knowledge_id
        )

        if (
            await SpaceFileDao.count_folder_by_name(
                folder.knowledge_id,
                new_name,
                folder.file_level_path,
                exclude_id=folder_id,
            )
            > 0
        ):
            raise SpaceFolderDuplicateError()

        folder.file_name = new_name
        updated_folder = await KnowledgeFileDao.async_update(folder)
        await KnowledgeDao.async_update_knowledge_update_time_by_id(folder.knowledge_id)
        return updated_folder

    async def delete_folder(self, space_id: int, folder_id: int):
        from bisheng.worker.knowledge.file_worker import delete_knowledge_file_celery

        folder = await self._get_folder_for_action(space_id, folder_id)
        await self._require_permission_id(
            "folder", folder_id, "delete_folder", space_id=space_id
        )
        space = await KnowledgeDao.aquery_by_id(space_id)
        if not space:
            raise SpaceNotFoundError()
        self._ensure_space_async_task_tenant_consistency(space, "delete_folder")

        prefix = f"{folder.file_level_path}/{folder.id}"
        children = await SpaceFileDao.get_children_by_prefix(
            folder.knowledge_id, prefix
        )
        floder_ids = [folder_id]
        file_ids = []
        resource_tuples_to_cleanup = [("folder", folder_id)]
        for child in children:
            if child.file_type == FileType.DIR.value:
                await self._require_permission_id(
                    "folder", child.id, "delete_folder", space_id=space_id
                )
                floder_ids.append(child.id)
                resource_tuples_to_cleanup.append(("folder", child.id))
            else:
                await self._require_permission_id(
                    "knowledge_file", child.id, "delete_file", space_id=space_id
                )
                file_ids.append(child.id)
                resource_tuples_to_cleanup.append(("knowledge_file", child.id))

        if file_ids:
            delete_knowledge_file_celery.delay(
                file_ids=file_ids, knowledge_id=folder.knowledge_id, clear_minio=True
            )

        await self.update_folder_update_time(folder.file_level_path)
        await self._cleanup_resource_tuples(resource_tuples_to_cleanup)

        await KnowledgeFileDao.adelete_batch(file_ids + floder_ids)

        # Prune channel ➜ knowledge-folder sync bindings that target the deleted
        # folders so the Celery sync worker stops referencing a tombstone.
        from bisheng.channel.domain.models.channel_knowledge_sync import (
            ChannelKnowledgeSyncDao,
        )

        try:
            await ChannelKnowledgeSyncDao.adelete_by_folder_ids(floder_ids)
        except Exception as e:
            _logger.warning(
                "Failed to cleanup channel knowledge sync bindings for folders %s: %s",
                floder_ids,
                e,
            )

        await KnowledgeDao.async_update_knowledge_update_time_by_id(folder.knowledge_id)

    async def get_folder_file_parent(self, space_id: int, file_id: int) -> List[Dict]:
        file_record = await self._require_file_or_folder_relation(
            space_id, file_id, "can_read"
        )
        await self._require_permission_id(
            "folder"
            if file_record.file_type == FileType.DIR.value
            else "knowledge_file",
            file_record.id,
            "view_folder"
            if file_record.file_type == FileType.DIR.value
            else "view_file",
            space_id=space_id,
        )
        if file_record.level == 0:
            return []
        file_level_path_list = file_record.file_level_path.split("/")
        file_ids = [int(one) for one in file_level_path_list if one]
        file_list = await KnowledgeFileDao.aget_file_by_ids(file_ids)
        file_list = {file.id: file for file in file_list}
        res = []
        for one in file_ids:
            res.append(
                {
                    "id": one,
                    "file_name": file_list.get(one).file_name
                    if file_list.get(one)
                    else one,
                }
            )
        return res

    # ──────────────────────────── Files ───────────────────────────────────────

    async def add_file(
        self,
        knowledge_id: int,
        file_path: List[str],
        parent_id: Optional[int] = None,
        file_source: FileSource = None,
        skip_approval: bool = False,
    ) -> List[KnowledgeSpaceFileResponse]:
        if file_source is None:
            file_source = FileSource.SPACE_UPLOAD
        if parent_id:
            await self._require_permission_id(
                "folder", parent_id, "upload_file", space_id=knowledge_id
            )
        else:
            await self._require_permission_id(
                "knowledge_space", knowledge_id, "upload_file"
            )

        db_knowledge = await KnowledgeDao.aquery_by_id(knowledge_id)
        if not db_knowledge:
            raise SpaceFolderNotFoundError()
        self._ensure_space_async_task_tenant_consistency(db_knowledge, "upload_file")

        level = 0
        file_level_path = ""
        parent_type = "knowledge_space"
        parent_resource_id = knowledge_id

        if parent_id:
            parent_folder = await self._get_folder_for_action(knowledge_id, parent_id)
            level = parent_folder.level + 1
            file_level_path = f"{parent_folder.file_level_path}/{parent_id}"
            parent_type = "folder"
            parent_resource_id = parent_id

        # User-role cap (multi-role max GB; admin returns None = unlimited).
        role_user_limit_bytes = (
            await QuotaService.get_knowledge_space_upload_limit_bytes(self.login_user)
        )
        logger.debug(
            f"space_file_upload_limit_bytes={role_user_limit_bytes} "
            f"user_id={self.login_user.user_id}"
        )
        current_user_total = int(
            await SpaceFileDao.get_user_total_file_size(self.login_user.user_id)
        )

        # Tenant-level cap: applies to the *target tenant* of the destination
        # knowledge space, regardless of the writer's role/admin status.
        # Raises 19403 here if the tenant chain is already exhausted.
        target_tid = db_knowledge.tenant_id
        tenant_remaining_bytes = await QuotaService.get_tenant_storage_remaining_bytes(
            target_tid
        )
        if tenant_remaining_bytes is not None:
            tenant_used_at_start_bytes = (
                await QuotaService.get_tenant_storage_used_bytes(target_tid)
            )
            tenant_cap_bytes = tenant_used_at_start_bytes + tenant_remaining_bytes
            current_tenant_total_bytes = tenant_used_at_start_bytes
        else:
            tenant_cap_bytes = None
            current_tenant_total_bytes = 0

        folder_id2name = {}

        async def get_folder_name(tmp_file_level_path: str) -> str:
            if not tmp_file_level_path:
                return ""
            folder_ids = [int(fid) for fid in tmp_file_level_path.split("/") if fid]
            not_exists_ids = [one for one in folder_ids if one not in folder_id2name]
            if not_exists_ids:
                folder_list = await KnowledgeFileDao.aget_file_by_ids(folder_ids)
                for folder in folder_list:
                    folder_id2name[folder.id] = folder.file_name
            tmp = ""
            for one in folder_ids:
                folder_name = folder_id2name.get(one, one)
                tmp += f"/{folder_name}"
            return tmp

        file_split_rule = FileProcessBase(knowledge_id=knowledge_id)
        process_files = []
        failed_files = []
        preview_cache_keys = []
        created_files = []

        async def cleanup_created_files() -> None:
            created_file_ids = [
                created_file.id
                for created_file in created_files
                if getattr(created_file, "id", None)
            ]
            if not created_file_ids:
                return
            try:
                await self._cleanup_resource_tuples(
                    [
                        ("knowledge_file", created_file_id)
                        for created_file_id in created_file_ids
                    ]
                )
            finally:
                await KnowledgeFileDao.adelete_batch(created_file_ids)

        try:
            for one in file_path:
                db_file = KnowledgeService.process_one_file(
                    self.login_user,
                    knowledge=db_knowledge,
                    file_info=KnowledgeFileOne(file_path=one, excel_rule=ExcelRule()),
                    split_rule=file_split_rule.model_dump(),
                    file_kwargs={
                        "level": level,
                        "file_level_path": file_level_path,
                        "file_source": file_source.value,
                    },
                )
                if db_file.status != KnowledgeFileStatus.FAILED.value:
                    if getattr(db_file, "id", None):
                        created_files.append(db_file)
                        # Plan 2 Task 9: also create a logical document + V1 (primary) for the uploaded file.
                        # This is independent of the version-management switch (D3): the rows always
                        # exist so the file list can be document-driven even when the switch is off.
                        async with get_async_db_session() as v_session:
                            v_doc = KnowledgeDocument(
                                knowledge_id=db_file.knowledge_id,
                                file_level_path=db_file.file_level_path,
                                level=db_file.level or 0,
                            )
                            v_session.add(v_doc)
                            await v_session.flush()
                            v_version = KnowledgeDocumentVersion(
                                document_id=v_doc.id,
                                knowledge_file_id=db_file.id,
                                version_no=1,
                                is_primary=True,
                            )
                            v_session.add(v_version)
                            await v_session.flush()
                            v_doc.primary_version_id = v_version.id
                            v_session.add(v_doc)
                            await v_session.commit()
                    # Get a preview cache of this filekey
                    cache_key = self.get_preview_cache_key(knowledge_id, one)
                    preview_cache_keys.append(cache_key)
                    process_files.append(db_file)
                    current_user_total += db_file.file_size
                    current_tenant_total_bytes += db_file.file_size
                else:
                    failed_file = KnowledgeSpaceFileResponse(**db_file.model_dump())
                    failed_file.old_file_level_path = await get_folder_name(
                        db_file.file_level_path
                    )
                    failed_file.file_level_path = file_level_path
                    failed_files.append(failed_file)
                # Tenant-level cap: applies to admins as well; the write triggered by
                # this upload would push the target tenant over its storage_gb cap.
                if (
                    tenant_cap_bytes is not None
                    and current_tenant_total_bytes > tenant_cap_bytes
                ):
                    blocker = (
                        target_tid,
                        "tenant_limit",
                        round(current_tenant_total_bytes / (1024**3), 2),
                        round(tenant_cap_bytes / (1024**3), 2),
                        "",
                    )
                    raise QuotaService._make_storage_quota_error(blocker, "storage_gb")
                # User-role cap (preserved). Admins skip this branch because
                # role_user_limit_bytes is None for them.
                if (
                    role_user_limit_bytes is not None
                    and current_user_total > role_user_limit_bytes
                ):
                    raise SpaceFileSizeLimitError()
            for created_file in created_files:
                await self._initialize_child_resource_permissions(
                    "knowledge_file",
                    created_file.id,
                    parent_type,
                    parent_resource_id,
                )
        except Exception:
            try:
                await cleanup_created_files()
            except Exception as cleanup_exc:
                logger.warning(
                    f"Failed to cleanup files after knowledge space upload error: {cleanup_exc}"
                )
            raise
        for index, one in enumerate(process_files):
            file_worker.parse_knowledge_file_celery.delay(
                one.id, preview_cache_keys[index]
            )
        await self.update_folder_update_time(file_level_path)
        await KnowledgeDao.async_update_knowledge_update_time_by_id(knowledge_id)
        return failed_files + process_files

    async def rename_file(self, file_id: int, new_name: str) -> KnowledgeFile:
        from bisheng.worker.knowledge.rebuild_knowledge_worker import (
            rebuild_knowledge_file_chunk,
        )

        file_record = await self._get_file_for_action(file_id)
        await self._require_permission_id(
            "knowledge_file", file_id, "rename_file", space_id=file_record.knowledge_id
        )
        space = await KnowledgeDao.aquery_by_id(file_record.knowledge_id)
        if not space:
            raise SpaceNotFoundError()
        self._ensure_space_async_task_tenant_consistency(space, "rename_file")

        old_suffix = (
            file_record.file_name.rsplit(".", 1)[-1]
            if "." in file_record.file_name
            else ""
        )
        new_suffix = new_name.rsplit(".", 1)[-1] if "." in new_name else ""
        if old_suffix != new_suffix:
            raise SpaceFileExtensionError()

        if (
            await SpaceFileDao.count_file_by_name(
                file_record.knowledge_id, new_name, exclude_id=file_id
            )
            > 0
        ):
            raise SpaceFileNameDuplicateError()

        file_record.file_name = new_name
        updated_file = await KnowledgeFileDao.async_update(file_record)

        if updated_file.status == KnowledgeFileStatus.SUCCESS.value:
            rebuild_knowledge_file_chunk.delay(file_id=file_id)
        await self.update_folder_update_time(file_record.file_level_path)
        await KnowledgeDao.async_update_knowledge_update_time_by_id(
            file_record.knowledge_id
        )
        return updated_file

    async def update_file_encoding(
        self,
        file_id: int,
        encoding: str,
    ) -> KnowledgeFile:
        """Update a file's file_encoding (shougang feature). Owner/admin only."""
        file_record = await self._get_file_for_action(file_id)
        # Reuse 'rename_file' permission action — that action is owner/admin-only,
        # matching the required privilege level for editing encoding.
        await self._require_permission_id(
            "knowledge_file",
            file_id,
            "rename_file",
            space_id=file_record.knowledge_id,
        )

        cleaned = encoding.strip()
        if not cleaned:
            raise ValueError("encoding cannot be empty after strip")

        file_record.file_encoding = cleaned
        file_record.updater_id = self.login_user.user_id
        file_record.updater_name = self.login_user.user_name
        return await KnowledgeFileDao.async_update(file_record)

    async def delete_file(self, file_id: int):
        from bisheng.worker.knowledge.file_worker import delete_knowledge_file_celery

        file_record = await self._get_file_for_action(file_id)
        await self._require_permission_id(
            "knowledge_file", file_id, "delete_file", space_id=file_record.knowledge_id
        )
        space = await KnowledgeDao.aquery_by_id(file_record.knowledge_id)
        if not space:
            raise SpaceNotFoundError()
        self._ensure_space_async_task_tenant_consistency(space, "delete_file")

        await KnowledgeFileDao.adelete_batch([file_id])
        delete_knowledge_file_celery.delay(
            file_ids=[file_id], knowledge_id=file_record.knowledge_id, clear_minio=True
        )
        await self._cleanup_resource_tuples([("knowledge_file", file_id)])
        await self.update_folder_update_time(file_record.file_level_path)
        await KnowledgeDao.async_update_knowledge_update_time_by_id(
            file_record.knowledge_id
        )

    async def get_file_preview(self, file_id: int) -> dict:
        file_record = await self._require_file_relation(file_id, "can_read")
        await self._require_permission_id(
            "knowledge_file", file_id, "view_file", space_id=file_record.knowledge_id
        )

        original_url, preview_url = KnowledgeService.get_file_share_url(file_id)

        return {
            "original_url": original_url,
            "preview_url": preview_url,
        }

    async def get_file_download(
        self, file_id: int, *, space_id: Optional[int] = None
    ) -> dict:
        file_record = await self._get_file_for_action(file_id, space_id=space_id)
        await self._require_permission_id(
            "knowledge_file",
            file_id,
            "download_file",
            space_id=file_record.knowledge_id,
        )

        original_url, preview_url = KnowledgeService.get_file_share_url(file_id)

        return {
            "original_url": original_url,
            "preview_url": preview_url,
        }

    # ──────────────────────────── Tags ───────────────────────────────────
    async def get_space_tags(self, space_id: int) -> List[Tag]:
        await self._require_read_permission(space_id)
        await self._require_permission_id("knowledge_space", space_id, "view_space")
        tags = await TagDao.get_tags_by_business(
            business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE, business_id=str(space_id)
        )
        return tags

    async def add_space_tag(self, space_id: int, tag_name: str) -> Tag:
        await self._require_permission_id("knowledge_space", space_id, "edit_space")

        existing_tags = await TagDao.get_tags_by_business(
            business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE,
            business_id=str(space_id),
            name=tag_name,
        )
        if any(t.name == tag_name for t in existing_tags):
            raise SpaceTagExistsError()

        new_tag = Tag(
            name=tag_name,
            user_id=self.login_user.user_id,
            business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE,
            business_id=str(space_id),
        )
        return await TagDao.ainsert_tag(new_tag)

    async def delete_space_tag(self, space_id: int, tag_id: int):
        await self._require_permission_id("knowledge_space", space_id, "edit_space")
        return await TagDao.delete_business_tag(
            tag_id,
            business_id=str(space_id),
            business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE,
        )

    async def update_file_tags(self, space_id: int, file_id: int, tag_ids: List[int]):
        """2：支持对单文件的标签管理: Overwrite tags for a single file."""
        await self._get_file_for_action(file_id, space_id=space_id)
        await self._require_permission_id(
            "knowledge_file", file_id, "rename_file", space_id=space_id
        )

        resource_id = str(file_id)
        resource_type = ResourceTypeEnum.SPACE_FILE
        await TagDao.aupdate_resource_tags(
            tag_ids, resource_id, resource_type, self.login_user.user_id
        )
        await KnowledgeDao.async_update_knowledge_update_time_by_id(space_id)

    async def batch_add_file_tags(
        self, space_id: int, file_ids: List[int], tag_ids: List[int]
    ):
        """1：支持对文件批量添加标签: Batch add tags to files."""
        await self._require_read_permission(space_id)
        if not file_ids or not tag_ids:
            return

        files = await self._get_space_files_or_raise(space_id, file_ids)

        resource_type = ResourceTypeEnum.SPACE_FILE
        for file_record in files:
            await self._require_permission_id(
                "knowledge_file", file_record.id, "rename_file", space_id=space_id
            )
            await TagDao.add_tags(
                tag_ids, str(file_record.id), resource_type, self.login_user.user_id
            )

        await KnowledgeDao.async_update_knowledge_update_time_by_id(space_id)

    async def retry_space_files(self, space_id: int, req_data: dict) -> list:
        """
        Retry logic for multiple files in a knowledge space with potentially new split rules.
        Similar to KnowledgeService.retry_files but scoped to a space.
        """
        space = await KnowledgeDao.aquery_by_id(space_id)
        if not space or space.type != KnowledgeTypeEnum.SPACE.value:
            raise SpaceNotFoundError()
        await self._require_read_permission(space_id)
        self._ensure_space_async_task_tenant_consistency(space, "retry_space_files")

        db_file_retry = req_data.get("file_objs")
        if not db_file_retry:
            return []

        id2input = {file.get("id"): file for file in db_file_retry}
        file_ids = list(id2input.keys())
        db_files = await KnowledgeFileDao.aget_file_by_ids(file_ids)
        if not db_files:
            return []

        for db_file in db_files:
            if db_file.knowledge_id != space_id:
                raise SpaceFileNotFoundError()
            await self._require_resource_permission(
                "can_edit", "knowledge_file", db_file.id
            )

        tmp, file_level_path = await self.process_retry_files(
            db_files, id2input, self.login_user
        )

        for folder_path in file_level_path:
            await self.update_folder_update_time(folder_path)

        await KnowledgeDao.async_update_knowledge_update_time_by_id(space_id)
        return []

    async def batch_retry_failed_files(self, space_id: int, file_ids: List[int]):
        from bisheng.worker import retry_knowledge_file_celery

        space = await KnowledgeDao.aquery_by_id(space_id)
        if not space:
            raise SpaceNotFoundError()
        await self._require_read_permission(space_id)
        self._ensure_space_async_task_tenant_consistency(
            space, "batch_retry_failed_files"
        )

        retry_files = await KnowledgeFileDao.aget_file_by_ids(file_ids)
        all_file_ids = []
        all_file_level_path = set()
        retryable_status = {
            KnowledgeFileStatus.FAILED.value,
            KnowledgeFileStatus.VIOLATION.value,
        }
        for file in retry_files:
            if file.knowledge_id != space_id:
                continue
            if (
                file.file_type == FileType.FILE.value
                and file.status in retryable_status
            ):
                await self._require_resource_permission(
                    "can_edit", "knowledge_file", file.id
                )
                retry_knowledge_file_celery.delay(file.id)
                all_file_ids.append(file.id)
                all_file_level_path.add(file.file_level_path)
            elif file.file_type == FileType.DIR.value:
                await self._require_resource_permission("can_edit", "folder", file.id)
                all_failed_files = await SpaceFileDao.get_children_by_prefix(
                    knowledge_id=space_id, prefix=file.file_level_path + f"/{file.id}"
                )
                for item in all_failed_files:
                    if (
                        item.status in retryable_status
                        and item.file_type == FileType.FILE.value
                    ):
                        await self._require_resource_permission(
                            "can_edit", "knowledge_file", item.id
                        )
                        retry_knowledge_file_celery.delay(item.id)
                        all_file_ids.append(item.id)
                        all_file_level_path.add(file.file_level_path)
        if all_file_ids:
            await KnowledgeFileDao.aupdate_file_status(
                all_file_ids, KnowledgeFileStatus.WAITING, "batch_retry_failed_files"
            )
            await KnowledgeDao.async_update_knowledge_update_time_by_id(space_id)
        for one in all_file_level_path:
            if one:
                await self.update_folder_update_time(one)
        return True

    # ──────────────────────────── Batch Ops ───────────────────────────────────

    async def batch_delete(
        self, knowledge_id: int, file_ids: List[int], folder_ids: List[int]
    ):
        from bisheng.worker.knowledge.file_worker import delete_knowledge_file_celery

        knowledge = await KnowledgeDao.aquery_by_id(knowledge_id)
        if not knowledge:
            raise SpaceNotFoundError()

        await self._require_read_permission(knowledge_id)
        self._ensure_space_async_task_tenant_consistency(knowledge, "batch_delete")

        for folder_id in folder_ids:
            await self.delete_folder(knowledge.id, folder_id)

        if file_ids:
            direct_files = []
            for file_id in self._dedupe_ids(file_ids):
                file_record = await self._get_file_for_action(
                    file_id, space_id=knowledge_id
                )
                await self._require_permission_id(
                    "knowledge_file", file_id, "delete_file", space_id=knowledge_id
                )
                direct_files.append(file_record)
            direct_file_ids = [file.id for file in direct_files]
            await KnowledgeFileDao.adelete_batch(direct_file_ids)
            delete_knowledge_file_celery.delay(
                file_ids=direct_file_ids, knowledge_id=knowledge.id, clear_minio=True
            )
            await self._cleanup_resource_tuples(
                [("knowledge_file", file_id) for file_id in direct_file_ids]
            )

        # Prune channel ➜ knowledge-folder sync bindings for the top-level
        # folders deleted in this batch so the Celery sync worker stops
        # referencing a tombstone. Per-folder cascades are pruned by
        # delete_folder() above.
        if folder_ids:
            from bisheng.channel.domain.models.channel_knowledge_sync import (
                ChannelKnowledgeSyncDao,
            )

            try:
                await ChannelKnowledgeSyncDao.adelete_by_folder_ids(folder_ids)
            except Exception as e:
                _logger.warning(
                    "Failed to cleanup channel knowledge sync bindings for folders %s: %s",
                    folder_ids,
                    e,
                )

        if file_ids:
            await KnowledgeDao.async_update_knowledge_update_time_by_id(knowledge.id)

    async def batch_download(
        self, space_id: int, file_ids: List[int], folder_ids: List[int]
    ) -> str:
        """
        Download selected files and folders, preserving the original directory structure,
        compress into a zip archive, upload to the MinIO tmp bucket, and return a
        presigned URL (valid for 7 days).

        Directory structure is reconstructed from file_level_path (e.g. '/7/42') by
        resolving each segment id to the corresponding folder name.
        """
        space = await KnowledgeDao.aquery_by_id(space_id)
        if not space or space.type != KnowledgeTypeEnum.SPACE.value:
            raise SpaceNotFoundError()

        # ── 1. Collect all file records to include ────────────────────────────
        # Explicit files requested directly
        direct_files = []
        for file_id in self._dedupe_ids(file_ids):
            file_record = await self._get_file_for_action(file_id, space_id=space_id)
            await self._require_permission_id(
                "knowledge_file", file_id, "download_file", space_id=space_id
            )
            direct_files.append(file_record)

        # Files & sub-folders under every requested folder_id
        folder_db_records: List[KnowledgeFile] = []
        for folder_id in self._dedupe_ids(folder_ids):
            folder = await self._get_folder_for_action(space_id, folder_id)
            await self._require_permission_id(
                "folder", folder_id, "download_folder", space_id=space_id
            )
            prefix = f"{folder.file_level_path}/{folder.id}"
            descendants = await SpaceFileDao.get_children_by_prefix(
                folder.knowledge_id, prefix
            )
            for descendant in descendants:
                if descendant.file_type == FileType.DIR.value:
                    await self._require_permission_id(
                        "folder", descendant.id, "download_folder", space_id=space_id
                    )
                else:
                    await self._require_permission_id(
                        "knowledge_file",
                        descendant.id,
                        "download_file",
                        space_id=space_id,
                    )
            folder_db_records.append(folder)
            folder_db_records.extend(descendants)

        # All KnowledgeFile objects this download touches
        all_records: List[KnowledgeFile] = direct_files + folder_db_records

        # ── 2. Build id→name map for every folder encountered ─────────────────
        #       We need this to translate '/7/42' → 'Reports/Q1'
        folder_id_to_name: dict[int, str] = {}
        for rec in all_records:
            if rec.file_type == FileType.DIR.value:
                folder_id_to_name[rec.id] = rec.file_name

        # Collect any ancestor folder IDs referenced in file_level_path but not yet known
        missing_ids: set[int] = set()
        for rec in all_records:
            if not rec.file_level_path:
                continue
            for part in rec.file_level_path.split("/"):
                if not part:
                    continue
                try:
                    fid = int(part)
                    if fid not in folder_id_to_name:
                        missing_ids.add(fid)
                except ValueError:
                    pass

        if missing_ids:
            extra_folders = await KnowledgeFileDao.aget_file_by_ids(list(missing_ids))
            for f in extra_folders:
                if f.file_type == FileType.DIR.value:
                    folder_id_to_name[f.id] = f.file_name

        def resolve_dir_path(file_level_path: Optional[str]) -> str:
            """Convert '/7/42' to 'FolderA/SubFolderB' using the name map."""
            if not file_level_path:
                return ""
            parts = [p for p in file_level_path.split("/") if p]
            names = []
            for part in parts:
                try:
                    fid = int(part)
                    names.append(folder_id_to_name.get(fid, str(fid)))
                except ValueError:
                    names.append(part)
            return "/".join(names)

        # ── 3. Download files from MinIO and write into a temp dir ────────────
        from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync

        minio = get_minio_storage_sync()

        import os
        import zipfile
        from datetime import datetime

        with tempfile.TemporaryDirectory() as tmp_dir:
            for rec in all_records:
                rel_dir = resolve_dir_path(rec.file_level_path)
                local_dir = os.path.join(tmp_dir, rel_dir) if rel_dir else tmp_dir
                os.makedirs(local_dir, exist_ok=True)
                local_path = os.path.join(local_dir, rec.file_name)

                if rec.file_type == FileType.DIR.value:
                    # Create the folder explicitly so empty folders exist in tmp_dir
                    os.makedirs(local_path, exist_ok=True)
                    continue

                target_object_name = rec.object_name
                # If file source is CHANNEL, use preview_object_name to download the HTML file
                if (
                    rec.file_source == FileSource.CHANNEL.value
                    and rec.preview_file_object_name
                ):
                    target_object_name = rec.preview_file_object_name
                    name, _ = os.path.splitext(rec.file_name)
                    local_path = os.path.join(local_dir, f"{name}.html")

                if not target_object_name:  # no stored object – skip
                    continue

                try:
                    response = minio.download_object_sync(
                        object_name=target_object_name
                    )
                    with open(local_path, "wb") as f:
                        for one in response.stream(65536):
                            f.write(one)
                except Exception:
                    # Skip files that cannot be fetched (e.g. not yet parsed)
                    continue
                finally:
                    response.close()
                    response.release_conn()

            # ── 4. Create zip archive ─────────────────────────────────────────
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            zip_folder = generate_uuid()
            zip_name = f"{timestamp}_{zip_folder[:6]}.zip"
            zip_path = os.path.join(tmp_dir, zip_name)

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(tmp_dir):
                    # Add directories to ensure empty directories are included in the zip
                    for dirname in dirs:
                        dir_path = os.path.join(root, dirname)
                        arcname = os.path.relpath(dir_path, tmp_dir)
                        zf.write(dir_path, arcname)
                    # Add files
                    for filename in files:
                        if filename == zip_name:
                            continue  # don't zip the zip itself
                        full_path = os.path.join(root, filename)
                        arcname = os.path.relpath(full_path, tmp_dir)
                        zf.write(full_path, arcname)

            # ── 5. Upload zip to MinIO tmp bucket & return presigned URL ──────
            minio_object_name = f"download/{zip_folder}/{zip_name}"
            await minio.put_object_tmp(
                minio_object_name, Path(zip_path), content_type="application/zip"
            )
            share_url = await minio.get_share_link(
                minio_object_name,
                bucket=minio.tmp_bucket,
                clear_host=True,
                expire_days=7,
            )

        return share_url

    # ──────────────────────────── Subscribe ───────────────────────────────────

    async def subscribe_space(self, space_id: int) -> dict:
        """
        Subscribe the current user to a knowledge space.
        - PRIVATE spaces cannot be subscribed.
        - PUBLIC spaces: status = active (True) → 'subscribed'
        - APPROVAL spaces: status = pending (False) → 'pending'
        Returns {"status": "subscribed" | "pending", "space_id": space_id}
        """
        space = await KnowledgeDao.aquery_by_id(space_id)
        if not space or space.type != KnowledgeTypeEnum.SPACE.value:
            raise SpaceNotFoundError()

        if space.auth_type == AuthTypeEnum.PRIVATE:
            raise SpaceSubscribePrivateError()

        target_status = (
            MembershipStatusEnum.ACTIVE
            if space.auth_type == AuthTypeEnum.PUBLIC
            else MembershipStatusEnum.PENDING
        )

        existing = await SpaceChannelMemberDao.async_find_member(
            space_id, self.login_user.user_id
        )
        if existing is not None:
            if existing.user_role != UserRoleEnum.MEMBER:
                return {
                    "status": "subscribed",
                    "space_id": space_id,
                }
            if existing.status == MembershipStatusEnum.ACTIVE:
                return {
                    "status": "subscribed",
                    "space_id": space_id,
                }
            if (
                existing.status == MembershipStatusEnum.PENDING
                and target_status == MembershipStatusEnum.PENDING
            ):
                return {
                    "status": "pending",
                    "space_id": space_id,
                }

        if not existing or existing.status == MembershipStatusEnum.REJECTED:
            count = await SpaceChannelMemberDao.async_count_user_space_subscriptions(
                self.login_user.user_id
            )
            if count >= _MAX_SUBSCRIBE_PER_USER:
                raise SpaceSubscribeLimitError()

        previous_status = existing.status if existing else None
        if existing:
            existing.status = target_status
            existing = await SpaceChannelMemberDao.update(existing)
            member = existing
        else:
            member = SpaceChannelMember(
                business_id=str(space_id),
                business_type=BusinessTypeEnum.SPACE,
                user_id=self.login_user.user_id,
                user_role=UserRoleEnum.MEMBER,
                status=target_status,
            )
            await SpaceChannelMemberDao.async_insert_member(member)

        if space.auth_type == AuthTypeEnum.APPROVAL:
            gate = self.approval_gate or self._build_space_approval_gate()
            gate_result = await gate.request_or_pass(
                ApprovalGateRequest(
                    tenant_id=self.login_user.tenant_id,
                    scenario_code="knowledge_space_subscribe_request",
                    business_key=f"space:{space.id}:user:{self.login_user.user_id}",
                    business_resource_type="knowledge_space",
                    business_resource_id=str(space.id),
                    business_name=space.name,
                    applicant_user_id=self.login_user.user_id,
                    applicant_user_name=self.login_user.user_name,
                    payload_snapshot={
                        "space_id": space.id,
                        "space_name": space.name,
                        "space_type": getattr(space, "type", ""),
                        "applicant_user_id": self.login_user.user_id,
                    },
                )
            )
            if gate_result.decision == "pass":
                member.status = MembershipStatusEnum.ACTIVE
                if existing:
                    member = await SpaceChannelMemberDao.update(member)
                else:
                    member = await SpaceChannelMemberDao.update(member)
                await self.__class__.sync_direct_space_user_permissions(
                    space_id,
                    member.user_id,
                    member.user_role,
                    is_active=True,
                )
                return {
                    "status": "subscribed",
                    "space_id": space_id,
                }
        elif previous_status != MembershipStatusEnum.PENDING:
            await self._send_subscription_notification(space)

        if member.status == MembershipStatusEnum.ACTIVE:
            await self.__class__.sync_direct_space_user_permissions(
                space_id,
                member.user_id,
                member.user_role,
                is_active=True,
            )

        return {
            "status": "subscribed"
            if member.status == MembershipStatusEnum.ACTIVE
            else "pending",
            "space_id": space_id,
        }

    def _build_space_approval_gate(self) -> ApprovalGate:
        registry = ApprovalRegistry.with_default_presets()
        registry.register_handler(
            "knowledge_space_subscribe_request",
            KnowledgeSpaceSubscribeScenarioHandler(
                find_member=SpaceChannelMemberDao.async_find_member,
                update_member=SpaceChannelMemberDao.update,
                sync_permissions=self.__class__.sync_direct_space_user_permissions,
            ),
        )
        return ApprovalGate(registry=registry)

    async def _send_subscription_notification(self, space: Knowledge):
        if space.auth_type != AuthTypeEnum.APPROVAL or not self.message_service:
            return
        members = await SpaceChannelMemberDao.async_get_members_by_space(
            space.id, user_roles=[UserRoleEnum.ADMIN, UserRoleEnum.CREATOR]
        )
        member_ids = [one.user_id for one in members]
        await self.message_service.send_generic_approval(
            applicant_user_id=self.login_user.user_id,
            applicant_user_name=self.login_user.user_name,
            action_code="request_knowledge_space",
            business_type="knowledge_space_id",
            business_id=str(space.id),
            business_name=space.name,
            button_action_code="request_knowledge_space",
            receiver_user_ids=member_ids,
        )

    async def unsubscribe_space(self, space_id: int) -> bool:
        space = await KnowledgeDao.aquery_by_id(space_id)
        if not space or space.type != KnowledgeTypeEnum.SPACE.value:
            raise SpaceNotFoundError()

        current_membership = await SpaceChannelMemberDao.async_find_member(
            space_id, self.login_user.user_id
        )
        if space.user_id == self.login_user.user_id or (
            current_membership and current_membership.user_role == UserRoleEnum.CREATOR
        ):
            raise SpacePermissionDeniedError()

        await self._revoke_direct_space_user_permissions(
            space_id, self.login_user.user_id
        )
        deleted = await SpaceChannelMemberDao.delete_space_member(
            space_id, self.login_user.user_id
        )
        return deleted
