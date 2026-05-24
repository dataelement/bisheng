import asyncio
import hashlib
import hmac
import logging
import secrets
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, TYPE_CHECKING

from fastapi import Request
from loguru import logger
from sqlalchemy import func
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
    SpaceFileDuplicateError,
    SpaceSubscribePrivateError,
    SpaceSubscribeLimitError,
    SpacePermissionDeniedError,
    SpaceTagExistsError,
    SpaceFileSizeLimitError,
    SpaceInvalidLevelError,
    SpaceInvalidScopeOwnerError,
    SpaceCreatePublicDeniedError,
    SpaceCreateDepartmentDeniedError,
    SpaceCreateTeamDeniedError,
    SpaceNameDuplicateError,
    SpaceTenantMismatchError,
)
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.common.utils import util as common_util
from bisheng.common.errcode.knowledge import KnowledgeFileFailedError
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
from bisheng.database.models.department import DepartmentDao, UserDepartment, UserDepartmentDao
from bisheng.database.models.group import GroupDao
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tenant import TenantDao
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
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceOwnerTypeEnum,
    KnowledgeSpaceScope,
    KnowledgeSpaceScopeDao,
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
    GroupedKnowledgeSpacesResp,
    KnowledgeSpaceCreateOptionsResp,
    KnowledgeSpaceCreateOptionDepartmentsResp,
    KnowledgeSpaceCreateOptionUserGroupsResp,
    KnowledgeSpaceCreateOptionDepartment,
    KnowledgeSpaceCreateOptionUserGroup,
    ShougangPortalFavoriteCreateReq,
    ShougangPortalFavoriteCreateResp,
    ShougangPortalFileItemResp,
    ShougangPortalFileSearchReq,
    ShougangPortalHomeReq,
    ShougangPortalPersonalSpaceItemResp,
    ShougangPortalShareLinkAccessResp,
    ShougangPortalShareLinkCreateReq,
    ShougangPortalShareLinkCreateResp,
    ShougangPortalShareLinkMetaResp,
    ShougangPortalShareLinkVerifyReq,
    ShougangPortalSharePermissions,
    ShougangPortalShareType,
    ShougangPortalShareVisibility,
    ShougangPortalSpaceInfoError,
    ShougangPortalSpaceInfoItemResp,
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
from bisheng.telemetry.domain.mid_table.knowledge_space_content import KnowledgeSpaceContentStat
from bisheng.approval.domain.services.approval_gate import ApprovalGate
from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateDecision, ApprovalGateRequest
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
from bisheng.share_link.domain.models.share_link import (
    ResourceTypeEnum as ShareResourceTypeEnum,
    ShareLink,
    ShareLinkStatusEnum,
    ShareMode,
)
from bisheng.share_link.domain.repositories.implementations.share_link_repository_impl import ShareLinkRepositoryImpl
from bisheng.user.domain.models.user import UserDao
from bisheng.utils import generate_uuid
from bisheng.worker.knowledge import file_worker

if TYPE_CHECKING:
    from bisheng.message.domain.services.message_service import MessageService
    from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_version_repository import (
        KnowledgeDocumentVersionRepository,
    )
    from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_repository import (
        KnowledgeDocumentRepository,
    )

# Maximum number of Knowledge Spaces a user can create
_MAX_SPACE_PER_USER = 200
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
        # Injected by DI factory alongside version_repo. Used by the version-link
        # cascade during file deletion to clear the logical-document anchor
        # whenever the whole chain (or its primary) gets removed.
        self.doc_repo: Optional["KnowledgeDocumentRepository"] = None

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
    _SHOUGANG_PORTAL_SHARE_SECRET_ALGORITHM = 'pbkdf2_sha256'
    _SHOUGANG_PORTAL_SHARE_SECRET_ITERATIONS = 120_000

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

    async def _get_tenant_root_department_id(self) -> int:
        tenant = await TenantDao.aget_by_id(int(self.login_user.tenant_id))
        root_dept_id = int(getattr(tenant, 'root_dept_id', 0) or 0) if tenant else 0
        if not root_dept_id:
            raise SpaceInvalidScopeOwnerError(msg='Tenant root department does not exist')
        dept = await DepartmentDao.aget_by_id(root_dept_id)
        if dept is None or getattr(dept, 'status', 'active') != 'active':
            raise SpaceInvalidScopeOwnerError(msg='Tenant root department does not exist')
        return root_dept_id

    @staticmethod
    def _normalize_space_level(level: KnowledgeSpaceLevelEnum | str | None) -> KnowledgeSpaceLevelEnum:
        if level is None:
            return KnowledgeSpaceLevelEnum.PERSONAL
        if isinstance(level, KnowledgeSpaceLevelEnum):
            return level
        try:
            return KnowledgeSpaceLevelEnum(str(level))
        except ValueError:
            raise SpaceInvalidLevelError()

    async def _admin_department_ids(self) -> set[int]:
        departments = await DepartmentDao.aget_user_admin_departments(self.login_user.user_id)
        ids: set[int] = set()
        for dept in departments:
            if getattr(dept, 'id', None) is None:
                continue
            ids.add(int(dept.id))
            path = getattr(dept, 'path', None)
            if path:
                ids.update(int(i) for i in await DepartmentDao.aget_subtree_ids(path))
        return ids

    async def _user_group_ids_for_create(self) -> set[int]:
        if self.login_user.is_admin():
            groups, _ = await GroupDao.aget_all_groups(1, 2000, '')
        else:
            groups, _ = await GroupDao.aget_visible_groups(self.login_user.user_id, 1, 2000, '')
        return {
            int(group.id)
            for group in groups or []
            if getattr(group, 'id', None) is not None
        }

    @staticmethod
    def _paginate_options(items: list, page: int, page_size: int) -> tuple[list, int]:
        total = len(items)
        safe_page = max(int(page or 1), 1)
        safe_page_size = min(max(int(page_size or 20), 1), 100)
        offset = (safe_page - 1) * safe_page_size
        return items[offset:offset + safe_page_size], total

    @staticmethod
    def _department_path_name(dept, department_name_map: Dict[int, str]) -> Optional[str]:
        path_ids = [
            int(part)
            for part in str(getattr(dept, 'path', '') or '').split('/')
            if part.isdigit()
        ]
        names = [department_name_map.get(dept_id) for dept_id in path_ids if department_name_map.get(dept_id)]
        if not names and getattr(dept, 'name', None):
            names = [dept.name]
        return '/'.join(names) if names else None

    async def _department_options_for_create(self) -> list[KnowledgeSpaceCreateOptionDepartment]:
        if self.login_user.is_admin():
            departments = await DepartmentDao.aget_active_by_tenant(int(self.login_user.tenant_id))
        else:
            department_ids = await self._admin_department_ids()
            departments = await DepartmentDao.aget_by_ids(list(department_ids)) if department_ids else []

        dept_name_map = {
            int(dept.id): dept.name
            for dept in departments
            if getattr(dept, 'id', None) is not None
        }
        options = [
            KnowledgeSpaceCreateOptionDepartment(
                id=int(dept.id),
                name=dept.name,
                path_name=self._department_path_name(dept, dept_name_map),
            )
            for dept in departments
            if getattr(dept, 'id', None) is not None
        ]
        return sorted(options, key=lambda item: (item.path_name or item.name or '', item.id))

    async def _department_tree_for_create(self) -> list[dict]:
        if self.login_user.is_admin():
            departments = await DepartmentDao.aget_active_by_tenant(int(self.login_user.tenant_id))
        else:
            department_ids = await self._admin_department_ids()
            departments = await DepartmentDao.aget_by_ids(list(department_ids)) if department_ids else []
        if not departments:
            return []

        dept_ids = [
            int(dept.id)
            for dept in departments
            if getattr(dept, 'id', None) is not None
        ]
        count_map: Dict[int, int] = {}
        async with get_async_db_session() as session:
            count_result = await session.exec(
                select(
                    UserDepartment.department_id,
                    func.count(UserDepartment.id),
                )
                .where(UserDepartment.department_id.in_(dept_ids))
                .group_by(UserDepartment.department_id)
            )
            count_map = {
                int(dept_id): int(count)
                for dept_id, count in count_result.all()
            }

        nodes = {
            int(dept.id): {
                'id': int(dept.id),
                'dept_id': getattr(dept, 'dept_id', '') or '',
                'name': dept.name,
                'parent_id': int(dept.parent_id) if getattr(dept, 'parent_id', None) is not None else None,
                'member_count': count_map.get(int(dept.id), 0),
                'sort_order': int(getattr(dept, 'sort_order', 0) or 0),
                'children': [],
            }
            for dept in departments
            if getattr(dept, 'id', None) is not None
        }
        roots: list[dict] = []
        for node in nodes.values():
            parent_id = node['parent_id']
            if parent_id and parent_id in nodes:
                nodes[parent_id]['children'].append(node)
            else:
                roots.append(node)

        def _sort_tree(items: list[dict]) -> list[dict]:
            items.sort(key=lambda item: (item.get('sort_order', 0), item.get('name', '')))
            for item in items:
                item['children'] = _sort_tree(item.get('children', []))
                item.pop('sort_order', None)
            return items

        return _sort_tree(roots)

    async def _user_group_options_for_create(self) -> list[KnowledgeSpaceCreateOptionUserGroup]:
        user_group_ids = await self._user_group_ids_for_create()
        groups = await GroupDao.aget_group_by_ids(list(user_group_ids)) if user_group_ids else []
        options = [
            KnowledgeSpaceCreateOptionUserGroup(id=int(group.id), group_name=group.group_name)
            for group in groups
            if getattr(group, 'id', None) is not None
        ]
        return sorted(options, key=lambda item: item.group_name or '')

    async def _resolve_space_scope_on_create(
        self,
        *,
        space_level: KnowledgeSpaceLevelEnum | str | None,
        department_id: Optional[int],
        user_group_id: Optional[int],
    ) -> tuple[KnowledgeSpaceLevelEnum, KnowledgeSpaceOwnerTypeEnum, int]:
        level = self._normalize_space_level(space_level)

        if level == KnowledgeSpaceLevelEnum.PUBLIC:
            if department_id is not None or user_group_id is not None:
                raise SpaceInvalidScopeOwnerError()
            if not self.login_user.is_admin():
                raise SpaceCreatePublicDeniedError()
            return level, KnowledgeSpaceOwnerTypeEnum.TENANT_ROOT_DEPARTMENT, await self._get_tenant_root_department_id()

        if level == KnowledgeSpaceLevelEnum.DEPARTMENT:
            if department_id is None or user_group_id is not None:
                raise SpaceInvalidScopeOwnerError()
            dept = await DepartmentDao.aget_by_id(int(department_id))
            if dept is None or getattr(dept, 'status', 'active') != 'active':
                raise SpaceInvalidScopeOwnerError(msg='Department does not exist or is archived')
            if not self.login_user.is_admin():
                admin_department_ids = await self._admin_department_ids()
                if int(department_id) not in admin_department_ids:
                    raise SpaceCreateDepartmentDeniedError()
            return level, KnowledgeSpaceOwnerTypeEnum.DEPARTMENT, int(department_id)

        if level == KnowledgeSpaceLevelEnum.TEAM:
            if user_group_id is None or department_id is not None:
                raise SpaceInvalidScopeOwnerError()
            group = await GroupDao.aget_by_id(int(user_group_id))
            if group is None:
                raise SpaceInvalidScopeOwnerError(msg='User group does not exist')
            user_group_ids = await self._user_group_ids_for_create()
            if int(user_group_id) not in user_group_ids:
                raise SpaceCreateTeamDeniedError()
            return level, KnowledgeSpaceOwnerTypeEnum.USER_GROUP, int(user_group_id)

        if level == KnowledgeSpaceLevelEnum.PERSONAL:
            if department_id is not None or user_group_id is not None:
                raise SpaceInvalidScopeOwnerError()
            return level, KnowledgeSpaceOwnerTypeEnum.USER, int(self.login_user.user_id)

        raise SpaceInvalidScopeOwnerError()

    async def _create_space_scope(
        self,
        *,
        space_id: int,
        level: KnowledgeSpaceLevelEnum,
        owner_type: KnowledgeSpaceOwnerTypeEnum,
        owner_id: int,
    ) -> KnowledgeSpaceScope:
        return await KnowledgeSpaceScopeDao.acreate(
            tenant_id=int(self.login_user.tenant_id),
            space_id=space_id,
            level=level,
            owner_type=owner_type,
            owner_id=owner_id,
            created_by=int(self.login_user.user_id),
        )

    async def _ensure_space_name_unique_in_scope(
        self,
        *,
        name: str,
        level: KnowledgeSpaceLevelEnum,
        owner_type: KnowledgeSpaceOwnerTypeEnum,
        owner_id: int,
        exclude_id: Optional[int] = None,
        tenant_id: Optional[int] = None,
    ) -> None:
        existing_space = await KnowledgeDao.async_get_space_by_scope_name(
            tenant_id=int(tenant_id or self.login_user.tenant_id),
            level=level,
            owner_type=owner_type,
            owner_id=owner_id,
            name=name,
            exclude_id=exclude_id,
        )
        if existing_space:
            raise SpaceNameDuplicateError()

    async def _grant_default_scope_permissions(
        self,
        *,
        level: KnowledgeSpaceLevelEnum,
        owner_id: int,
        space_id: int,
    ) -> None:
        grant: Optional[AuthorizeGrantItem] = None
        if level == KnowledgeSpaceLevelEnum.PUBLIC:
            grant = AuthorizeGrantItem(
                subject_type='department',
                subject_id=owner_id,
                relation='viewer',
                include_children=True,
            )
        elif level == KnowledgeSpaceLevelEnum.DEPARTMENT:
            grant = AuthorizeGrantItem(
                subject_type='department',
                subject_id=owner_id,
                relation='viewer',
                include_children=True,
            )
        elif level == KnowledgeSpaceLevelEnum.TEAM:
            grant = AuthorizeGrantItem(
                subject_type='user_group',
                subject_id=owner_id,
                relation='viewer',
                include_children=False,
            )
        if grant is None:
            return
        await PermissionService.authorize(
            object_type='knowledge_space',
            object_id=str(space_id),
            grants=[grant],
            enforce_fga_success=True,
        )

    async def get_create_options(self) -> KnowledgeSpaceCreateOptionsResp:
        user_group_ids = await self._user_group_ids_for_create()
        if self.login_user.is_admin():
            can_create_department = True
        else:
            can_create_department = bool(
                await DepartmentDao.aget_user_admin_departments(self.login_user.user_id)
            )

        return KnowledgeSpaceCreateOptionsResp(
            can_create_public=bool(self.login_user.is_admin()),
            can_create_department=can_create_department,
            can_create_team=bool(user_group_ids),
            can_create_personal=True,
            departments=[],
            user_groups=[],
            default_space_level=KnowledgeSpaceLevelEnum.PERSONAL,
        )

    async def get_create_departments(
        self,
        *,
        keyword: str = '',
        page: int = 1,
        page_size: int = 20,
    ) -> KnowledgeSpaceCreateOptionDepartmentsResp:
        tree = await self._department_tree_for_create()
        return KnowledgeSpaceCreateOptionDepartmentsResp(data=tree, total=len(tree))

    async def get_create_user_groups(
        self,
        *,
        keyword: str = '',
        page: int = 1,
        page_size: int = 20,
    ) -> KnowledgeSpaceCreateOptionUserGroupsResp:
        options = await self._user_group_options_for_create()
        normalized_keyword = (keyword or '').strip().lower()
        if normalized_keyword:
            options = [
                item for item in options
                if normalized_keyword in (item.group_name or '').lower()
            ]
        page_items, total = self._paginate_options(options, page, page_size)
        return KnowledgeSpaceCreateOptionUserGroupsResp(data=page_items, total=total)

    async def _decorate_department_metadata(
        self,
        spaces: List[KnowledgeSpaceInfoResp],
    ) -> List[KnowledgeSpaceInfoResp]:
        if not spaces:
            return spaces
        space_ids = [int(space.id) for space in spaces]
        bindings = await DepartmentKnowledgeSpaceDao.aget_by_space_ids(space_ids)
        try:
            scopes = await KnowledgeSpaceScopeDao.aget_map_by_space_ids(space_ids)
        except Exception as e:
            _logger.debug('Failed to load knowledge space scope metadata: %s', e)
            scopes = {}
        binding_map = {binding.space_id: binding for binding in bindings}
        department_ids = {
            int(binding.department_id)
            for binding in bindings
            if getattr(binding, 'department_id', None) is not None
        }
        for scope in scopes.values():
            if scope.owner_type in {
                KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
                KnowledgeSpaceOwnerTypeEnum.TENANT_ROOT_DEPARTMENT,
            }:
                department_ids.add(int(scope.owner_id))
        departments = await DepartmentDao.aget_by_ids(list(department_ids))
        department_name_map = {int(dept.id): dept.name for dept in departments}

        group_ids = [
            int(scope.owner_id)
            for scope in scopes.values()
            if scope.owner_type == KnowledgeSpaceOwnerTypeEnum.USER_GROUP
        ]
        try:
            groups = await GroupDao.aget_group_by_ids(group_ids) if group_ids else []
        except Exception as e:
            _logger.debug('Failed to load knowledge space owner groups: %s', e)
            groups = []
        group_name_map = {int(group.id): group.group_name for group in groups}

        user_ids = {
            int(scope.owner_id)
            for scope in scopes.values()
            if scope.owner_type == KnowledgeSpaceOwnerTypeEnum.USER
        }
        user_ids.update(
            int(space.user_id)
            for space in spaces
            if int(space.id) not in scopes
        )
        try:
            users = await UserDao.aget_user_by_ids(list(user_ids)) if user_ids else []
        except Exception as e:
            _logger.debug('Failed to load knowledge space owner users: %s', e)
            users = []
        user_name_map = {int(user.user_id): user.user_name for user in users}

        for space in spaces:
            binding = binding_map.get(int(space.id))
            scope = scopes.get(int(space.id))
            if scope is None:
                if binding is not None:
                    space.space_level = KnowledgeSpaceLevelEnum.DEPARTMENT
                    space.owner_type = KnowledgeSpaceOwnerTypeEnum.DEPARTMENT
                    space.owner_id = int(binding.department_id)
                else:
                    space.space_level = KnowledgeSpaceLevelEnum.PERSONAL
                    space.owner_type = KnowledgeSpaceOwnerTypeEnum.USER
                    space.owner_id = int(space.user_id or 0)
            else:
                space.space_level = scope.level
                space.owner_type = scope.owner_type
                space.owner_id = int(scope.owner_id)

            if space.owner_type in {
                KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
                KnowledgeSpaceOwnerTypeEnum.TENANT_ROOT_DEPARTMENT,
            }:
                space.owner_name = department_name_map.get(int(space.owner_id or 0))
            elif space.owner_type == KnowledgeSpaceOwnerTypeEnum.USER_GROUP:
                space.owner_name = group_name_map.get(int(space.owner_id or 0))
            elif space.owner_type == KnowledgeSpaceOwnerTypeEnum.USER:
                space.owner_name = user_name_map.get(int(space.owner_id or 0))

            if binding is not None or space.space_level == KnowledgeSpaceLevelEnum.DEPARTMENT:
                dept_id = int(binding.department_id) if binding is not None else int(space.owner_id or 0)
                space.space_kind = 'department'
                space.department_id = dept_id
                space.department_name = department_name_map.get(dept_id)
                if binding is not None:
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
                result.can_unsubscribe = await self._can_unsubscribe_space(space, member_conf)
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

    @staticmethod
    def _is_default_join_relation_mirror(
        binding: dict,
        membership: SpaceChannelMember,
    ) -> bool:
        expected_relation = _SPACE_MEMBER_ROLE_TO_RELATION.get(membership.user_role)
        if expected_relation not in {'viewer', 'manager'}:
            return False
        return (
            binding.get('subject_type') == 'user'
            and binding.get('relation') == expected_relation
            and (binding.get('model_id') or expected_relation) == expected_relation
        )

    def _binding_grants_view_space(
        self,
        binding: dict,
        models: Dict[str, dict],
    ) -> bool:
        model_id = binding.get('model_id')
        model = models.get(model_id) if model_id else None
        permission_ids = self._permission_ids_for_relation(
            binding.get('relation') or '',
            model,
        )
        return 'view_space' in permission_ids

    async def _has_unsubscribe_rebac_coverage(
        self,
        space_id: int,
        membership: SpaceChannelMember,
    ) -> bool:
        bindings = [
            binding for binding in await self._get_relation_bindings()
            if (
                binding.get('resource_type') == 'knowledge_space'
                and str(binding.get('resource_id')) == str(space_id)
            )
        ]
        if not bindings:
            return False

        models: Optional[Dict[str, dict]] = None
        user_subject_strings: Optional[set[str]] = None
        binding_department_paths: Optional[Dict[int, str]] = None
        user_department_paths: Optional[Dict[int, str]] = None

        for binding in bindings:
            subject_type = binding.get('subject_type')
            if subject_type == 'user':
                if not self._is_direct_space_user_binding(binding, space_id, self.login_user.user_id):
                    continue
                if self._is_default_join_relation_mirror(binding, membership):
                    continue
                if models is None:
                    models = await self._get_relation_models_map()
                if self._binding_grants_view_space(binding, models):
                    return True
                continue

            if subject_type not in {'department', 'user_group'}:
                continue
            if user_subject_strings is None:
                user_subject_strings = await self._get_current_user_subject_strings()
            if binding_department_paths is None:
                binding_department_paths = await self._get_binding_department_paths(bindings)
            if user_department_paths is None:
                user_department_paths = await FineGrainedPermissionService.get_current_user_department_paths(
                    user_subject_strings,
                )
            if not FineGrainedPermissionService._binding_matches_current_user(
                binding,
                user_subject_strings,
                binding_department_paths,
                user_department_paths,
            ):
                continue
            if models is None:
                models = await self._get_relation_models_map()
            if self._binding_grants_view_space(binding, models):
                return True

        return False

    async def _can_unsubscribe_space(
        self,
        space: Knowledge,
        membership: Optional[SpaceChannelMember],
    ) -> bool:
        if not membership or not membership.is_active:
            return False
        if space.user_id == self.login_user.user_id or membership.user_role == UserRoleEnum.CREATOR:
            return False
        if (membership.membership_source or 'manual') != 'manual':
            return False
        return not await self._has_unsubscribe_rebac_coverage(int(space.id), membership)

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
        lineage_binding_can_override = object_type in {"folder", "knowledge_file"}
        permission_lineage = (
            [item for item in lineage if item[0] != "knowledge_space"]
            if lineage_binding_can_override
            else lineage
        )
        user_subject_strings = await self._get_current_user_subject_strings()
        bindings = await self._get_relation_bindings()
        binding_department_paths = await self._get_binding_department_paths(bindings)
        models = await self._get_relation_models_map()
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
            lineage=permission_lineage,
            nearest_binding_wins=lineage_binding_can_override,
            return_match_metadata=True,
            use_permission_level_fallback=not lineage_binding_can_override,
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

    async def validate_knowledge_space_create(
        self,
        name: str,
        description: Optional[str] = None,
        icon: Optional[str] = None,
        auth_type: AuthTypeEnum = AuthTypeEnum.PUBLIC,
        is_released: bool = False,
        space_level: KnowledgeSpaceLevelEnum | str | None = KnowledgeSpaceLevelEnum.PERSONAL,
        department_id: Optional[int] = None,
        user_group_id: Optional[int] = None,
        auto_tag_enabled: bool = False,
        auto_tag_library_id: Optional[int] = None,
        auto_tag_custom_tags: Optional[List[str]] = None,
        skip_user_limit: bool = False,
    ) -> tuple[KnowledgeSpaceLevelEnum, KnowledgeSpaceOwnerTypeEnum, int]:
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

        level, owner_type, owner_id = await self._resolve_space_scope_on_create(
            space_level=space_level,
            department_id=department_id,
            user_group_id=user_group_id,
        )
        await self._ensure_space_name_unique_in_scope(
            name=name,
            level=level,
            owner_type=owner_type,
            owner_id=owner_id,
        )

        if await self._is_auto_tag_feature_visible():
            auto_tag_touched = (
                auto_tag_enabled
                or auto_tag_library_id is not None
                or auto_tag_custom_tags is not None
            )
            if auto_tag_touched:
                if auto_tag_custom_tags is not None:
                    normalized = KnowledgeSpaceTagLibraryService.normalize_tags(
                        auto_tag_custom_tags
                    )
                    if not normalized:
                        raise KnowledgeSpaceTagLibraryInvalidError(
                            message="开启自动标签时必须提供至少一个自定义标签"
                        )
                else:
                    await KnowledgeSpaceTagLibraryService.validate_bindable_library(
                        auto_tag_library_id
                    )

        return level, owner_type, owner_id

    async def create_knowledge_space(
        self,
        name: str,
        description: Optional[str] = None,
        icon: Optional[str] = None,
        auth_type: AuthTypeEnum = AuthTypeEnum.PUBLIC,
        is_released: bool = False,
        space_level: KnowledgeSpaceLevelEnum | str | None = KnowledgeSpaceLevelEnum.PERSONAL,
        department_id: Optional[int] = None,
        user_group_id: Optional[int] = None,
        auto_tag_enabled: bool = False,
        auto_tag_library_id: Optional[int] = None,
        auto_tag_custom_tags: Optional[List[str]] = None,
        skip_user_limit: bool = False,
    ) -> Knowledge:
        """Create a new knowledge space (max 200 per user)."""

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

        level, owner_type, owner_id = await self._resolve_space_scope_on_create(
            space_level=space_level,
            department_id=department_id,
            user_group_id=user_group_id,
        )
        await self._ensure_space_name_unique_in_scope(
            name=name,
            level=level,
            owner_type=owner_type,
            owner_id=owner_id,
        )

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

        await self._create_space_scope(
            space_id=int(knowledge_space.id),
            level=level,
            owner_type=owner_type,
            owner_id=owner_id,
        )
        await self._grant_default_scope_permissions(
            level=level,
            owner_id=owner_id,
            space_id=int(knowledge_space.id),
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
        member_info = None
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
                is_global_admin = False
                is_admin = getattr(self.login_user, 'is_admin', None)
                if callable(is_admin):
                    is_global_admin = bool(is_admin())
                if result.user_role is not None and not is_global_admin:
                    self._apply_subscription_flags(result, SpaceSubscriptionStatusEnum.SUBSCRIBED)
            if result.user_role is None and has_content_permission:
                result.user_role = UserRoleEnum.MEMBER
        result.follower_num = follower_num
        result.file_num = total_file_num
        result.can_unsubscribe = await self._can_unsubscribe_space(space, member_info)
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

    async def get_shougang_portal_space_levels(self) -> List[Dict]:
        return [
            {"value": KnowledgeSpaceLevelEnum.PUBLIC.value, "label": "公共空间"},
            {"value": KnowledgeSpaceLevelEnum.DEPARTMENT.value, "label": "部门空间"},
            {"value": KnowledgeSpaceLevelEnum.TEAM.value, "label": "团队空间"},
            {"value": KnowledgeSpaceLevelEnum.PERSONAL.value, "label": "个人空间"},
        ]

    async def get_shougang_portal_personal_spaces(self) -> Dict:
        grouped = await self.get_grouped_spaces()
        items: List[ShougangPortalPersonalSpaceItemResp] = []
        for space in getattr(grouped, 'personal_spaces', []) or []:
            if getattr(space, 'space_level', KnowledgeSpaceLevelEnum.PERSONAL) != KnowledgeSpaceLevelEnum.PERSONAL:
                continue
            permission_ids = await self._get_effective_permission_ids('knowledge_space', int(space.id))
            if 'upload_file' not in permission_ids:
                continue
            items.append(
                ShougangPortalPersonalSpaceItemResp(
                    id=int(space.id),
                    name=str(space.name or ''),
                    description=str(space.description or ''),
                    file_count=int(getattr(space, 'file_num', 0) or 0),
                    updated_at=self._serialize_datetime(getattr(space, 'update_time', None)),
                )
            )
        data = [item.model_dump(mode='json') for item in items]
        return {"data": data, "total": len(data)}

    def _copy_shougang_portal_favorite_file(
        self,
        source_file: KnowledgeFile,
        source_space: Knowledge,
        target_space: Knowledge,
        extra_user_metadata: Dict,
    ) -> Optional[KnowledgeFile]:
        loop: Optional[asyncio.AbstractEventLoop] = None
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        try:
            return file_worker.copy_normal(
                source_file,
                source_space,
                target_space,
                self.login_user.user_id,
                extra_user_metadata=extra_user_metadata,
            )
        finally:
            if loop is not None:
                asyncio.set_event_loop(None)
                loop.close()

    async def create_shougang_portal_favorite(
        self,
        req: ShougangPortalFavoriteCreateReq,
    ) -> ShougangPortalFavoriteCreateResp:
        source_space = await KnowledgeDao.aquery_by_id(req.source_space_id)
        target_space = await KnowledgeDao.aquery_by_id(req.target_space_id)
        if not source_space or source_space.type != KnowledgeTypeEnum.SPACE.value:
            raise SpaceNotFoundError()
        if not target_space or target_space.type != KnowledgeTypeEnum.SPACE.value:
            raise SpaceNotFoundError()

        source_file = await KnowledgeFileDao.query_by_id(req.source_file_id)
        source_file = self._ensure_space_file(source_file, req.source_space_id)

        await self._require_permission_id(
            'knowledge_file',
            req.source_file_id,
            'view_file',
            space_id=req.source_space_id,
        )
        if await self._get_space_level(req.target_space_id) != KnowledgeSpaceLevelEnum.PERSONAL:
            raise SpaceInvalidLevelError(msg='Target space must be a personal knowledge space')
        await self._require_permission_id('knowledge_space', req.target_space_id, 'upload_file')

        repeat_file = await KnowledgeFileDao.get_repeat_file(
            req.target_space_id,
            md5_=source_file.md5,
            file_name=source_file.file_name,
        )
        if repeat_file:
            raise SpaceFileDuplicateError()

        extra_user_metadata = {
            'shougang_portal_favorite': {
                'source_space_id': req.source_space_id,
                'source_file_id': req.source_file_id,
            }
        }
        copied_file = await asyncio.to_thread(
            self._copy_shougang_portal_favorite_file,
            source_file,
            source_space,
            target_space,
            extra_user_metadata,
        )
        if not copied_file or not copied_file.id or copied_file.status == KnowledgeFileStatus.FAILED.value:
            raise KnowledgeFileFailedError()

        await self._initialize_child_resource_permissions(
            'knowledge_file',
            int(copied_file.id),
            'knowledge_space',
            req.target_space_id,
        )
        await KnowledgeDao.async_update_knowledge_update_time_by_id(req.target_space_id)

        title = Path(copied_file.file_name or source_file.file_name or '').stem
        return ShougangPortalFavoriteCreateResp(
            file_id=int(copied_file.id),
            space_id=req.target_space_id,
            title=title,
        )

    @staticmethod
    def _enum_value(value) -> str:
        raw = getattr(value, 'value', value)
        return str(raw or '')

    @classmethod
    def _hash_shougang_portal_share_secret(cls, secret: str) -> str:
        normalized = str(secret or '')
        if not normalized:
            return ''
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            'sha256',
            normalized.encode('utf-8'),
            salt.encode('utf-8'),
            cls._SHOUGANG_PORTAL_SHARE_SECRET_ITERATIONS,
        ).hex()
        return (
            f'{cls._SHOUGANG_PORTAL_SHARE_SECRET_ALGORITHM}$'
            f'{cls._SHOUGANG_PORTAL_SHARE_SECRET_ITERATIONS}${salt}${digest}'
        )

    @classmethod
    def _verify_shougang_portal_share_secret(cls, secret: str, secret_hash: str) -> bool:
        if not secret_hash:
            return True
        parts = str(secret_hash).split('$')
        if len(parts) != 4 or parts[0] != cls._SHOUGANG_PORTAL_SHARE_SECRET_ALGORITHM:
            return False
        try:
            iterations = int(parts[1])
        except ValueError:
            return False
        salt = parts[2]
        expected = parts[3]
        actual = hashlib.pbkdf2_hmac(
            'sha256',
            str(secret or '').encode('utf-8'),
            salt.encode('utf-8'),
            iterations,
        ).hex()
        return hmac.compare_digest(actual, expected)

    @staticmethod
    def _generate_shougang_portal_invite_code() -> str:
        alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
        return ''.join(secrets.choice(alphabet) for _ in range(6))

    @staticmethod
    def _is_shougang_portal_share_expired(share_link: ShareLink) -> bool:
        expire_time = int(getattr(share_link, 'expire_time', 0) or 0)
        create_time = getattr(share_link, 'create_time', None)
        if expire_time <= 0 or not create_time:
            return False
        return create_time + timedelta(seconds=expire_time) < datetime.now()

    @staticmethod
    def _shougang_portal_share_permissions(meta_data: Dict) -> ShougangPortalSharePermissions:
        permissions = meta_data.get('permissions') or {}
        return ShougangPortalSharePermissions(
            view=True,
            download=bool(permissions.get('download')),
            upload=False,
        )

    async def _save_shougang_portal_share_link(self, share_link: ShareLink) -> ShareLink:
        async with get_async_db_session() as session:
            repository = ShareLinkRepositoryImpl(session)
            return await repository.save(share_link)

    async def _get_shougang_portal_share_link(self, share_token: str) -> ShareLink:
        async with get_async_db_session() as session:
            repository = ShareLinkRepositoryImpl(session)
            share_link = await repository.find_one(share_token=share_token)
        if not share_link:
            raise NotFoundError()
        return share_link

    def _require_shougang_portal_file_share_link(self, share_link: ShareLink) -> Dict:
        resource_type = self._enum_value(getattr(share_link, 'resource_type', ''))
        if resource_type not in {
            ShareResourceTypeEnum.KNOWLEDGE_SPACE_FILE.value,
            ShareResourceTypeEnum.KNOWLEDGE_SPACE_FILE.name,
        }:
            raise NotFoundError()
        status = self._enum_value(getattr(share_link, 'status', ''))
        if status not in {
            ShareLinkStatusEnum.ACTIVE.value,
            ShareLinkStatusEnum.ACTIVE.name,
        }:
            raise NotFoundError()
        meta_data = getattr(share_link, 'meta_data', None) or {}
        if not isinstance(meta_data, dict):
            raise NotFoundError()
        return meta_data

    async def _resolve_shougang_portal_space_department_id(self, space_id: int) -> int:
        binding = await DepartmentKnowledgeSpaceDao.aget_by_space_id(space_id)
        if binding and getattr(binding, 'department_id', None) is not None:
            return int(binding.department_id)

        scope = await KnowledgeSpaceScopeDao.aget_by_space_id(space_id)
        scope_level = self._enum_value(getattr(scope, 'level', '')) if scope else ''
        if (
            scope
            and scope_level == KnowledgeSpaceLevelEnum.DEPARTMENT.value
            and self._enum_value(getattr(scope, 'owner_type', '')) == KnowledgeSpaceOwnerTypeEnum.DEPARTMENT.value
            and getattr(scope, 'owner_id', None) is not None
        ):
            return int(scope.owner_id)
        return 0

    async def _resolve_shougang_portal_create_share_department_id(self, source_space: Knowledge) -> int:
        space_id = int(source_space.id)
        scope = await KnowledgeSpaceScopeDao.aget_by_space_id(space_id)
        scope_level = self._enum_value(getattr(scope, 'level', '')) if scope else ''
        if scope and scope_level == KnowledgeSpaceLevelEnum.PERSONAL.value:
            return await self._resolve_shougang_portal_current_user_department_id()
        if (
            scope
            and scope_level == KnowledgeSpaceLevelEnum.DEPARTMENT.value
            and self._enum_value(getattr(scope, 'owner_type', '')) == KnowledgeSpaceOwnerTypeEnum.DEPARTMENT.value
            and getattr(scope, 'owner_id', None) is not None
        ):
            return int(scope.owner_id)
        space_department_id = await self._resolve_shougang_portal_space_department_id(space_id)
        if space_department_id:
            return space_department_id
        return await self._resolve_shougang_portal_current_user_department_id()

    async def _resolve_shougang_portal_current_user_department_id(self) -> int:
        login_user_id = self._normalize_shougang_portal_user_id(getattr(self.login_user, 'user_id', None))
        if login_user_id is None:
            return 0
        primary_department = await UserDepartmentDao.aget_user_primary_department(login_user_id)
        if primary_department and getattr(primary_department, 'department_id', None) is not None:
            return int(primary_department.department_id)
        departments = await UserDepartmentDao.aget_user_departments(login_user_id)
        for department in departments or []:
            if getattr(department, 'department_id', None) is not None:
                return int(department.department_id)
        return 0

    @staticmethod
    def _normalize_shougang_portal_user_id(user_id) -> Optional[int]:
        if user_id is None or user_id == '':
            return None
        try:
            return int(user_id)
        except (TypeError, ValueError):
            return None

    async def _require_shougang_portal_share_create_permission(
        self,
        source_space: Knowledge,
        source_file: KnowledgeFile,
    ) -> None:
        try:
            await self._require_permission_id(
                'knowledge_file',
                int(source_file.id),
                'share_file',
                space_id=int(source_space.id),
            )
            return
        except SpacePermissionDeniedError:
            pass

        login_user_id = self._normalize_shougang_portal_user_id(getattr(self.login_user, 'user_id', None))
        if login_user_id is None:
            raise SpacePermissionDeniedError(msg='当前账号没有分享该文档的权限')

        if self._normalize_shougang_portal_user_id(getattr(source_file, 'user_id', None)) == login_user_id:
            return
        if self._normalize_shougang_portal_user_id(getattr(source_space, 'user_id', None)) == login_user_id:
            return

        membership = await SpaceChannelMemberDao.async_find_member(int(source_space.id), login_user_id)
        if (
            membership
            and membership.is_active
            and self._enum_value(membership.user_role) in {UserRoleEnum.CREATOR.value, UserRoleEnum.ADMIN.value}
        ):
            return

        raise SpacePermissionDeniedError(msg='当前账号没有分享该文档的权限')

    async def create_shougang_portal_share_link(
        self,
        req: ShougangPortalShareLinkCreateReq,
    ) -> ShougangPortalShareLinkCreateResp:
        source_space = await KnowledgeDao.aquery_by_id(req.space_id)
        if not source_space or source_space.type != KnowledgeTypeEnum.SPACE.value:
            raise SpaceNotFoundError()

        source_file = await KnowledgeFileDao.query_by_id(req.file_id)
        source_file = self._ensure_space_file(source_file, req.space_id)
        await self._require_shougang_portal_share_create_permission(source_space, source_file)

        share_type = self._enum_value(req.share_type)
        visibility = self._enum_value(req.visibility)
        if share_type not in {item.value for item in ShougangPortalShareType}:
            raise SpacePermissionDeniedError(msg='Invalid share type')
        if visibility not in {item.value for item in ShougangPortalShareVisibility}:
            raise SpacePermissionDeniedError(msg='Invalid share visibility')

        department_id = 0
        if visibility == ShougangPortalShareVisibility.DEPARTMENT.value:
            department_id = await self._resolve_shougang_portal_create_share_department_id(source_space)
            if not department_id:
                raise SpacePermissionDeniedError(
                    msg='当前账号未绑定部门，无法创建仅本部门分享',
                )

        invite_code = (
            self._generate_shougang_portal_invite_code()
            if share_type == ShougangPortalShareType.INVITE_CODE.value
            else ''
        )
        password = str(req.password or '')
        meta_data = {
            'space_id': int(req.space_id),
            'file_id': int(req.file_id),
            'file_name': str(source_file.file_name or ''),
            'share_type': share_type,
            'visibility': visibility,
            'permissions': {
                'view': True,
                'download': bool(req.allow_download),
                'upload': False,
            },
            'password_hash': self._hash_shougang_portal_share_secret(password),
            'invite_code_hash': self._hash_shougang_portal_share_secret(invite_code),
        }
        if department_id:
            meta_data['department_id'] = department_id
        tenant_id = int(getattr(self.login_user, 'tenant_id', 1) or 1)
        share_link = ShareLink(
            share_token=common_util.generate_short_high_entropy_string(),
            resource_id=str(req.file_id),
            resource_type=ShareResourceTypeEnum.KNOWLEDGE_SPACE_FILE,
            share_mode=ShareMode.READ_ONLY,
            expire_time=int(req.expire_seconds or 0),
            meta_data=meta_data,
            create_user_id=str(getattr(self.login_user, 'user_id', '')),
            tenant_id=tenant_id,
        )
        saved = await self._save_shougang_portal_share_link(share_link)
        return ShougangPortalShareLinkCreateResp(
            share_token=saved.share_token,
            link=f'/share/document/{saved.share_token}',
            invite_code=invite_code,
            expire_seconds=int(req.expire_seconds or 0),
        )

    async def get_shougang_portal_share_link_meta(
        self,
        share_token: str,
    ) -> ShougangPortalShareLinkMetaResp:
        share_link = await self._get_shougang_portal_share_link(share_token)
        meta_data = self._require_shougang_portal_file_share_link(share_link)
        share_type = self._enum_value(meta_data.get('share_type')) or ShougangPortalShareType.LINK.value
        visibility = self._enum_value(meta_data.get('visibility')) or ShougangPortalShareVisibility.DEPARTMENT.value
        return ShougangPortalShareLinkMetaResp(
            share_token=share_link.share_token,
            file_name=str(meta_data.get('file_name') or ''),
            share_type=share_type,
            visibility=visibility,
            permissions=self._shougang_portal_share_permissions(meta_data),
            requires_password=bool(meta_data.get('password_hash')),
            requires_invite_code=(
                share_type == ShougangPortalShareType.INVITE_CODE.value
                or bool(meta_data.get('invite_code_hash'))
            ),
            expired=self._is_shougang_portal_share_expired(share_link),
        )

    async def verify_shougang_portal_share_link(
        self,
        share_token: str,
        req: ShougangPortalShareLinkVerifyReq,
    ) -> ShougangPortalShareLinkAccessResp:
        share_link = await self._get_shougang_portal_share_link(share_token)
        meta_data = self._require_shougang_portal_file_share_link(share_link)
        if self._is_shougang_portal_share_expired(share_link):
            raise SpacePermissionDeniedError(msg='Share link has expired')

        password_hash = str(meta_data.get('password_hash') or '')
        if password_hash and not self._verify_shougang_portal_share_secret(req.password, password_hash):
            raise SpacePermissionDeniedError(msg='Invalid share password')

        share_type = self._enum_value(meta_data.get('share_type'))
        invite_code_hash = str(meta_data.get('invite_code_hash') or '')
        if share_type == ShougangPortalShareType.INVITE_CODE.value:
            invite_code = str(req.invite_code or '').strip().upper()
            if not invite_code or not self._verify_shougang_portal_share_secret(invite_code, invite_code_hash):
                raise SpacePermissionDeniedError(msg='Invalid invite code')

        space_id = int(meta_data.get('space_id') or 0)
        file_id = int(meta_data.get('file_id') or 0)
        if not space_id or not file_id:
            raise NotFoundError()

        visibility = self._enum_value(meta_data.get('visibility'))
        if visibility == ShougangPortalShareVisibility.DEPARTMENT.value:
            await self._require_shougang_portal_share_department_access(
                space_id=space_id,
                share_link=share_link,
                meta_data=meta_data,
            )

        permissions = self._shougang_portal_share_permissions(meta_data)
        return ShougangPortalShareLinkAccessResp(
            share_token=share_token,
            space_id=space_id,
            file_id=file_id,
            allow_download=permissions.download,
        )

    async def _require_shougang_portal_share_department_access(
        self,
        *,
        space_id: int,
        share_link: ShareLink,
        meta_data: Dict,
    ) -> None:
        if await self._can_shougang_portal_department_share_access(
            space_id=space_id,
            share_link=share_link,
            meta_data=meta_data,
        ):
            return
        raise SpacePermissionDeniedError(
            msg='Share link is limited to the owning department, sub-departments, reviewers, or creator',
        )

    async def _can_shougang_portal_department_share_access(
        self,
        *,
        space_id: int,
        share_link: ShareLink,
        meta_data: Dict,
    ) -> bool:
        user_id = int(getattr(self.login_user, 'user_id', 0) or 0)
        if not user_id:
            return False

        if str(getattr(share_link, 'create_user_id', '') or '') == str(user_id):
            return True

        department_id = int(meta_data.get('department_id') or 0)
        if not department_id:
            department_id = await self._resolve_shougang_portal_space_department_id(space_id)
        if not department_id:
            return False

        if await self._is_shougang_portal_user_in_department_scope(department_id):
            return True
        if await self._is_shougang_portal_user_department_admin(department_id):
            return True
        if await self._is_shougang_portal_share_reviewer(space_id):
            return True
        return False

    async def _get_shougang_portal_department_scope_ids(self, department_id: int) -> set[int]:
        dept = await DepartmentDao.aget_by_id(department_id)
        if dept and getattr(dept, 'path', None):
            return {int(department_id)} | {int(item) for item in await DepartmentDao.aget_subtree_ids(dept.path)}
        return {int(department_id)}

    async def _is_shougang_portal_user_in_department_scope(self, department_id: int) -> bool:
        allowed_department_ids = await self._get_shougang_portal_department_scope_ids(department_id)
        user_departments = await UserDepartmentDao.aget_user_departments(int(self.login_user.user_id))
        user_department_ids = {int(row.department_id) for row in user_departments}
        return bool(allowed_department_ids & user_department_ids)

    async def _is_shougang_portal_user_department_admin(self, department_id: int) -> bool:
        admin_departments = await DepartmentDao.aget_user_admin_departments(int(self.login_user.user_id))
        if not admin_departments:
            return False

        admin_department_ids = {
            int(row.id)
            for row in admin_departments
            if getattr(row, 'id', None) is not None
        }
        if int(department_id) in admin_department_ids:
            return True

        target_dept = await DepartmentDao.aget_by_id(department_id)
        target_path = str(getattr(target_dept, 'path', '') or '')
        if not target_path:
            return False
        return any(
            bool(getattr(row, 'path', None)) and target_path.startswith(str(row.path))
            for row in admin_departments
        )

    async def _is_shougang_portal_share_reviewer(self, space_id: int) -> bool:
        from bisheng.approval.domain.services.approval_service import ApprovalService

        try:
            reviewer_ids = await ApprovalService.get_department_space_reviewer_user_ids(
                request=self.request,
                login_user=self.login_user,
                space_id=space_id,
                parent_folder_id=None,
            )
        except Exception:
            logger.warning(
                'Failed to resolve shougang portal share reviewers for space_id={}',
                space_id,
            )
            return False
        return int(self.login_user.user_id) in {int(user_id) for user_id in reviewer_ids}

    async def _get_space_level(self, space_id: int) -> KnowledgeSpaceLevelEnum:
        scopes = await KnowledgeSpaceScopeDao.aget_map_by_space_ids([space_id])
        scope = scopes.get(space_id)
        if scope:
            return scope.level
        department_bindings = await DepartmentKnowledgeSpaceDao.aget_by_space_ids([space_id])
        if any(int(binding.space_id) == int(space_id) for binding in department_bindings):
            return KnowledgeSpaceLevelEnum.DEPARTMENT
        return KnowledgeSpaceLevelEnum.PERSONAL

    async def search_shougang_portal_tags(
            self,
            space_ids: List[int],
            space_level: Optional[KnowledgeSpaceLevelEnum],
    ) -> List[str]:
        spaces = await self._get_shougang_portal_visible_search_spaces(space_ids, space_level)
        if not spaces:
            return []
        tag_map = await TagDao.aget_tags_by_business_ids(
            business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE,
            business_ids=[str(space.id) for space in spaces],
        )
        tag_names = {
            str(tag.name)
            for tags in tag_map.values()
            for tag in tags
            if tag.name
        }
        return sorted(tag_names)

    async def get_shougang_portal_home(self, req: ShougangPortalHomeReq) -> Dict:
        spaces = await self._get_shougang_portal_visible_search_spaces(req.space_ids, req.space_level)
        section_tags = list(dict.fromkeys(section.tag for section in req.sections if section.tag))
        empty_sections = {section.tag: [] for section in req.sections}
        if not spaces:
            return {"sections": empty_sections, "tags": []}

        space_ids = [int(space.id) for space in spaces]
        space_name_map = {int(space.id): str(space.name or space.id) for space in spaces}
        tag_map = await TagDao.aget_tags_by_business_ids(
            business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE,
            business_ids=[str(space_id) for space_id in space_ids],
        )
        all_tags = [
            tag
            for tags in tag_map.values()
            for tag in tags
            if tag.id is not None and tag.name
        ]
        hot_tags = list(dict.fromkeys(str(tag.name) for tag in all_tags))[:req.hot_tags_limit]
        if not section_tags:
            return {"sections": empty_sections, "tags": hot_tags}

        section_tag_ids_by_name: Dict[str, List[int]] = {
            tag_name: [
                int(tag.id)
                for tag in all_tags
                if tag.name == tag_name and tag.id is not None
            ]
            for tag_name in section_tags
        }
        section_tag_ids = [
            tag_id
            for tag_ids in section_tag_ids_by_name.values()
            for tag_id in tag_ids
        ]
        if not section_tag_ids:
            return {"sections": empty_sections, "tags": hot_tags}

        links = await TagDao.aget_resources_by_tags(section_tag_ids, ResourceTypeEnum.SPACE_FILE)
        file_ids_by_section: Dict[str, List[int]] = {tag_name: [] for tag_name in section_tags}
        tag_name_by_id = {
            tag_id: tag_name
            for tag_name, tag_ids in section_tag_ids_by_name.items()
            for tag_id in tag_ids
        }
        all_file_ids: List[int] = []
        for link in links:
            tag_name = tag_name_by_id.get(int(link.tag_id))
            resource_id = str(link.resource_id or "")
            if tag_name is None or not resource_id.isdigit():
                continue
            file_id = int(resource_id)
            file_ids_by_section.setdefault(tag_name, []).append(file_id)
            all_file_ids.append(file_id)

        unique_file_ids = list(dict.fromkeys(all_file_ids))
        if not unique_file_ids:
            return {"sections": empty_sections, "tags": hot_tags}

        files = await KnowledgeFileDao.aget_file_by_space_filters(
            knowledge_ids=space_ids,
            status=[KnowledgeFileStatus.SUCCESS.value],
            file_ids=unique_file_ids,
            order_by='update_time',
            order_sort='desc',
        )
        visible_files = await self._filter_shougang_portal_visible_files(files)
        enriched_items = await self._handle_file_folder_extra_info(visible_files)
        item_map: Dict[int, ShougangPortalFileItemResp] = {}
        for item in enriched_items:
            space_id = int(item.get("knowledge_id") or 0)
            item["knowledge_name"] = space_name_map.get(space_id, str(space_id))
            if self._is_shougang_portal_file_item(item, None):
                mapped = self._map_shougang_portal_file_item(space_id, item)
                item_map[mapped.id] = mapped

        sections: Dict[str, List[Dict]] = {}
        for section in req.sections:
            ids = list(dict.fromkeys(file_ids_by_section.get(section.tag, [])))
            items = [item_map[file_id] for file_id in ids if file_id in item_map]
            items = self._sort_shougang_portal_file_items(items, 'updated_at', None)
            sections[section.tag] = [
                item.model_dump(mode='json')
                for item in items[:section.page_size]
            ]
        return {"sections": sections, "tags": hot_tags}

    async def get_shougang_portal_space_infos(self, space_ids: List[int]) -> List[ShougangPortalSpaceInfoItemResp]:
        if not space_ids:
            return []

        unique_space_ids = list(dict.fromkeys(int(space_id) for space_id in space_ids))
        spaces = await KnowledgeDao.async_get_spaces_by_ids(unique_space_ids, order_by='update_time')
        space_map = {
            int(space.id): space
            for space in spaces
            if int(space.type) == KnowledgeTypeEnum.SPACE.value
        }

        permission_results = await asyncio.gather(
            *[
                self._get_effective_permission_ids('knowledge_space', space_id)
                for space_id in space_map
            ],
            return_exceptions=True,
        )
        permission_map = dict(zip(space_map.keys(), permission_results))

        visible_space_ids: List[int] = []
        has_content_permission_map: Dict[int, bool] = {}
        error_map: Dict[int, ShougangPortalSpaceInfoError] = {}
        for space_id in unique_space_ids:
            space = space_map.get(space_id)
            if not space:
                error_map[space_id] = ShougangPortalSpaceInfoError(
                    code=SpaceNotFoundError.Code,
                    message=SpaceNotFoundError.Msg,
                )
                continue
            permission_result = permission_map.get(space_id)
            if isinstance(permission_result, Exception):
                error_map[space_id] = ShougangPortalSpaceInfoError(
                    code=500,
                    message='Failed to get knowledge space info',
                )
                continue
            if 'view_space' in permission_result:
                visible_space_ids.append(space_id)
                has_content_permission_map[space_id] = True
                continue
            if self._is_square_preview_space(space):
                visible_space_ids.append(space_id)
                has_content_permission_map[space_id] = False
                continue
            error_map[space_id] = ShougangPortalSpaceInfoError(
                code=SpacePermissionDeniedError.Code,
                message=SpacePermissionDeniedError.Msg,
            )

        if not visible_space_ids:
            return [
                ShougangPortalSpaceInfoItemResp(
                    id=space_id,
                    data={},
                    error=error_map.get(space_id),
                )
                for space_id in space_ids
            ]

        visible_space_id_strings = [str(space_id) for space_id in visible_space_ids]
        creator_ids = list({
            int(space_map[space_id].user_id)
            for space_id in visible_space_ids
            if space_map[space_id].user_id != self.login_user.user_id
        })
        file_count_task = KnowledgeFileDao.async_count_success_files_batch(visible_space_ids)
        follower_count_task = SpaceChannelMemberDao.async_count_members_batch(visible_space_id_strings)
        membership_task = SpaceChannelMemberDao.async_get_all_members_for_spaces(
            self.login_user.user_id,
            visible_space_id_strings,
        )
        creator_task = UserDao.aget_user_by_ids(creator_ids) if creator_ids else None
        if creator_task:
            file_count_map, follower_count_map, memberships, creators = await asyncio.gather(
                file_count_task,
                follower_count_task,
                membership_task,
                creator_task,
            )
        else:
            file_count_map, follower_count_map, memberships = await asyncio.gather(
                file_count_task,
                follower_count_task,
                membership_task,
            )
            creators = []

        creator_map = {int(user.user_id): user for user in (creators or [])}
        member_map = {
            int(member.business_id): member
            for member in (memberships or [])
            if str(member.business_id).isdigit()
        }
        is_global_admin = False
        is_admin = getattr(self.login_user, 'is_admin', None)
        if callable(is_admin):
            is_global_admin = bool(is_admin())

        permission_level_space_ids = [
            space_id
            for space_id in visible_space_ids
            if space_map[space_id].user_id != self.login_user.user_id
            and not (
                member_map.get(space_id)
                and member_map[space_id].is_active
            )
            and has_content_permission_map.get(space_id)
        ]
        permission_levels: Dict[int, Optional[str]] = {}
        if permission_level_space_ids:
            levels = await asyncio.gather(*[
                PermissionService.get_permission_level(
                    user_id=self.login_user.user_id,
                    object_type='knowledge_space',
                    object_id=str(space_id),
                    login_user=self.login_user,
                )
                for space_id in permission_level_space_ids
            ])
            permission_levels = {
                space_id: level
                for space_id, level in zip(permission_level_space_ids, levels)
            }

        result_map: Dict[int, KnowledgeSpaceInfoResp] = {}
        can_unsubscribe_tasks = []
        for space_id in visible_space_ids:
            space = space_map[space_id]
            result = KnowledgeSpaceInfoResp(**space.model_dump())
            member_info = None
            if space.user_id != self.login_user.user_id:
                create_user = creator_map.get(int(space.user_id))
                result.user_name = create_user.user_name if create_user else str(space.user_id)
            else:
                result.user_name = self.login_user.user_name

            if space.user_id == self.login_user.user_id:
                result.user_role = UserRoleEnum.CREATOR
                self._apply_subscription_flags(result, SpaceSubscriptionStatusEnum.SUBSCRIBED)
            else:
                member_info = member_map.get(space_id)
                if member_info:
                    self._apply_subscription_flags(result, self._resolve_subscription_status(member_info))
                    if member_info.is_active:
                        result.user_role = member_info.user_role
                elif has_content_permission_map.get(space_id) and not is_global_admin:
                    self._apply_subscription_flags(result, SpaceSubscriptionStatusEnum.SUBSCRIBED)
                if result.user_role is None and has_content_permission_map.get(space_id):
                    result.user_role = self._permission_level_to_space_user_role(permission_levels.get(space_id))
                    if result.user_role is not None and not is_global_admin:
                        self._apply_subscription_flags(result, SpaceSubscriptionStatusEnum.SUBSCRIBED)
                if result.user_role is None and has_content_permission_map.get(space_id):
                    result.user_role = UserRoleEnum.MEMBER

            result.follower_num = int(follower_count_map.get(str(space_id), 0) or 0)
            result.file_num = int(file_count_map.get(space_id, 0) or 0)
            result_map[space_id] = result
            can_unsubscribe_tasks.append((space_id, self._can_unsubscribe_space(space, member_info)))

        can_unsubscribe_results = await asyncio.gather(
            *[task for _, task in can_unsubscribe_tasks],
            return_exceptions=True,
        )
        for (space_id, _), can_unsubscribe in zip(can_unsubscribe_tasks, can_unsubscribe_results):
            result_map[space_id].can_unsubscribe = (
                False if isinstance(can_unsubscribe, Exception) else bool(can_unsubscribe)
            )

        await self._decorate_department_metadata(list(result_map.values()))

        items: List[ShougangPortalSpaceInfoItemResp] = []
        for space_id in space_ids:
            result = result_map.get(space_id)
            if result:
                items.append(
                    ShougangPortalSpaceInfoItemResp(
                        id=space_id,
                        data=result.model_dump(mode='json'),
                        error=None,
                    )
                )
            else:
                items.append(
                    ShougangPortalSpaceInfoItemResp(
                        id=space_id,
                        data={},
                        error=error_map.get(space_id),
                    )
                )
        return items

    async def search_shougang_portal_files(self, req: ShougangPortalFileSearchReq) -> Dict:
        spaces = await self._get_shougang_portal_visible_search_spaces(req.space_ids, req.space_level)
        if not spaces:
            return {"data": [], "total": 0, "page": req.page, "page_size": req.page_size}

        space_ids = [int(space.id) for space in spaces]
        tag_file_ids = await self._get_shougang_portal_tag_file_ids(space_ids, req.tag)
        if req.tag and not tag_file_ids:
            return {"data": [], "total": 0, "page": req.page, "page_size": req.page_size}

        keyword_file_ids = await self._get_shougang_portal_keyword_file_ids(
            spaces=spaces,
            keyword=req.q,
            filter_file_ids=tag_file_ids,
        )
        files = await KnowledgeFileDao.aget_file_by_space_filters(
            knowledge_ids=space_ids,
            file_name=req.q,
            status=[KnowledgeFileStatus.SUCCESS.value],
            file_ids=tag_file_ids,
            extra_file_ids=keyword_file_ids,
            file_ext=req.file_ext,
            order_by='update_time',
            order_sort='desc',
        )
        if not files:
            return {"data": [], "total": 0, "page": req.page, "page_size": req.page_size}

        visible_files = await self._filter_shougang_portal_visible_files(files)
        if not visible_files:
            return {"data": [], "total": 0, "page": req.page, "page_size": req.page_size}

        space_name_map = {int(space.id): str(space.name or space.id) for space in spaces}
        enriched_items = await self._handle_file_folder_extra_info(visible_files)
        all_items: List[ShougangPortalFileItemResp] = []
        for item in enriched_items:
            space_id = int(item.get("knowledge_id") or 0)
            item["knowledge_name"] = space_name_map.get(space_id, str(space_id))
            if self._is_shougang_portal_file_item(item, req.file_ext):
                all_items.append(self._map_shougang_portal_file_item(space_id, item))

        sorted_items = self._sort_shougang_portal_file_items(all_items, req.sort, req.q)
        start = (req.page - 1) * req.page_size
        end = start + req.page_size
        return {
            "data": [item.model_dump(mode='json') for item in sorted_items[start:end]],
            "total": len(sorted_items),
            "page": req.page,
            "page_size": req.page_size,
        }

    async def _get_shougang_portal_visible_search_spaces(
            self,
            requested_space_ids: List[int],
            space_level: Optional[KnowledgeSpaceLevelEnum],
    ) -> List[Knowledge]:
        space_ids = await self._resolve_shougang_portal_search_space_ids(requested_space_ids, space_level)
        if not space_ids:
            return []
        spaces = await KnowledgeDao.async_get_spaces_by_ids(space_ids, order_by='update_time')
        space_map = {
            int(space.id): space
            for space in spaces
            if int(space.type) == KnowledgeTypeEnum.SPACE.value
        }
        ordered_spaces = [space_map[space_id] for space_id in space_ids if space_id in space_map]
        if not ordered_spaces:
            return []

        is_global_admin = False
        is_admin = getattr(self.login_user, 'is_admin', None)
        if callable(is_admin):
            is_global_admin = bool(is_admin())

        visible_spaces: List[Knowledge] = []
        permission_checks = []
        permission_spaces: List[Knowledge] = []
        for space in ordered_spaces:
            if is_global_admin or int(space.user_id or 0) == int(self.login_user.user_id) or self._is_square_preview_space(space):
                visible_spaces.append(space)
                continue
            permission_spaces.append(space)
            permission_checks.append(self._get_effective_permission_ids('knowledge_space', int(space.id)))

        if permission_checks:
            permission_results = await asyncio.gather(*permission_checks, return_exceptions=True)
            for space, permission_result in zip(permission_spaces, permission_results):
                if isinstance(permission_result, Exception):
                    logger.warning(
                        "skip shougang portal space search permission check: space_id={} error={}",
                        space.id,
                        permission_result,
                    )
                    continue
                if 'view_space' in permission_result:
                    visible_spaces.append(space)
        visible_space_ids = {int(space.id) for space in visible_spaces}
        return [space for space in ordered_spaces if int(space.id) in visible_space_ids]

    async def _resolve_shougang_portal_search_space_ids(
        self,
        requested_space_ids: List[int],
        space_level: Optional[KnowledgeSpaceLevelEnum],
    ) -> List[int]:
        unique_space_ids = list(dict.fromkeys(int(space_id) for space_id in requested_space_ids if int(space_id) > 0))
        if not unique_space_ids:
            return []
        if space_level is None:
            return unique_space_ids
        scopes = await KnowledgeSpaceScopeDao.aget_map_by_space_ids(unique_space_ids)
        department_bindings = await DepartmentKnowledgeSpaceDao.aget_by_space_ids(unique_space_ids)
        department_space_ids = {int(binding.space_id) for binding in department_bindings}
        result = []
        for space_id in unique_space_ids:
            scope = scopes.get(space_id)
            resolved_level = scope.level if scope else (
                KnowledgeSpaceLevelEnum.DEPARTMENT
                if space_id in department_space_ids
                else KnowledgeSpaceLevelEnum.PERSONAL
            )
            if resolved_level == space_level:
                result.append(space_id)
        return result

    async def _get_shougang_portal_tag_file_ids(self, space_ids: List[int], tag_name: Optional[str]) -> Optional[List[int]]:
        if not tag_name:
            return None
        tag_map = await TagDao.aget_tags_by_business_ids(
            business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE,
            business_ids=[str(space_id) for space_id in space_ids],
            name=tag_name,
        )
        tag_ids = [
            int(tag.id)
            for tags in tag_map.values()
            for tag in tags
            if tag.id is not None
        ]
        if not tag_ids:
            return []
        resources = await TagDao.aget_resources_by_tags(tag_ids, ResourceTypeEnum.SPACE_FILE)
        file_ids: List[int] = []
        for resource in resources:
            resource_id = str(resource.resource_id or "")
            if resource_id.isdigit():
                file_ids.append(int(resource_id))
        return list(dict.fromkeys(file_ids))

    async def _get_shougang_portal_keyword_file_ids(
            self,
            *,
            spaces: List[Knowledge],
            keyword: Optional[str],
            filter_file_ids: Optional[List[int]],
    ) -> List[int]:
        if not keyword:
            return []
        index_names = [str(space.index_name) for space in spaces if space.index_name]
        if not index_names:
            return []
        query: Dict = {"match_phrase": {"text": keyword}}
        if filter_file_ids:
            query = {
                "bool": {
                    "must": [
                        query,
                        {"terms": {"metadata.document_id": filter_file_ids}},
                    ]
                }
            }
        try:
            es_vector = await KnowledgeRag.init_knowledge_es_vectorstore(knowledge=spaces[0])
            es_result = await es_vector.client.search(index=index_names, body={
                "query": query,
                "aggs": {
                    "document_ids": {
                        "terms": {
                            "field": "metadata.document_id",
                            "size": 10000,
                        }
                    }
                },
                "size": 0,
            })
        except Exception as exc:
            logger.warning("skip shougang portal batch es search: error={}", exc)
            return []

        aggregations = es_result.get("aggregations") or {}
        buckets = aggregations.get("document_ids", {}).get("buckets", [])
        file_ids = [int(one["key"]) for one in buckets if str(one.get("key", "")).isdigit()]
        if filter_file_ids:
            allowed = set(filter_file_ids)
            file_ids = [file_id for file_id in file_ids if file_id in allowed]
        return file_ids

    async def _filter_shougang_portal_visible_files(self, files: List[KnowledgeFile]) -> List[KnowledgeFile]:
        grouped_files: Dict[int, List[KnowledgeFile]] = {}
        for file in files:
            grouped_files.setdefault(int(file.knowledge_id), []).append(file)

        visible_files: List[KnowledgeFile] = []
        for space_id, items in grouped_files.items():
            try:
                visible_files.extend(await self._filter_visible_child_items(items, space_id=space_id))
            except Exception as exc:
                logger.warning("skip shougang portal file visibility check: space_id={} error={}", space_id, exc)
        return visible_files

    async def _get_shougang_portal_tag_ids(self, space_id: int, tag_name: Optional[str]) -> Optional[List[int]]:
        if not tag_name:
            return None
        tags = await TagDao.get_tags_by_business(
            business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE,
            business_id=str(space_id),
            name=tag_name,
        )
        return [int(tag.id) for tag in tags if tag.id is not None]

    def _is_shougang_portal_file_item(self, item: Dict, file_ext: Optional[str]) -> bool:
        if int(item.get("file_type", -1)) != FileType.FILE.value:
            return False
        file_name = str(item.get("file_name") or "")
        if file_ext and self._get_file_ext(file_name) != file_ext.strip().lower().lstrip("."):
            return False
        return True

    def _map_shougang_portal_file_item(self, space_id: int, item: Dict) -> ShougangPortalFileItemResp:
        file_name = str(item.get("file_name") or "")
        return ShougangPortalFileItemResp(
            id=int(item.get("id") or 0),
            space_id=space_id,
            title=Path(file_name).stem or file_name,
            summary=str(item.get("abstract") or ""),
            source=str(item.get("knowledge_name") or item.get("space_name") or space_id),
            updated_at=self._serialize_datetime(item.get("update_time")),
            tags=[str(tag.get("name")) for tag in item.get("tags") or [] if isinstance(tag, dict) and tag.get("name")],
            file_ext=self._get_file_ext(file_name),
            file_size=str(item.get("file_size") or ""),
            file_encoding=str(
                item.get("file_encoding")
                or item.get("fileEncoding")
                or item.get("document_code")
                or item.get("file_no")
                or ""
            ),
        )

    @staticmethod
    def _get_file_ext(file_name: str) -> str:
        suffix = Path(file_name).suffix.lower()
        return suffix[1:] if suffix.startswith(".") else suffix

    @staticmethod
    def _serialize_datetime(value) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, str):
            return value
        return ""

    @staticmethod
    def _sort_shougang_portal_file_items(
        items: List[ShougangPortalFileItemResp],
        sort: str,
        keyword: Optional[str],
    ) -> List[ShougangPortalFileItemResp]:
        if sort == 'updated_at' or not keyword:
            return sorted(items, key=lambda item: item.updated_at, reverse=True)
        keyword_lower = keyword.lower()

        def score(item: ShougangPortalFileItemResp) -> tuple[int, str]:
            title = item.title.lower()
            summary = item.summary.lower()
            tags = [tag.lower() for tag in item.tags]
            hit_score = 0
            if title == keyword_lower:
                hit_score += 4
            if keyword_lower in title:
                hit_score += 3
            if keyword_lower in summary:
                hit_score += 2
            if any(keyword_lower in tag for tag in tags):
                hit_score += 1
            return hit_score, item.updated_at

        return sorted(items, key=score, reverse=True)

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
        await KnowledgeSpaceContentStat.enqueue_space_delete_stat_async(space_id)

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
        name_changed = name is not None and name != space.name

        if name_changed:
            scope = await KnowledgeSpaceScopeDao.aget_by_space_id(space_id)
            if scope is None:
                raise SpaceInvalidScopeOwnerError(msg='Knowledge space scope does not exist')
            await self._ensure_space_name_unique_in_scope(
                name=name,
                level=scope.level,
                owner_type=scope.owner_type,
                owner_id=int(scope.owner_id),
                exclude_id=space_id,
                tenant_id=int(scope.tenant_id or space.tenant_id or self.login_user.tenant_id),
            )
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
        if name_changed:
            await KnowledgeSpaceContentStat.enqueue_space_rename_stat_async(space_id)
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
            can_unsubscribe = await self._can_unsubscribe_space(one, member_conf)

            if member_conf.is_pinned:
                pinned_spaces.append(
                    KnowledgeSpaceInfoResp(
                        **one.model_dump(),
                        is_pinned=True,
                        user_role=member_conf.user_role,
                        subscription_status=SpaceSubscriptionStatusEnum.SUBSCRIBED,
                        is_followed=True,
                        can_unsubscribe=can_unsubscribe,
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
                        can_unsubscribe=can_unsubscribe,
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

    async def get_grouped_spaces(
        self,
        order_by: str = 'update_time',
    ) -> GroupedKnowledgeSpacesResp:
        members = await SpaceChannelMemberDao.async_get_user_space_members(self.login_user.user_id)
        space_ids = {
            int(member.business_id)
            for member in members
            if str(member.business_id).isdigit()
        }
        created_ids, accessible_ids = await asyncio.gather(
            KnowledgeDao.aget_knowledge_ids_created_by(
                self.login_user.user_id,
                KnowledgeTypeEnum.SPACE,
            ),
            PermissionService.list_accessible_ids(
                user_id=self.login_user.user_id,
                relation='can_read',
                object_type='knowledge_space',
                login_user=self.login_user,
            ),
        )
        space_ids.update(int(space_id) for space_id in created_ids)
        if accessible_ids is None:
            all_space_ids = await KnowledgeDao.aget_knowledge_ids_by_type(KnowledgeTypeEnum.SPACE)
            space_ids.update(all_space_ids)
        else:
            space_ids.update(int(space_id) for space_id in accessible_ids if str(space_id).isdigit())

        spaces = await self._format_accessible_spaces(
            list(space_ids),
            order_by,
            memberships=members,
            required_permission_id='view_space',
        )
        grouped = GroupedKnowledgeSpacesResp()
        for space in spaces:
            if space.space_level == KnowledgeSpaceLevelEnum.PUBLIC:
                grouped.public_spaces.append(space)
            elif space.space_level == KnowledgeSpaceLevelEnum.DEPARTMENT:
                grouped.department_spaces.append(space)
            elif space.space_level == KnowledgeSpaceLevelEnum.TEAM:
                grouped.team_spaces.append(space)
            else:
                grouped.personal_spaces.append(space)
        return grouped

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
        square_members = await SpaceChannelMemberDao.async_get_all_members_for_spaces(
            self.login_user.user_id,
            [str(space_id) for space_id in space_ids_int],
        )
        square_member_map = {
            int(member.business_id): member
            for member in square_members
            if str(member.business_id).isdigit()
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

        is_global_admin = False
        is_admin = getattr(self.login_user, 'is_admin', None)
        if callable(is_admin):
            is_global_admin = bool(is_admin())

        permission_level_map: Dict[int, Optional[str]] = {}
        permission_probe_ids = [
            row[0].id
            for row in rows
            if row[0].user_id != self.login_user.user_id
            and self._resolve_subscription_status_from_fields(row[1], row[2])
            != SpaceSubscriptionStatusEnum.SUBSCRIBED
        ]
        if permission_probe_ids and not is_global_admin:
            permission_levels = await asyncio.gather(*[
                PermissionService.get_permission_level(
                    user_id=self.login_user.user_id,
                    object_type='knowledge_space',
                    object_id=str(space_id),
                    login_user=self.login_user,
                )
                for space_id in permission_probe_ids
            ])
            permission_level_map = {
                space_id: level
                for space_id, level in zip(permission_probe_ids, permission_levels)
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
            user_role = None
            permission_level = permission_level_map.get(space.id)
            if permission_level:
                user_role = self._permission_level_to_space_user_role(permission_level)
                if user_role is not None:
                    subscription_status = SpaceSubscriptionStatusEnum.SUBSCRIBED
            if space.id in readable_space_with_view_permission:
                subscription_status = SpaceSubscriptionStatusEnum.SUBSCRIBED
            member_info = square_member_map.get(int(space.id))

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
                        "user_role": user_role,
                        "can_unsubscribe": await self._can_unsubscribe_space(space, member_info),
                    }
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

                in_progress_statuses = {
                    KnowledgeFileStatus.PROCESSING.value,
                    KnowledgeFileStatus.WAITING.value,
                    KnowledgeFileStatus.REBUILDING.value,
                }
                async with get_async_db_session() as session:
                    rows = (await session.exec(stmt)).all()
                    total = sum(r[1] for r in rows)
                    success = sum(
                        r[1] for r in rows if r[0] == KnowledgeFileStatus.SUCCESS.value
                    )
                    processing = sum(
                        r[1] for r in rows if r[0] in in_progress_statuses
                    )
                    folder_counts[folder.id] = {
                        "file_num": total,
                        "success_file_num": success,
                        "processing_file_num": processing,
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
                    one.id,
                    {"file_num": 0, "success_file_num": 0, "processing_file_num": 0},
                )
                item.update(counts)
                item["summary"] = ""
            else:
                item["thumbnails"] = self.get_logo_share_link(one.thumbnails)
                item["tags"] = file_tags.get(one.id, [])
                item["summary"] = one.abstract or ""
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

        expanded_file_ids = (
            await self._cascade_version_links_on_delete(file_ids) if file_ids else []
        )
        if expanded_file_ids:
            delete_knowledge_file_celery.delay(
                file_ids=expanded_file_ids,
                knowledge_id=folder.knowledge_id,
                clear_minio=True,
            )
            # Sibling files pulled in via primary-of-multi-version expansion
            # also need their tuples cleaned up.
            for sibling_id in set(expanded_file_ids) - set(file_ids):
                resource_tuples_to_cleanup.append(("knowledge_file", sibling_id))

        await self.update_folder_update_time(folder.file_level_path)
        await self._cleanup_resource_tuples(resource_tuples_to_cleanup)

        await KnowledgeFileDao.adelete_batch(expanded_file_ids + floder_ids)
        if expanded_file_ids:
            await KnowledgeSpaceContentStat.enqueue_file_stat_async(expanded_file_ids)

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
            # Most rollback paths fire before the V1 doc/version rows are
            # written, so the cascade is a defensive no-op here. Kept for the
            # case where a partial create leaves stale chain rows.
            expanded_ids = await self._cascade_version_links_on_delete(created_file_ids)
            try:
                await self._cleanup_resource_tuples(
                    [
                        ("knowledge_file", created_file_id)
                        for created_file_id in expanded_ids
                    ]
                )
            finally:
                await KnowledgeFileDao.adelete_batch(expanded_ids)

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
        await KnowledgeSpaceContentStat.enqueue_file_stat_async([file_id])

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

    async def _cascade_version_links_on_delete(
        self, file_ids: List[int]
    ) -> List[int]:
        """Resolve version-chain cleanup before hard-deleting KnowledgeFile rows.

        Product spec (2026-05-23):
          • non-primary version in a multi-version chain → drop only that row
          • primary version OR sole V1 → drop the whole chain (every version,
            every sibling file, and the document anchor)
          • file with no version row (legacy / pre-version-mgmt) → untouched

        Returns the union of input file_ids and any sibling file_ids picked up
        via primary-of-multi-version expansion, so the caller can run the same
        tuple / index / minio cleanup against them in one shot.

        No-op (returns input as-is) when the repos are not injected — keeps the
        flow safe for any code path that constructs the service without the
        version DI wiring.
        """
        if not self.version_repo or not self.doc_repo or not file_ids:
            return list(file_ids)

        pending_per_doc: Dict[int, list] = {}
        for fid in file_ids:
            v = await self.version_repo.find_by_knowledge_file_id(fid)
            if v is None:
                continue
            pending_per_doc.setdefault(v.document_id, []).append(v)

        expanded: set[int] = set(file_ids)
        versions_to_delete: List[int] = []
        documents_to_delete: List[int] = []

        for doc_id, pending_versions in pending_per_doc.items():
            chain = await self.version_repo.find_by_document_id(doc_id)
            pending_ids = {v.id for v in pending_versions}
            primary_in_pending = any(v.is_primary for v in pending_versions)
            all_in_chain_pending = len(chain) == len(pending_ids)

            if primary_in_pending or all_in_chain_pending:
                for v in chain:
                    versions_to_delete.append(v.id)
                    expanded.add(v.knowledge_file_id)
                documents_to_delete.append(doc_id)
            else:
                for v in pending_versions:
                    versions_to_delete.append(v.id)

        for vid in versions_to_delete:
            await self.version_repo.delete(vid)
        for did in documents_to_delete:
            # Clear the pointer before deleting the anchor — defensive against
            # any future FK constraint that might be added to primary_version_id.
            await self.doc_repo.update_primary_version_id(did, None)
            await self.doc_repo.delete(did)

        return list(expanded)

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

        expanded_ids = await self._cascade_version_links_on_delete([file_id])
        await KnowledgeFileDao.adelete_batch(expanded_ids)
        if expanded_ids:
            await KnowledgeSpaceContentStat.enqueue_file_stat_async(expanded_ids)
        delete_knowledge_file_celery.delay(
            file_ids=expanded_ids,
            knowledge_id=file_record.knowledge_id,
            clear_minio=True,
        )
        await self._cleanup_resource_tuples(
            [("knowledge_file", fid) for fid in expanded_ids]
        )
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
        asyncio.create_task(self._log_file_preview_success(file_record))

        return {
            "original_url": original_url,
            "preview_url": preview_url,
        }

    async def _log_file_preview_success(self, file_record: KnowledgeFile) -> None:
        try:
            from bisheng.telemetry.domain.mid_table.knowledge_space_content import KnowledgeSpaceContentStat

            space = await KnowledgeDao.aquery_by_id(file_record.knowledge_id)
            if (
                not space
                or space.type != KnowledgeTypeEnum.SPACE.value
                or file_record.status != KnowledgeFileStatus.SUCCESS.value
            ):
                return
            await KnowledgeSpaceContentStat.log_preview_success(
                file_record=file_record,
                space=space,
                viewer_user_id=self.login_user.user_id,
                viewer_user_name=self.login_user.user_name,
            )
        except Exception:
            logger.exception("Failed to log knowledge space file preview telemetry.")

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
        if tmp:
            await KnowledgeSpaceContentStat.enqueue_file_stat_async([one.id for one in tmp])

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
            await KnowledgeSpaceContentStat.enqueue_file_stat_async(all_file_ids)
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
            expanded_file_ids = await self._cascade_version_links_on_delete(direct_file_ids)
            await KnowledgeFileDao.adelete_batch(expanded_file_ids)
            if expanded_file_ids:
                await KnowledgeSpaceContentStat.enqueue_file_stat_async(expanded_file_ids)
            delete_knowledge_file_celery.delay(
                file_ids=expanded_file_ids,
                knowledge_id=knowledge.id,
                clear_minio=True,
            )
            await self._cleanup_resource_tuples(
                [("knowledge_file", file_id) for file_id in expanded_file_ids]
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
            primary_dept = await UserDepartmentDao.aget_user_primary_department(self.login_user.user_id)
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
                    applicant_department_id=primary_dept.department_id if primary_dept else None,
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
            if gate_result.decision == ApprovalGateDecision.PENDING and gate_result.task_ids and self.message_service:
                await self._send_space_approval_notification(
                    space=space,
                    instance_id=gate_result.instance_id,
                    task_ids=gate_result.task_ids,
                )
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

    async def _send_space_approval_notification(
        self,
        *,
        space: Knowledge,
        instance_id: int,
        task_ids: list[int],
    ) -> None:
        from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
        approver_user_ids: list[int] = []
        seen: set[int] = set()
        for task_id in task_ids:
            task = await ApprovalInstanceRepository.get_task(task_id)
            if task and task.approver_user_id not in seen:
                seen.add(task.approver_user_id)
                approver_user_ids.append(task.approver_user_id)
        if not approver_user_ids:
            return
        await self.message_service.send_generic_approval(
            applicant_user_id=self.login_user.user_id,
            applicant_user_name=self.login_user.user_name,
            action_code="request_knowledge_space",
            business_type="approval_instance_id",
            business_id=str(instance_id),
            business_name=space.name,
            button_action_code="request_knowledge_space",
            receiver_user_ids=approver_user_ids,
        )

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
        if not await self._can_unsubscribe_space(space, current_membership):
            raise SpacePermissionDeniedError()

        await self._revoke_direct_space_user_permissions(
            space_id, self.login_user.user_id
        )
        deleted = await SpaceChannelMemberDao.delete_space_member(
            space_id, self.login_user.user_id
        )
        return deleted
