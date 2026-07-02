import asyncio
import contextvars
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import Request
from langchain_core.documents import Document
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import func, update
from sqlmodel import select

from bisheng.api.v1.schemas import ExcelRule, FileProcessBase, KnowledgeFileOne
from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateDecision, ApprovalGateRequest
from bisheng.approval.domain.services.approval_gate import ApprovalGate
from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.approval.domain.services.knowledge_space_subscribe_scenario_handler import (
    KnowledgeSpaceSubscribeScenarioHandler,
)
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum, BaseTelemetryTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.common.errcode.knowledge import KnowledgeSpaceTagLibraryInvalidError
from bisheng.common.errcode.knowledge_space import (
    FavoriteSpaceProtectedError,
    SpaceBusinessDomainCodeInvalidError,
    SpaceCreateDepartmentDeniedError,
    SpaceCreatePublicDeniedError,
    SpaceFileDuplicateError,
    SpaceFileEncodingDuplicateError,
    SpaceFileExtensionError,
    SpaceFileNameDuplicateError,
    SpaceFileNameSensitiveWordError,
    SpaceFileNotFoundError,
    SpaceFileSizeLimitError,
    SpaceFolderCircularMoveError,
    SpaceFolderDepthError,
    SpaceFolderDuplicateError,
    SpaceFolderNotFoundError,
    SpaceInvalidLevelError,
    SpaceInvalidScopeOwnerError,
    SpaceLimitError,
    SpaceNameDuplicateError,
    SpaceNameSensitiveWordError,
    SpaceNotFoundError,
    SpacePermissionDeniedError,
    SpaceSubscribeLimitError,
    SpaceSubscribePrivateError,
    SpaceTenantMismatchError,
)
from bisheng.common.errcode.llm import WorkbenchEmbeddingError
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    SpaceChannelMemberDao,
    UserRoleEnum,
)
from bisheng.common.schemas.api import PageData, PageInfiniteCursorData
from bisheng.common.schemas.telemetry.event_data_schema import PortalDocumentReadEventData
from bisheng.common.telemetry.portal_event_service import (
    PORTAL_BFF_TELEMETRY_SOURCE_HEADER,
    PortalTelemetryEventService,
    is_portal_bff_proxy_source,
)
from bisheng.common.utils import util as common_util
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.core.openfga.client import (
    begin_fga_read_stats,
    finish_fga_read_stats,
)
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.database.models.department import DepartmentDao, UserDepartment, UserDepartmentDao
from bisheng.database.models.group import GroupDao
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.review_tags import ReviewTag, ReviewTagDao
from bisheng.database.models.tag import Tag, TagBusinessTypeEnum, TagDao, TagResourceTypeEnum
from bisheng.database.models.tenant import TenantDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.knowledge.domain.constants import normalize_business_domain_code
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.department_knowledge_space import (
    DepartmentKnowledgeSpaceDao,
)
from bisheng.knowledge.domain.models.knowledge import (
    AuthTypeEnum,
    Knowledge,
    KnowledgeDao,
    KnowledgeRead,
    KnowledgeState,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import (
    KnowledgeDocumentVersion,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    FileSource,
    FileType,
    KnowledgeFile,
    KnowledgeFileDao,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.models.knowledge_space_file import SpaceFileDao
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceOwnerTypeEnum,
    KnowledgeSpaceScope,
    KnowledgeSpaceScopeDao,
)
from bisheng.knowledge.domain.models.knowledge_space_tag_library import (
    KnowledgeSpaceTagLibraryDao,
)
from bisheng.knowledge.domain.models.knowledge_tag_library_link import KnowledgeTagLibraryLinkDao
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    GroupedKnowledgeSpacesResp,
    KnowledgeSpaceCreateOptionDepartment,
    KnowledgeSpaceCreateOptionDepartmentsResp,
    KnowledgeSpaceCreateOptionsResp,
    KnowledgeSpaceCreateOptionUserGroup,
    KnowledgeSpaceCreateOptionUserGroupsResp,
    KnowledgeSpaceFileResponse,
    KnowledgeSpaceInfoResp,
    RemoveSpaceMemberRequest,
    ShougangPortalFavoriteCreateReq,
    ShougangPortalFavoriteCreateResp,
    ShougangPortalFavoriteFileItem,
    ShougangPortalFavoriteFilesResp,
    ShougangPortalFavoriteRemoveReq,
    ShougangPortalFavoriteRemoveResp,
    ShougangPortalFavoriteStatusReq,
    ShougangPortalFavoriteStatusResp,
    ShougangPortalFavoriteStatusResultItem,
    ShougangPortalFileItemResp,
    ShougangPortalFileSearchReq,
    ShougangPortalHomeReq,
    ShougangPortalPersonalSpaceItemResp,
    ShougangPortalQaFileSearchReq,
    ShougangPortalShareLinkAccessResp,
    ShougangPortalShareLinkCreateReq,
    ShougangPortalShareLinkCreateResp,
    ShougangPortalShareLinkMetaResp,
    ShougangPortalShareLinkVerifyReq,
    ShougangPortalSharePermissions,
    ShougangPortalShareType,
    ShougangPortalShareVisibility,
    ShougangPortalSpaceBusinessDomainCodesSyncReq,
    ShougangPortalSpaceInfoError,
    ShougangPortalSpaceInfoItemResp,
    ShougangPortalUploadedFileResp,
    SpaceMemberPageResponse,
    SpaceMemberResponse,
    SpaceSubscriptionStatusEnum,
    UpdateSpaceMemberRoleRequest,
    UploadFolderRecommendationItemResp,
    UploadFolderRecommendationResp,
    UploadFolderRecommendFileReq,
)
from bisheng.knowledge.domain.services.knowledge_audit_telemetry_service import (
    KnowledgeAuditTelemetryService,
)
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.domain.services.knowledge_space_tag_library_service import (
    KnowledgeSpaceTagLibraryService,
)
from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils
from bisheng.knowledge.domain.services.tag_library_tag_service import TagLibraryTagService
from bisheng.knowledge.domain.services.web_link_import_service import (
    KnowledgeWebLinkImportService,
    WebLinkImportResult,
)
from bisheng.llm.domain import LLMService
from bisheng.message.domain.services.notification_content import build_notify_content
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
from bisheng.sensitive_word.domain.schemas import SensitiveWordBusinessType
from bisheng.sensitive_word.domain.services.sensitive_word_policy_service import SensitiveWordPolicyService
from bisheng.share_link.domain.models.share_link import (
    ResourceTypeEnum as ShareResourceTypeEnum,
)
from bisheng.share_link.domain.models.share_link import (
    ShareLink,
    ShareLinkStatusEnum,
    ShareMode,
)
from bisheng.share_link.domain.repositories.implementations.share_link_repository_impl import ShareLinkRepositoryImpl
from bisheng.telemetry.domain.mid_table.knowledge_space_content import KnowledgeSpaceContentStat
from bisheng.user.domain.models.user import UserDao
from bisheng.utils import generate_uuid, get_request_ip
from bisheng.worker.knowledge import file_worker
from bisheng.workstation.domain.services.workstation_service import WorkStationService

if TYPE_CHECKING:
    from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_repository import (
        KnowledgeDocumentRepository,
    )
    from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_version_repository import (
        KnowledgeDocumentVersionRepository,
    )
    from bisheng.message.domain.services.message_service import MessageService

# Maximum number of Knowledge Spaces a user can create
_MAX_SPACE_PER_USER = 200
# Maximum number of spaces a user can subscribe to (not as creator)
_MAX_SUBSCRIBE_PER_USER = 50
SPACE_ADMIN_ASSIGNMENT_MESSAGE = "assigned_knowledge_space_admin"
SPACE_ADMIN_REVOKED_MESSAGE = "revoked_knowledge_space_admin"
SPACE_MEMBER_REMOVED_MESSAGE = "removed_knowledge_space_member"
SPACE_MADE_PRIVATE_MESSAGE = "knowledge_space_made_private"
SPACE_DELETED_MESSAGE = "knowledge_space_deleted"
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

PORTAL_SEARCH_ES_RECALL_LIMIT = 80
PORTAL_SEARCH_VECTOR_RECALL_LIMIT = 24
PORTAL_SEARCH_FINAL_LIMIT = 50
PORTAL_SEARCH_PERMISSION_BATCH_SIZE = 50
PORTAL_SEARCH_OVERSAMPLE_FACTOR = 3
PORTAL_SEARCH_RRF_K = 60
PORTAL_SEARCH_ES_WEIGHT = 1.0
PORTAL_SEARCH_VECTOR_WEIGHT = 1.0
PORTAL_SEARCH_RERANK_MODEL_ID = ""
PORTAL_SEARCH_RERANK_MODEL_ID_ENV = "BISHENG_PORTAL_SEARCH_RERANK_MODEL_ID"
PORTAL_SEARCH_TITLE_MATCH_STOPWORDS = (
    "如何",
    "怎么",
    "怎样",
    "什么",
    "哪些",
    "是否",
    "有没有",
    "关于",
    "相关",
    "文档",
    "文件",
    "资料",
    "的",
)
_PORTAL_VISIBLE_SPACE_CACHE_TTL = 5.0
_PORTAL_VISIBLE_SPACE_CACHE: dict[tuple, tuple[float, list[Knowledge]]] = {}
_PORTAL_VISIBLE_SPACE_CACHE_LOCK = asyncio.Lock()

_AUDIO_FILE_EXTENSIONS = {"mp3", "wav", "m4a", "aac", "flac", "ogg"}
_VIDEO_FILE_EXTENSIONS = {"mp4", "mov", "avi", "mkv", "webm"}
_WEB_LINK_SEPARATORS = ["\n\n", "\n", "。", "\\.", "，", ",", "；", ";", "、", "\\s+", ""]
_WEB_LINK_SEPARATOR_RULES = ["after" for _ in _WEB_LINK_SEPARATORS]


@dataclass
class PortalSearchChunk:
    file_id: int
    knowledge_id: int
    content: str
    source: str
    retriever: str
    rank: int
    score: float
    metadata: dict[str, Any]


@dataclass
class PortalFileCandidate:
    file_id: int
    knowledge_id: int
    es_best_rank: int | None = None
    vector_best_rank: int | None = None
    es_best_score: float | None = None
    vector_best_score: float | None = None
    chunks: list[Any] = field(default_factory=list)
    fusion_score: float = 0.0
    rerank_score: float | None = None
    title_match_tier: int = 0
    title_match_score: float = 0.0
    title_match_reason: str = ""


@dataclass
class PortalSearchPerfContext:
    started_at: float
    stage: str = "start"
    keyword: str = ""
    sort: str = ""
    tag_enabled: bool = False
    file_ext: str = ""
    document_type: str = ""
    space_count: int = 0
    es_chunk_count: int = 0
    vector_chunk_count: int = 0
    candidate_count: int = 0
    visible_candidate_count: int = 0
    final_count: int = 0
    visible_check_count: int = 0
    fast_path_public_space_count: int = 0
    rerank_model_id: str = ""
    rerank_enabled: bool = False
    rerank_attempted: bool = False
    rerank_error: str = ""
    top_results: list[dict[str, Any]] = field(default_factory=list)
    success: bool = False
    error: str = ""


_portal_search_perf_var: contextvars.ContextVar[PortalSearchPerfContext | None] = contextvars.ContextVar(
    "portal_search_perf",
    default=None,
)


def _get_portal_search_perf() -> PortalSearchPerfContext | None:
    return _portal_search_perf_var.get()


def _set_portal_search_stage(stage: str) -> None:
    perf = _get_portal_search_perf()
    if perf is not None:
        perf.stage = stage


def _increment_portal_search_perf(field: str, amount: int = 1) -> None:
    perf = _get_portal_search_perf()
    if perf is not None:
        setattr(perf, field, getattr(perf, field) + amount)


class KnowledgeSpaceService(KnowledgeUtils):
    """Service for Knowledge Space operations.
    Instance-based; each method receives login_user as an argument.
    All business logic is async; DB access is delegated to DAO classes.
    """

    def __init__(self, request: Request, login_user: UserPayload):
        self.request = request
        self.login_user = login_user
        self.message_service: MessageService | None = None
        self.approval_gate: ApprovalGate | None = None
        # Injected by DI factory after construction (same pattern as message_service).
        # When set, list_space_children will exclude non-primary version files and
        # return version enrichment fields.
        self.version_repo: KnowledgeDocumentVersionRepository | None = None
        # Injected by DI factory alongside version_repo. Used by the version-link
        # cascade during file deletion to clear the logical-document anchor
        # whenever the whole chain (or its primary) gets removed.
        self.doc_repo: KnowledgeDocumentRepository | None = None
        self._created_space_scope_by_id: dict[
            int,
            tuple[KnowledgeSpaceLevelEnum, KnowledgeSpaceOwnerTypeEnum, int],
        ] = {}

    def _ensure_space_async_task_tenant_consistency(self, space: Knowledge, operation: str) -> None:
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
    _SHOUGANG_PORTAL_SHARE_SECRET_ALGORITHM = "pbkdf2_sha256"
    _SHOUGANG_PORTAL_SHARE_SECRET_ITERATIONS = 120_000

    @staticmethod
    def _resolve_subscription_status(
        membership: SpaceChannelMember | None,
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
        status: str | None,
        update_time: datetime | None,
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

            if update_time and update_time >= datetime.now() - REJECTED_STATUS_DISPLAY_WINDOW:
                return SpaceSubscriptionStatusEnum.REJECTED
        return SpaceSubscriptionStatusEnum.NOT_SUBSCRIBED

    @staticmethod
    def _apply_subscription_flags(
        result: KnowledgeSpaceInfoResp,
        subscription_status: SpaceSubscriptionStatusEnum,
    ) -> None:
        result.subscription_status = subscription_status
        result.is_followed = subscription_status == SpaceSubscriptionStatusEnum.SUBSCRIBED
        result.is_pending = subscription_status == SpaceSubscriptionStatusEnum.PENDING

    @staticmethod
    def _permission_level_to_space_user_role(
        permission_level: str | None,
    ) -> UserRoleEnum | None:
        if permission_level in ("owner", "can_manage"):
            # The UI only knows creator/admin/member. A direct owner grant must
            # preserve manage semantics without masquerading as the creator.
            return UserRoleEnum.ADMIN
        if permission_level in ("can_edit", "can_read"):
            return UserRoleEnum.MEMBER
        return None

    async def _get_tenant_root_department_id(self) -> int:
        tenant = await TenantDao.aget_by_id(int(self.login_user.tenant_id))
        root_dept_id = int(getattr(tenant, "root_dept_id", 0) or 0) if tenant else 0
        if not root_dept_id:
            raise SpaceInvalidScopeOwnerError(msg="Tenant root department does not exist")
        dept = await DepartmentDao.aget_by_id(root_dept_id)
        if dept is None or getattr(dept, "status", "active") != "active":
            raise SpaceInvalidScopeOwnerError(msg="Tenant root department does not exist")
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
            if getattr(dept, "id", None) is None:
                continue
            ids.add(int(dept.id))
            path = getattr(dept, "path", None)
            if path:
                ids.update(int(i) for i in await DepartmentDao.aget_subtree_ids(path))
        return ids

    async def _user_group_ids_for_create(self) -> set[int]:
        if self.login_user.is_admin():
            groups, _ = await GroupDao.aget_all_groups(1, 2000, "")
            return {int(group.id) for group in groups or [] if getattr(group, "id", None) is not None}

        member_groups = await UserGroupDao.aget_user_group(self.login_user.user_id)
        admin_groups = await UserGroupDao.aget_user_admin_group(self.login_user.user_id)
        return {
            int(link.group_id)
            for link in [*(member_groups or []), *(admin_groups or [])]
            if getattr(link, "group_id", None) is not None
        }

    @staticmethod
    def _paginate_options(items: list, page: int, page_size: int) -> tuple[list, int]:
        total = len(items)
        safe_page = max(int(page or 1), 1)
        safe_page_size = min(max(int(page_size or 20), 1), 100)
        offset = (safe_page - 1) * safe_page_size
        return items[offset : offset + safe_page_size], total

    @staticmethod
    def _department_path_name(dept, department_name_map: dict[int, str]) -> str | None:
        path_ids = [int(part) for part in str(getattr(dept, "path", "") or "").split("/") if part.isdigit()]
        names = [department_name_map.get(dept_id) for dept_id in path_ids if department_name_map.get(dept_id)]
        if not names and getattr(dept, "name", None):
            names = [dept.name]
        return "/".join(names) if names else None

    async def _department_options_for_create(
        self, *, approval_request: bool = False
    ) -> list[KnowledgeSpaceCreateOptionDepartment]:
        if self.login_user.is_admin() or approval_request:
            departments = await DepartmentDao.aget_active_by_tenant(int(self.login_user.tenant_id))
        else:
            department_ids = await self._admin_department_ids()
            departments = await DepartmentDao.aget_by_ids(list(department_ids)) if department_ids else []

        dept_name_map = {int(dept.id): dept.name for dept in departments if getattr(dept, "id", None) is not None}
        options = [
            KnowledgeSpaceCreateOptionDepartment(
                id=int(dept.id),
                name=dept.name,
                path_name=self._department_path_name(dept, dept_name_map),
            )
            for dept in departments
            if getattr(dept, "id", None) is not None
        ]
        return sorted(options, key=lambda item: (item.path_name or item.name or "", item.id))

    async def _department_tree_for_create(self, *, approval_request: bool = False) -> list[dict]:
        if self.login_user.is_admin() or approval_request:
            departments = await DepartmentDao.aget_active_by_tenant(int(self.login_user.tenant_id))
        else:
            department_ids = await self._admin_department_ids()
            departments = await DepartmentDao.aget_by_ids(list(department_ids)) if department_ids else []
        if not departments:
            return []

        dept_ids = [int(dept.id) for dept in departments if getattr(dept, "id", None) is not None]
        count_map: dict[int, int] = {}
        async with get_async_db_session() as session:
            count_result = await session.exec(
                select(
                    UserDepartment.department_id,
                    func.count(UserDepartment.id),
                )
                .where(UserDepartment.department_id.in_(dept_ids))
                .group_by(UserDepartment.department_id)
            )
            count_map = {int(dept_id): int(count) for dept_id, count in count_result.all()}

        nodes = {
            int(dept.id): {
                "id": int(dept.id),
                "dept_id": getattr(dept, "dept_id", "") or "",
                "name": dept.name,
                "parent_id": int(dept.parent_id) if getattr(dept, "parent_id", None) is not None else None,
                "member_count": count_map.get(int(dept.id), 0),
                "sort_order": int(getattr(dept, "sort_order", 0) or 0),
                "children": [],
            }
            for dept in departments
            if getattr(dept, "id", None) is not None
        }
        roots: list[dict] = []
        for node in nodes.values():
            parent_id = node["parent_id"]
            if parent_id and parent_id in nodes:
                nodes[parent_id]["children"].append(node)
            else:
                roots.append(node)

        def _sort_tree(items: list[dict]) -> list[dict]:
            items.sort(key=lambda item: (item.get("sort_order", 0), item.get("name", "")))
            for item in items:
                item["children"] = _sort_tree(item.get("children", []))
                item.pop("sort_order", None)
            return items

        return _sort_tree(roots)

    async def _user_group_options_for_create(self) -> list[KnowledgeSpaceCreateOptionUserGroup]:
        user_group_ids = await self._user_group_ids_for_create()
        groups = await GroupDao.aget_group_by_ids(list(user_group_ids)) if user_group_ids else []
        options = [
            KnowledgeSpaceCreateOptionUserGroup(id=int(group.id), group_name=group.group_name)
            for group in groups
            if getattr(group, "id", None) is not None
        ]
        return sorted(options, key=lambda item: item.group_name or "")

    async def _resolve_space_scope_on_create(
        self,
        *,
        space_level: KnowledgeSpaceLevelEnum | str | None,
        department_id: int | None,
        user_group_id: int | None,
        approval_request: bool = False,
    ) -> tuple[KnowledgeSpaceLevelEnum, KnowledgeSpaceOwnerTypeEnum, int]:
        level = self._normalize_space_level(space_level)

        if level == KnowledgeSpaceLevelEnum.PUBLIC:
            if department_id is not None or user_group_id is not None:
                raise SpaceInvalidScopeOwnerError()
            if not self.login_user.is_admin():
                raise SpaceCreatePublicDeniedError()
            return (
                level,
                KnowledgeSpaceOwnerTypeEnum.TENANT_ROOT_DEPARTMENT,
                await self._get_tenant_root_department_id(),
            )

        if level == KnowledgeSpaceLevelEnum.DEPARTMENT:
            if user_group_id is not None:
                raise SpaceInvalidScopeOwnerError()
            if department_id is None:
                raise SpaceInvalidScopeOwnerError()
            dept = await DepartmentDao.aget_by_id(int(department_id))
            if dept is None or getattr(dept, "status", "active") != "active":
                raise SpaceInvalidScopeOwnerError(msg="Department does not exist or is archived")
            if not self.login_user.is_admin():
                raise SpaceCreateDepartmentDeniedError()
            return level, KnowledgeSpaceOwnerTypeEnum.DEPARTMENT, int(department_id)

        if level == KnowledgeSpaceLevelEnum.TEAM:
            if user_group_id is not None or department_id is not None:
                raise SpaceInvalidScopeOwnerError()
            return level, KnowledgeSpaceOwnerTypeEnum.USER, int(self.login_user.user_id)

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

    @staticmethod
    def _normalize_space_name(name: str) -> str:
        return name.strip()

    async def _ensure_space_name_unique_in_scope(
        self,
        *,
        name: str,
        level: KnowledgeSpaceLevelEnum,
        owner_type: KnowledgeSpaceOwnerTypeEnum,
        owner_id: int,
        exclude_id: int | None = None,
        tenant_id: int | None = None,
    ) -> None:
        normalized_name = self._normalize_space_name(name)
        level = self._normalize_space_level(level)
        if level == KnowledgeSpaceLevelEnum.PERSONAL:
            existing_space = await KnowledgeDao.async_get_personal_space_by_owner_name(
                owner_id=owner_id,
                name=normalized_name,
                exclude_id=exclude_id,
            )
        else:
            existing_space = await KnowledgeDao.async_get_non_personal_space_by_name(
                name=normalized_name,
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
        grant: AuthorizeGrantItem | None = None
        if level == KnowledgeSpaceLevelEnum.PUBLIC:
            grant = AuthorizeGrantItem(
                subject_type="department",
                subject_id=owner_id,
                relation="viewer",
                include_children=True,
            )
        elif level == KnowledgeSpaceLevelEnum.DEPARTMENT:
            grant = AuthorizeGrantItem(
                subject_type="department",
                subject_id=owner_id,
                relation="viewer",
                include_children=True,
            )
        if grant is None:
            return
        await PermissionService.authorize(
            object_type="knowledge_space",
            object_id=str(space_id),
            grants=[grant],
            enforce_fga_success=True,
        )

    def build_created_space_info(
        self,
        space: Knowledge,
        *,
        level: KnowledgeSpaceLevelEnum | str | None = None,
        owner_type: KnowledgeSpaceOwnerTypeEnum | str | None = None,
        owner_id: int | None = None,
    ) -> KnowledgeSpaceInfoResp:
        result = KnowledgeSpaceInfoResp(**space.model_dump())
        result.user_name = self.login_user.user_name
        result.user_role = UserRoleEnum.CREATOR
        result.follower_num = 1
        result.file_num = 0
        result.can_unsubscribe = False
        cached_scope = self._created_space_scope_by_id.get(int(space.id)) if space.id else None
        if cached_scope is not None:
            cached_level, cached_owner_type, cached_owner_id = cached_scope
            level = level or cached_level
            owner_type = owner_type or cached_owner_type
            owner_id = owner_id if owner_id is not None else cached_owner_id
        result.space_level = self._normalize_space_level(level)
        if owner_type is not None and not isinstance(owner_type, KnowledgeSpaceOwnerTypeEnum):
            owner_type = KnowledgeSpaceOwnerTypeEnum(owner_type)
        result.owner_type = owner_type
        result.owner_id = owner_id
        if owner_type == KnowledgeSpaceOwnerTypeEnum.USER:
            result.owner_name = self.login_user.user_name
        self._apply_subscription_flags(result, SpaceSubscriptionStatusEnum.SUBSCRIBED)
        return result

    @staticmethod
    def _enqueue_knowledge_space_index_init(space_id: int, invoke_user_id: int) -> None:
        try:
            from bisheng.worker.knowledge.space_init_worker import init_knowledge_space_indices

            init_knowledge_space_indices.delay(space_id, invoke_user_id)
        except Exception:
            _logger.exception(
                "Failed to enqueue knowledge space index init: space_id=%s user_id=%s",
                space_id,
                invoke_user_id,
            )
            raise

    @staticmethod
    def _enqueue_default_scope_permissions(
        *,
        level: KnowledgeSpaceLevelEnum,
        owner_id: int,
        space_id: int,
    ) -> None:
        if level not in {
            KnowledgeSpaceLevelEnum.PUBLIC,
            KnowledgeSpaceLevelEnum.DEPARTMENT,
        }:
            return
        try:
            from bisheng.worker.knowledge.space_init_worker import grant_knowledge_space_scope_permissions

            grant_knowledge_space_scope_permissions.delay(
                space_id=space_id,
                level=level.value,
                owner_id=owner_id,
            )
        except Exception:
            _logger.exception(
                "Failed to enqueue knowledge space scope permissions: space_id=%s level=%s owner_id=%s",
                space_id,
                level.value,
                owner_id,
            )
            raise

    async def get_create_options(self) -> KnowledgeSpaceCreateOptionsResp:
        return KnowledgeSpaceCreateOptionsResp(
            can_create_public=bool(self.login_user.is_admin()),
            can_create_department=bool(self.login_user.is_admin()),
            can_create_team=True,
            can_create_personal=True,
            departments=[],
            user_groups=[],
            default_space_level=KnowledgeSpaceLevelEnum.PERSONAL,
        )

    async def get_create_departments(
        self,
        *,
        keyword: str = "",
        page: int = 1,
        page_size: int = 20,
        approval_request: bool = False,
    ) -> KnowledgeSpaceCreateOptionDepartmentsResp:
        tree = await self._department_tree_for_create(approval_request=approval_request)
        return KnowledgeSpaceCreateOptionDepartmentsResp(data=tree, total=len(tree))

    async def get_create_user_groups(
        self,
        *,
        keyword: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> KnowledgeSpaceCreateOptionUserGroupsResp:
        options = await self._user_group_options_for_create()
        normalized_keyword = (keyword or "").strip().lower()
        if normalized_keyword:
            options = [item for item in options if normalized_keyword in (item.group_name or "").lower()]
        page_items, total = self._paginate_options(options, page, page_size)
        return KnowledgeSpaceCreateOptionUserGroupsResp(data=page_items, total=total)

    async def _decorate_department_metadata(
        self,
        spaces: list[KnowledgeSpaceInfoResp],
    ) -> list[KnowledgeSpaceInfoResp]:
        if not spaces:
            return spaces
        space_ids = [int(space.id) for space in spaces]
        bindings = await DepartmentKnowledgeSpaceDao.aget_by_space_ids(space_ids)
        try:
            scopes = await KnowledgeSpaceScopeDao.aget_map_by_space_ids(space_ids)
        except Exception as e:
            _logger.debug("Failed to load knowledge space scope metadata: %s", e)
            scopes = {}
        binding_map = {binding.space_id: binding for binding in bindings}
        department_ids = {
            int(binding.department_id) for binding in bindings if getattr(binding, "department_id", None) is not None
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
            _logger.debug("Failed to load knowledge space owner groups: %s", e)
            groups = []
        group_name_map = {int(group.id): group.group_name for group in groups}

        user_ids = {
            int(scope.owner_id) for scope in scopes.values() if scope.owner_type == KnowledgeSpaceOwnerTypeEnum.USER
        }
        user_ids.update(int(space.user_id) for space in spaces if int(space.id) not in scopes)
        try:
            users = await UserDao.aget_user_by_ids(list(user_ids)) if user_ids else []
        except Exception as e:
            _logger.debug("Failed to load knowledge space owner users: %s", e)
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
                space.space_kind = "department"
                space.department_id = dept_id
                space.department_name = department_name_map.get(dept_id)
                if binding is not None:
                    space.approval_enabled = binding.approval_enabled
                    space.sensitive_check_enabled = binding.sensitive_check_enabled
        return spaces

    async def _format_accessible_spaces(
        self,
        space_ids: list[int],
        order_by: str,
        *,
        memberships: list[SpaceChannelMember] | None = None,
        exclude_created: bool = False,
        required_permission_id: str | None = None,
    ) -> list[KnowledgeRead]:
        if not space_ids:
            return []

        membership_map = {int(member.business_id): member for member in (memberships or [])}
        spaces = await KnowledgeDao.async_get_spaces_by_ids(space_ids, order_by)
        if exclude_created:
            spaces = [space for space in spaces if space.user_id != self.login_user.user_id]
        if not spaces:
            return []

        permission_space_ids = [
            space.id for space in spaces if space.user_id != self.login_user.user_id and space.id not in membership_map
        ]
        permission_id_space_ids = [space.id for space in spaces if space.user_id != self.login_user.user_id]
        permission_levels = {}
        permission_ids_map: dict[int, set[str]] = {}
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
            permission_levels = {space_id: level for space_id, level in zip(permission_space_ids, levels)}
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
            permission_ids_map = {space_id: ids for space_id, ids in zip(permission_id_space_ids, permission_ids)}

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
                self._apply_subscription_flags(result, SpaceSubscriptionStatusEnum.SUBSCRIBED)
            elif member_conf:
                if required_permission_id and required_permission_id not in permission_ids_map.get(space.id, set()):
                    continue
                result.user_role = member_conf.user_role
                self._apply_subscription_flags(result, self._resolve_subscription_status(member_conf))
                result.can_unsubscribe = await self._can_unsubscribe_space(space, member_conf)
            else:
                effective_permission_ids = permission_ids_map.get(space.id, set())
                if required_permission_id and required_permission_id not in effective_permission_ids:
                    continue
                result.user_role = self._permission_level_to_space_user_role(
                    permission_levels.get(space.id),
                )
                if (
                    result.user_role is None
                    and required_permission_id == "view_space"
                    and "view_space" in effective_permission_ids
                ):
                    result.user_role = UserRoleEnum.MEMBER
                if result.user_role is None:
                    continue
                self._apply_subscription_flags(result, SpaceSubscriptionStatusEnum.SUBSCRIBED)

            if result.is_pinned:
                pinned_spaces.append(result)
            else:
                normal_spaces.append(result)

        ordered_spaces = pinned_spaces + normal_spaces
        if ordered_spaces:
            file_count_map = await KnowledgeFileDao.async_count_success_files_batch(
                [space.id for space in ordered_spaces]
            )
            for space in ordered_spaces:
                space.file_num = int(file_count_map.get(space.id, 0) or 0)

        return await self._decorate_department_metadata(ordered_spaces)

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
            permission_ids = await self._get_effective_permission_ids(object_type, object_id)
            required_permission = "view_folder" if object_type == "folder" else "view_file"
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
    def _dedupe_ids(resource_ids: list[int]) -> list[int]:
        return list(dict.fromkeys(resource_ids))

    def _check_name_sensitive_words(self, name: str) -> None:
        """Raise SpaceNameSensitiveWordError if name hits the knowledge-space sensitive-word policy."""
        result = SensitiveWordPolicyService.check_text(
            tenant_id=self.login_user.tenant_id,
            business_type=SensitiveWordBusinessType.KNOWLEDGE_SPACE_FILE_PARSE,
            text=name,
        )
        if result.enabled and result.hits:
            raise SpaceNameSensitiveWordError()

    def _check_filename_sensitive_words(self, filename: str) -> None:
        """Raise SpaceFileNameSensitiveWordError if file name hits the sensitive-word policy."""
        result = SensitiveWordPolicyService.check_text(
            tenant_id=self.login_user.tenant_id,
            business_type=SensitiveWordBusinessType.KNOWLEDGE_SPACE_FILE_PARSE,
            text=filename,
        )
        if result.enabled and result.hits:
            raise SpaceFileNameSensitiveWordError()

    @staticmethod
    def _ensure_space_folder(folder: KnowledgeFile | None, space_id: int) -> KnowledgeFile:
        if not folder or folder.file_type != FileType.DIR.value or folder.knowledge_id != space_id:
            raise SpaceFolderNotFoundError()
        return folder

    @staticmethod
    def _ensure_space_file(
        file_record: KnowledgeFile | None,
        space_id: int,
        *,
        allow_folder: bool = False,
    ) -> KnowledgeFile:
        if not file_record or file_record.knowledge_id != space_id:
            raise SpaceFileNotFoundError()
        if not allow_folder and file_record.file_type != FileType.FILE.value:
            raise SpaceFileNotFoundError()
        return file_record

    async def _get_space_files_or_raise(self, space_id: int, file_ids: list[int]) -> list[KnowledgeFile]:
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

    async def _get_folder_for_action(self, space_id: int, folder_id: int) -> KnowledgeFile:
        folder = await KnowledgeFileDao.query_by_id(folder_id)
        return self._ensure_space_folder(folder, space_id)

    async def _require_file_relation(
        self,
        file_id: int,
        relation: str,
        *,
        space_id: int | None = None,
    ) -> KnowledgeFile:
        file_record = await KnowledgeFileDao.query_by_id(file_id)
        if not file_record:
            raise SpaceFileNotFoundError()
        actual_space_id = space_id or file_record.knowledge_id
        await self._require_read_permission(actual_space_id)
        file_record = self._ensure_space_file(file_record, actual_space_id)
        await self._require_resource_permission(relation, "knowledge_file", file_record.id)
        return file_record

    async def _get_file_for_action(
        self,
        file_id: int,
        *,
        space_id: int | None = None,
    ) -> KnowledgeFile:
        file_record = await KnowledgeFileDao.query_by_id(file_id)
        if not file_record:
            raise SpaceFileNotFoundError()
        return self._ensure_space_file(file_record, space_id or file_record.knowledge_id)

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
        return await self._require_file_relation(resource_id, relation, space_id=space_id)

    async def _get_active_space_membership(self, space_id: int) -> SpaceChannelMember | None:
        member = await SpaceChannelMemberDao.async_find_member(space_id, self.login_user.user_id)
        if member and member.is_active:
            return member
        return None

    async def _membership_satisfies_relation(self, space_id: int, relation: str) -> bool:
        required_level = _SPACE_RELATION_LEVEL.get(relation)
        if required_level is None:
            return False
        member = await self._get_active_space_membership(space_id)
        if not member:
            return False
        member_relation = _SPACE_MEMBER_ROLE_TO_RELATION.get(member.user_role)
        return _SPACE_MEMBER_RELATION_LEVEL.get(member_relation or "", 0) >= required_level

    async def _membership_permission_ids(self, space_id: int) -> set[str]:
        member = await self._get_active_space_membership(space_id)
        if not member:
            return set()
        relation = _SPACE_MEMBER_ROLE_TO_RELATION.get(member.user_role)
        return default_permission_ids_for_relation(relation or "")

    @staticmethod
    def _build_item_lineage(item: KnowledgeFile, space_id: int) -> list[tuple[str, int]]:
        object_type = "folder" if item.file_type == FileType.DIR.value else "knowledge_file"
        ancestor_ids = [int(part) for part in (item.file_level_path or "").split("/") if part]
        return (
            [(object_type, item.id)]
            + [("folder", fid) for fid in reversed(ancestor_ids)]
            + [
                ("knowledge_space", space_id),
            ]
        )

    async def _space_id_for_resource(self, object_type: str, object_id: int) -> int | None:
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
        await self._write_resource_parent_tuple(object_type, object_id, parent_type, parent_id)
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

    async def _cleanup_resource_tuples(self, resources: list[tuple[str, int]]) -> None:
        for resource_type, resource_id in resources:
            try:
                await OwnerService.delete_resource_tuples(resource_type, str(resource_id))
            except Exception as e:
                _logger.warning(
                    "Failed to delete FGA tuples for %s %s: %s",
                    resource_type,
                    resource_id,
                    e,
                )

    async def _get_relation_models_map(self) -> dict[str, dict]:
        if hasattr(self, "_relation_models_map_cache"):
            return self._relation_models_map_cache
        from bisheng.permission.api.endpoints.resource_permission import (
            _get_relation_models,
            _normalize_model_dict,
        )

        raw_models = await _get_relation_models()
        self._relation_models_map_cache = {m["id"]: _normalize_model_dict(m) for m in raw_models}
        return self._relation_models_map_cache

    async def _get_relation_bindings(self) -> list[dict]:
        if hasattr(self, "_relation_bindings_cache"):
            return self._relation_bindings_cache
        from bisheng.permission.api.endpoints.resource_permission import _get_bindings

        self._relation_bindings_cache = await _get_bindings()
        return self._relation_bindings_cache

    @staticmethod
    def _is_direct_space_user_binding(binding: dict, space_id: int, user_id: int) -> bool:
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
        if expected_relation not in {"viewer", "manager"}:
            return False
        return (
            binding.get("subject_type") == "user"
            and binding.get("relation") == expected_relation
            and (binding.get("model_id") or expected_relation) == expected_relation
        )

    def _binding_grants_view_space(
        self,
        binding: dict,
        models: dict[str, dict],
    ) -> bool:
        model_id = binding.get("model_id")
        model = models.get(model_id) if model_id else None
        permission_ids = self._permission_ids_for_relation(
            binding.get("relation") or "",
            model,
        )
        return "view_space" in permission_ids

    async def _has_unsubscribe_rebac_coverage(
        self,
        space_id: int,
        membership: SpaceChannelMember,
    ) -> bool:
        bindings = [
            binding
            for binding in await self._get_relation_bindings()
            if (binding.get("resource_type") == "knowledge_space" and str(binding.get("resource_id")) == str(space_id))
        ]
        if not bindings:
            return False

        models: dict[str, dict] | None = None
        user_subject_strings: set[str] | None = None
        binding_department_paths: dict[int, str] | None = None
        user_department_paths: dict[int, str] | None = None

        for binding in bindings:
            subject_type = binding.get("subject_type")
            if subject_type == "user":
                if not self._is_direct_space_user_binding(binding, space_id, self.login_user.user_id):
                    continue
                if self._is_default_join_relation_mirror(binding, membership):
                    continue
                if models is None:
                    models = await self._get_relation_models_map()
                if self._binding_grants_view_space(binding, models):
                    return True
                continue

            if subject_type not in {"department", "user_group"}:
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
        membership: SpaceChannelMember | None,
    ) -> bool:
        if not membership or not membership.is_active:
            return False
        if space.user_id == self.login_user.user_id or membership.user_role == UserRoleEnum.CREATOR:
            return False
        if (membership.membership_source or "manual") != "manual":
            return False
        return not await self._has_unsubscribe_rebac_coverage(int(space.id), membership)

    @classmethod
    async def sync_direct_space_user_permissions(
        cls,
        space_id: int,
        user_id: int,
        user_role: UserRoleEnum | None,
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
            binding for binding in bindings if not cls._is_direct_space_user_binding(binding, space_id, user_id)
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
        child_resources: list[tuple[str, int]],
    ) -> None:
        """Remove non-owner space permissions when a space becomes private."""
        from bisheng.permission.api.endpoints.resource_permission import (
            _get_bindings,
            _save_bindings,
        )

        resources = [("knowledge_space", int(space.id))] + list(child_resources)
        resource_keys = {(resource_type, str(resource_id)) for resource_type, resource_id in resources}

        bindings = await _get_bindings()
        await _save_bindings(
            [
                binding
                for binding in bindings
                if (binding.get("resource_type"), str(binding.get("resource_id"))) not in resource_keys
            ]
        )

        fga = await PermissionService._aget_fga()
        if fga is None:
            raise RuntimeError("FGAClient not available while clearing private-space permissions")

        operations: list[TupleOperation] = []
        for resource_type, resource_id in resources:
            tuples = await fga.read_tuples(object=f"{resource_type}:{resource_id}")
            for tuple_item in tuples:
                if cls._should_preserve_private_space_tuple(space.user_id, resource_type, tuple_item):
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

    async def _revoke_direct_space_user_permissions(self, space_id: int, user_id: int) -> None:
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

        self._current_user_subjects_cache = await FineGrainedPermissionService.get_current_user_subject_strings(
            self.login_user,
        )
        return self._current_user_subjects_cache

    async def _get_binding_department_paths(self, bindings: list[dict]) -> dict[int, str]:
        if hasattr(self, "_binding_department_paths_cache"):
            return self._binding_department_paths_cache

        department_ids = {
            int(binding["subject_id"])
            for binding in bindings
            if binding.get("subject_type") == "department" and binding.get("include_children")
        }
        departments = await DepartmentDao.aget_by_ids(list(department_ids))
        self._binding_department_paths_cache = {dept.id: dept.path or "" for dept in departments}
        return self._binding_department_paths_cache

    @staticmethod
    def _permission_ids_for_relation(
        relation: str,
        model: dict | None = None,
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
        bindings: list[dict],
        binding_department_paths: dict[int, str],
        user_subject_strings: set[str],
    ) -> dict | None:
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
            if binding.get("resource_type") != resource_type or str(binding.get("resource_id")) != str(resource_id):
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
            tuple_department_rows = await DepartmentDao.aget_by_ids([tuple_department_id])
            tuple_department_path = tuple_department_rows[0].path if tuple_department_rows else ""
            for binding in bindings:
                if binding.get("resource_type") != resource_type or str(binding.get("resource_id")) != str(resource_id):
                    continue
                if binding.get("relation") != relation:
                    continue
                if binding.get("subject_type") != "department" or not binding.get("include_children"):
                    continue
                binding_path = binding_department_paths.get(int(binding.get("subject_id")))
                if binding_path and tuple_department_path and tuple_department_path.startswith(binding_path):
                    return binding
        return None

    async def _build_resource_lineage(
        self,
        object_type: str,
        object_id: int,
        *,
        space_id: int | None = None,
    ) -> list[tuple[str, int]]:
        if object_type == "knowledge_space":
            return [("knowledge_space", object_id)]

        if object_type == "folder":
            folder = await KnowledgeFileDao.query_by_id(object_id)
            folder = self._ensure_space_folder(folder, space_id or folder.knowledge_id)
            ancestor_ids = [int(part) for part in (folder.file_level_path or "").split("/") if part]
            return (
                [("folder", folder.id)]
                + [("folder", fid) for fid in reversed(ancestor_ids)]
                + [
                    ("knowledge_space", folder.knowledge_id),
                ]
            )

        if object_type == "knowledge_file":
            file_record = await KnowledgeFileDao.query_by_id(object_id)
            file_record = self._ensure_space_file(file_record, space_id or file_record.knowledge_id)
            ancestor_ids = [int(part) for part in (file_record.file_level_path or "").split("/") if part]
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
        space_id: int | None = None,
    ) -> set[str]:
        # Evaluate permissions across the resource lineage from child -> parent.
        # For a tuple backed by a custom relation model, permissions[] controls
        # runtime actions. Relation-only defaults are kept only as a legacy
        # fallback for old tuples or built-in system models.
        lineage = await self._build_resource_lineage(object_type, object_id, space_id=space_id)
        lineage_binding_can_override = object_type in {"folder", "knowledge_file"}
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
            lineage=lineage,
            nearest_binding_wins=lineage_binding_can_override,
            return_match_metadata=True,
            use_permission_level_fallback=not lineage_binding_can_override,
        )
        for lineage_type, lineage_id in lineage:
            if lineage_type == "knowledge_space":
                if not (lineage_binding_can_override and matched_lineage_binding):
                    effective_permissions.update(await self._membership_permission_ids(int(lineage_id)))
                break
        effective_permissions.update(await self._public_space_viewer_permission_ids(lineage))
        return effective_permissions

    async def _build_child_permission_context(self, space_id: int) -> dict:
        user_subject_strings = await self._get_current_user_subject_strings()
        bindings = await self._get_relation_bindings()
        binding_department_paths = await self._get_binding_department_paths(bindings)
        models = await self._get_relation_models_map()
        membership_permission_ids = await self._membership_permission_ids(space_id)
        public_space_permission_ids = await self._public_space_viewer_permission_ids([("knowledge_space", space_id)])
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
        object_type = "folder" if item.file_type == FileType.DIR.value else "knowledge_file"
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

    async def _public_space_viewer_permission_ids(self, lineage: list[tuple[str, int]]) -> set[str]:
        space_id = next(
            (lineage_id for lineage_type, lineage_id in lineage if lineage_type == "knowledge_space"),
            None,
        )
        if space_id is None:
            return set()
        space = await KnowledgeDao.aquery_by_id(int(space_id))
        if not space or space.type != KnowledgeTypeEnum.SPACE.value:
            return set()
        space_level = getattr(space, "space_level", None)
        if space_level is None:
            scope = await KnowledgeSpaceScopeDao.aget_by_space_id(int(space_id))
            space_level = scope.level if scope else None
        if getattr(space_level, "value", space_level) == KnowledgeSpaceLevelEnum.PUBLIC.value:
            return default_permission_ids_for_relation("viewer")
        return set()

    async def _require_permission_id(
        self,
        object_type: str,
        object_id: int,
        permission_id: str,
        *,
        space_id: int | None = None,
    ) -> None:
        effective_permissions = await self._get_effective_permission_ids(
            object_type,
            object_id,
            space_id=space_id,
        )
        if permission_id not in effective_permissions:
            raise SpacePermissionDeniedError()

    async def _list_space_child_resources(self, space_id: int) -> list[tuple[str, int]]:
        async with get_async_db_session() as session:
            rows = (
                await session.exec(
                    select(KnowledgeFile.id, KnowledgeFile.file_type).where(
                        KnowledgeFile.knowledge_id == space_id,
                    )
                )
            ).all()
        return [
            ("folder", resource_id) if file_type == FileType.DIR.value else ("knowledge_file", resource_id)
            for resource_id, file_type in rows
        ]

    async def _require_read_permission(self, space_id: int) -> Knowledge:
        space = await KnowledgeDao.aquery_by_id(space_id)
        if not space or space.type != KnowledgeTypeEnum.SPACE.value:
            raise SpaceNotFoundError()
        effective_permissions = await self._get_effective_permission_ids("knowledge_space", space_id)
        if "view_space" not in effective_permissions:
            raise SpacePermissionDeniedError()
        return space

    @staticmethod
    def _is_square_preview_space(space: Knowledge) -> bool:
        return space.is_released and space.auth_type in {
            AuthTypeEnum.PUBLIC,
            AuthTypeEnum.APPROVAL,
        }

    async def _require_space_info_permission(self, space_id: int) -> tuple[Knowledge, bool]:
        space = await KnowledgeDao.aquery_by_id(space_id)
        if not space or space.type != KnowledgeTypeEnum.SPACE.value:
            raise SpaceNotFoundError()
        effective_permissions = await self._get_effective_permission_ids("knowledge_space", space_id)
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
        return bool(getattr(cfg, "auto_tag_visible", True)) if cfg else True

    @staticmethod
    async def _is_review_tag_feature_enabled() -> bool:
        (
            cfg,
            _inherited,
            _src,
            _has_override,
        ) = await WorkStationService.get_knowledge_space_config_with_meta()
        return bool(getattr(cfg, "review_tag_visible", True)) if cfg else True

    @staticmethod
    async def _require_review_tag_feature_enabled() -> None:
        if not await KnowledgeSpaceService._is_review_tag_feature_enabled():
            raise ReviewTagFeatureDisabledError()

    @staticmethod
    def _resolve_requested_library_ids(
        auto_tag_library_id: int | None,
        auto_tag_library_ids: list[int] | None = None,
    ) -> list[int]:
        if auto_tag_library_ids is not None:
            return list(dict.fromkeys(int(item) for item in auto_tag_library_ids if item))
        if auto_tag_library_id is not None:
            return [int(auto_tag_library_id)]
        return []

    @staticmethod
    async def _decorate_auto_tag_for_info(result: KnowledgeSpaceInfoResp) -> None:
        """Populate auto-tag wire fields and mask private-library ids."""
        library_ids = await KnowledgeTagLibraryLinkDao.alist_library_ids_by_knowledge(result.id)
        if not library_ids and result.auto_tag_library_id:
            library_ids = [int(result.auto_tag_library_id)]

        public_ids: list[int] = []
        custom_tags: list[str] = []
        for library_id in library_ids:
            library = await KnowledgeSpaceTagLibraryDao.aget(library_id)
            if not library:
                continue
            if library.owner_knowledge_id is not None and library.owner_knowledge_id == result.id:
                manual, _ai = await TagLibraryTagService.list_tag_names(library_id)
                custom_tags.extend(manual or list(library.tags or []))
            else:
                public_ids.append(library_id)

        result.auto_tag_library_ids = public_ids or library_ids
        if custom_tags and not public_ids:
            result.auto_tag_mode = "custom"
            result.auto_tag_custom_tags = custom_tags
            result.auto_tag_library_id = None
            result.auto_tag_library_ids = []
            return

        result.auto_tag_mode = "library"
        result.auto_tag_custom_tags = None
        result.auto_tag_library_id = public_ids[0] if public_ids else (library_ids[0] if library_ids else None)
        result.auto_tag_library_ids = public_ids or library_ids

    @classmethod
    async def _apply_auto_tag_binding(
        cls,
        *,
        knowledge: Knowledge,
        auto_tag_enabled: bool,
        auto_tag_library_id: int | None,
        auto_tag_library_ids: list[int] | None = None,
        auto_tag_custom_tags: list[str] | None,
        user_id: int,
        tenant_id: int | None,
    ) -> tuple[bool, int | None]:
        """Resolve auto-tag state and sync knowledge↔library links."""
        library_update_requested = auto_tag_library_ids is not None or auto_tag_library_id is not None
        if not auto_tag_enabled:
            await KnowledgeSpaceTagLibraryDao.adelete_private_for_knowledge(knowledge.id)
            if library_update_requested:
                requested_ids = cls._resolve_requested_library_ids(
                    auto_tag_library_id,
                    auto_tag_library_ids,
                )
                if requested_ids:
                    await KnowledgeSpaceTagLibraryService.validate_bindable_libraries(requested_ids)
                await KnowledgeTagLibraryLinkDao.areplace_for_knowledge(
                    knowledge.id,
                    tenant_id,
                    requested_ids,
                )
                primary = requested_ids[0] if requested_ids else None
            else:
                existing_ids = await KnowledgeTagLibraryLinkDao.alist_library_ids_by_knowledge(
                    knowledge.id,
                )
                primary = existing_ids[0] if existing_ids else knowledge.auto_tag_library_id
            return False, primary

        requested_ids = cls._resolve_requested_library_ids(
            auto_tag_library_id,
            auto_tag_library_ids,
        )
        if auto_tag_custom_tags is not None and requested_ids:
            raise KnowledgeSpaceTagLibraryInvalidError(message="不能同时指定标签库与自定义标签")

        if auto_tag_custom_tags is not None:
            normalized = KnowledgeSpaceTagLibraryService.normalize_tags(auto_tag_custom_tags)
            if not normalized:
                raise KnowledgeSpaceTagLibraryInvalidError(message="开启自动标签时必须提供至少一个自定义标签")
            private = await KnowledgeSpaceTagLibraryDao.aupsert_private(
                knowledge_id=knowledge.id,
                tenant_id=tenant_id,
                user_id=user_id,
                tags=normalized,
            )
            await KnowledgeTagLibraryLinkDao.areplace_for_knowledge(
                knowledge.id,
                tenant_id,
                [int(private.id)],
            )
            return True, int(private.id)

        await KnowledgeSpaceTagLibraryService.validate_bindable_libraries(requested_ids)
        await KnowledgeSpaceTagLibraryDao.adelete_private_for_knowledge(knowledge.id)
        await KnowledgeTagLibraryLinkDao.areplace_for_knowledge(
            knowledge.id,
            tenant_id,
            requested_ids,
        )
        primary = requested_ids[0] if requested_ids else None
        return True, primary

    async def validate_knowledge_space_create(
        self,
        name: str,
        description: str | None = None,
        icon: str | None = None,
        auth_type: AuthTypeEnum = AuthTypeEnum.PUBLIC,
        is_released: bool = False,
        space_level: KnowledgeSpaceLevelEnum | str | None = KnowledgeSpaceLevelEnum.PERSONAL,
        department_id: int | None = None,
        user_group_id: int | None = None,
        auto_tag_enabled: bool = False,
        auto_tag_library_id: int | None = None,
        auto_tag_library_ids: list[int] | None = None,
        auto_tag_custom_tags: list[str] | None = None,
        skip_user_limit: bool = False,
        approval_request: bool = False,
    ) -> tuple[KnowledgeSpaceLevelEnum, KnowledgeSpaceOwnerTypeEnum, int]:
        name = self._normalize_space_name(name)
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
            approval_request=approval_request,
        )
        await self._ensure_space_name_unique_in_scope(
            name=name,
            level=level,
            owner_type=owner_type,
            owner_id=owner_id,
        )

        auto_tag_touched = (
            auto_tag_enabled
            or auto_tag_library_id is not None
            or auto_tag_library_ids is not None
            or auto_tag_custom_tags is not None
        )
        if auto_tag_touched:
            if auto_tag_custom_tags is not None:
                normalized = KnowledgeSpaceTagLibraryService.normalize_tags(auto_tag_custom_tags)
                if not normalized:
                    raise KnowledgeSpaceTagLibraryInvalidError(message="开启自动标签时必须提供至少一个自定义标签")
            else:
                await KnowledgeSpaceTagLibraryService.validate_bindable_libraries(
                    self._resolve_requested_library_ids(
                        auto_tag_library_id,
                        auto_tag_library_ids,
                    )
                )

        return level, owner_type, owner_id

    async def create_knowledge_space(
        self,
        name: str,
        description: str | None = None,
        icon: str | None = None,
        auth_type: AuthTypeEnum = AuthTypeEnum.PUBLIC,
        is_released: bool = False,
        space_level: KnowledgeSpaceLevelEnum | str | None = KnowledgeSpaceLevelEnum.PERSONAL,
        department_id: int | None = None,
        user_group_id: int | None = None,
        auto_tag_enabled: bool = False,
        auto_tag_library_id: int | None = None,
        auto_tag_library_ids: list[int] | None = None,
        auto_tag_custom_tags: list[str] | None = None,
        skip_user_limit: bool = False,
    ) -> Knowledge:
        """Create a new knowledge space (max 200 per user)."""

        perf_start = time.perf_counter()
        perf_last = perf_start

        def log_perf_stage(stage: str) -> None:
            nonlocal perf_last
            now = time.perf_counter()
            _logger.info(
                "knowledge_space_create_perf stage=%s elapsed_ms=%.2f total_ms=%.2f user_id=%s",
                stage,
                (now - perf_last) * 1000,
                (now - perf_start) * 1000,
                self.login_user.user_id,
            )
            perf_last = now

        name = self._normalize_space_name(name)
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
        log_perf_stage("validate")

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

        knowledge_space = await KnowledgeService.acreate_knowledge_base(
            self.request,
            self.login_user,
            db_knowledge,
            skip_hook=True,
            initialize_indices=False,
        )
        log_perf_stage("db_create")
        self._enqueue_knowledge_space_index_init(
            int(knowledge_space.id),
            int(self.login_user.user_id),
        )
        log_perf_stage("enqueue_index_init")

        if auto_tag_enabled or auto_tag_library_id is not None or auto_tag_custom_tags is not None:
            resolved_enabled, resolved_library_id = await self._apply_auto_tag_binding(
                knowledge=knowledge_space,
                auto_tag_enabled=auto_tag_enabled,
                auto_tag_library_id=auto_tag_library_id,
                auto_tag_library_ids=auto_tag_library_ids,
                auto_tag_custom_tags=auto_tag_custom_tags,
                user_id=self.login_user.user_id,
                tenant_id=self.login_user.tenant_id,
            )
            if resolved_enabled or resolved_library_id is not None:
                knowledge_space.auto_tag_enabled = resolved_enabled
                knowledge_space.auto_tag_library_id = resolved_library_id
                knowledge_space = await KnowledgeDao.async_update_space(knowledge_space)
            log_perf_stage("auto_tag")

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
        log_perf_stage("owner_tuple")

        await self._create_space_scope(
            space_id=int(knowledge_space.id),
            level=level,
            owner_type=owner_type,
            owner_id=owner_id,
        )
        self._created_space_scope_by_id[int(knowledge_space.id)] = (level, owner_type, owner_id)
        log_perf_stage("scope_create")
        self._enqueue_default_scope_permissions(
            level=level,
            owner_id=owner_id,
            space_id=int(knowledge_space.id),
        )
        log_perf_stage("enqueue_scope_permission")

        # Audit log for knowledge space creation
        await KnowledgeAuditTelemetryService.audit_create_knowledge_space(
            self.login_user, self.request, knowledge_space
        )
        log_perf_stage("audit")
        _logger.info(
            "knowledge_space_create_perf stage=total total_ms=%.2f user_id=%s space_id=%s",
            (time.perf_counter() - perf_start) * 1000,
            self.login_user.user_id,
            knowledge_space.id,
        )

        return knowledge_space

    async def get_space_info(self, space_id: int) -> KnowledgeSpaceInfoResp:
        from bisheng.worker import rebuild_knowledge_celery

        space, has_content_permission = await self._require_space_info_permission(space_id)

        follower_num = await SpaceChannelMemberDao.async_count_space_members(space_id)
        total_file_num = (await KnowledgeFileDao.async_count_success_files_batch([space_id])).get(space_id, 0)
        result = KnowledgeSpaceInfoResp(**space.model_dump())
        member_info = None
        if space.user_id != self.login_user.user_id:
            create_user = await UserDao.aget_user(space.user_id)
            result.user_name = create_user.user_name if create_user else str(space.user_id)
        else:
            result.user_name = self.login_user.user_name
        if space.user_id == self.login_user.user_id:
            result.user_role = UserRoleEnum.CREATOR
            self._apply_subscription_flags(result, SpaceSubscriptionStatusEnum.SUBSCRIBED)
        else:
            member_info = await SpaceChannelMemberDao.async_find_member(
                space_id=space.id,
                user_id=self.login_user.user_id,
            )
            if member_info:
                self._apply_subscription_flags(result, self._resolve_subscription_status(member_info))
                if member_info.is_active:
                    result.user_role = member_info.user_role
            elif has_content_permission and not self.login_user.is_admin():
                self._apply_subscription_flags(result, SpaceSubscriptionStatusEnum.SUBSCRIBED)
            if result.user_role is None and has_content_permission:
                level = await PermissionService.get_permission_level(
                    user_id=self.login_user.user_id,
                    object_type="knowledge_space",
                    object_id=str(space_id),
                    login_user=self.login_user,
                )
                result.user_role = self._permission_level_to_space_user_role(level)
                is_global_admin = False
                is_admin = getattr(self.login_user, "is_admin", None)
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

    async def get_shougang_portal_space_levels(self) -> list[dict]:
        return [
            {"value": KnowledgeSpaceLevelEnum.PUBLIC.value, "label": "公共空间"},
            {"value": KnowledgeSpaceLevelEnum.DEPARTMENT.value, "label": "部门空间"},
            {"value": KnowledgeSpaceLevelEnum.TEAM.value, "label": "团队空间"},
            {"value": KnowledgeSpaceLevelEnum.PERSONAL.value, "label": "个人空间"},
        ]

    async def get_shougang_portal_personal_spaces(self) -> dict:
        grouped = await self.get_grouped_spaces()
        fav_space_id: int | None = None
        try:
            fav = await self._ensure_favorite_space()
            fav_space_id = int(fav.id)
        except Exception as exc:  # best-effort：收藏库懒创建失败不应阻断个人库列表
            logger.warning("ensure favorite space failed in personal-spaces: {}", exc)
        items: list[ShougangPortalPersonalSpaceItemResp] = []
        for space in getattr(grouped, "personal_spaces", []) or []:
            if getattr(space, "space_level", KnowledgeSpaceLevelEnum.PERSONAL) != KnowledgeSpaceLevelEnum.PERSONAL:
                continue
            is_fav = bool(getattr(space, "is_favorite", False)) or (
                fav_space_id is not None and int(space.id) == fav_space_id
            )
            permission_ids = await self._get_effective_permission_ids("knowledge_space", int(space.id))
            if "upload_file" not in permission_ids and not is_fav:
                continue
            items.append(
                ShougangPortalPersonalSpaceItemResp(
                    id=int(space.id),
                    name=str(space.name or ""),
                    description=str(space.description or ""),
                    file_count=int(getattr(space, "file_num", 0) or 0),
                    updated_at=self._serialize_datetime(getattr(space, "update_time", None)),
                    is_favorite=is_fav,
                )
            )
        # 收藏库若刚建、尚未出现在 grouped 里，补进列表
        if fav_space_id is not None and not any(it.id == fav_space_id for it in items):
            fav_row = await KnowledgeDao.aquery_by_id(fav_space_id)
            if fav_row:
                items.append(
                    ShougangPortalPersonalSpaceItemResp(
                        id=fav_space_id,
                        name=str(fav_row.name or "我的收藏"),
                        description=str(fav_row.description or ""),
                        file_count=0,
                        updated_at=self._serialize_datetime(getattr(fav_row, "update_time", None)),
                        is_favorite=True,
                    )
                )
        items.sort(key=lambda x: not x.is_favorite)  # 收藏库排首位
        data = [item.model_dump(mode="json") for item in items]
        return {"data": data, "total": len(data)}

    FAVORITE_SPACE_NAME = "我的收藏"

    async def _find_favorite_space(self) -> Knowledge | None:
        return await KnowledgeDao.aget_user_favorite_space(self.login_user.user_id)

    async def _adopt_existing_favorite_space(self) -> Knowledge | None:
        """收编：用户已有同名个人库（含本功能上线前手动创建的『我的收藏』）时，
        将其标记为 is_favorite 复用，避免创建撞名(SpaceNameDuplicateError)。"""
        space = await KnowledgeDao.async_get_personal_space_by_owner_name(
            owner_id=self.login_user.user_id,
            name=self.FAVORITE_SPACE_NAME,
        )
        if not space:
            return None
        if not getattr(space, "is_favorite", False):
            space.is_favorite = True
            space = await KnowledgeDao.async_update_space(space)
        return space

    async def _create_favorite_space(self) -> Knowledge:
        space = await self.create_knowledge_space(
            name=self.FAVORITE_SPACE_NAME,
            description="系统默认收藏知识库",
            space_level=KnowledgeSpaceLevelEnum.PERSONAL,
            skip_user_limit=True,
        )
        space.is_favorite = True
        await KnowledgeDao.async_update_space(space)
        return space

    async def _ensure_favorite_space(self) -> Knowledge:
        """懒创建、幂等：已有收藏库→返回；有同名个人库→收编；否则创建；并发/撞名兜底回查+收编。"""
        existing = await self._find_favorite_space()
        if existing:
            return existing
        adopted = await self._adopt_existing_favorite_space()
        if adopted:
            return adopted
        try:
            return await self._create_favorite_space()
        except Exception:
            again = await self._find_favorite_space()
            if again:
                return again
            adopted_again = await self._adopt_existing_favorite_space()
            if adopted_again:
                return adopted_again
            raise

    @staticmethod
    def _favorite_ref_meta(source_space_id: int, source_file_id: int) -> dict:
        return {"favorite_reference": {"source_space_id": int(source_space_id), "source_file_id": int(source_file_id)}}

    async def _find_favorite_reference(self, fav_space_id, source_space_id, source_file_id):
        rows, _ = await KnowledgeFileDao.aget_references_by_knowledge_id(int(fav_space_id))
        for row in rows:
            meta = (row.user_metadata or {}).get("favorite_reference") or {}
            if int(meta.get("source_space_id") or 0) == int(source_space_id) and int(
                meta.get("source_file_id") or 0
            ) == int(source_file_id):
                return row
        return None

    async def _create_favorite_reference(self, fav_space, source_space, source_file):
        ref = KnowledgeFile(
            knowledge_id=int(fav_space.id),
            user_id=self.login_user.user_id,
            file_name=source_file.file_name,
            file_type=source_file.file_type,
            md5=source_file.md5,
            status=KnowledgeFileStatus.SUCCESS.value,
            file_source="favorite_reference",
            user_metadata=self._favorite_ref_meta(int(source_space.id), int(source_file.id)),
        )
        return await KnowledgeFileDao.aadd_file(ref)

    async def create_shougang_portal_favorite(
        self,
        req: ShougangPortalFavoriteCreateReq,
    ) -> ShougangPortalFavoriteCreateResp:
        source_space = await KnowledgeDao.aquery_by_id(req.source_space_id)
        if not source_space or source_space.type != KnowledgeTypeEnum.SPACE.value:
            raise SpaceNotFoundError()
        source_file = await KnowledgeFileDao.query_by_id(req.source_file_id)
        source_file = self._ensure_space_file(source_file, req.source_space_id)
        await self._require_permission_id(
            "knowledge_file", req.source_file_id, "view_file", space_id=req.source_space_id
        )

        fav_space = await self._ensure_favorite_space()
        existing = await self._find_favorite_reference(int(fav_space.id), req.source_space_id, req.source_file_id)
        if existing:
            title = Path(existing.file_name or source_file.file_name or "").stem
            return ShougangPortalFavoriteCreateResp(
                favorite_file_id=int(existing.id),
                space_id=int(fav_space.id),
                source_space_id=req.source_space_id,
                source_file_id=req.source_file_id,
                title=title,
            )

        ref_file = await self._create_favorite_reference(fav_space, source_space, source_file)
        await KnowledgeDao.async_update_knowledge_update_time_by_id(int(fav_space.id))
        title = Path(ref_file.file_name or source_file.file_name or "").stem
        return ShougangPortalFavoriteCreateResp(
            favorite_file_id=int(ref_file.id),
            space_id=int(fav_space.id),
            source_space_id=req.source_space_id,
            source_file_id=req.source_file_id,
            title=title,
        )

    async def remove_shougang_portal_favorite(
        self, req: ShougangPortalFavoriteRemoveReq
    ) -> ShougangPortalFavoriteRemoveResp:
        fav_space = await self._find_favorite_space()
        if not fav_space:
            return ShougangPortalFavoriteRemoveResp(removed=False)
        ref = await self._find_favorite_reference(int(fav_space.id), req.source_space_id, req.source_file_id)
        if not ref:
            return ShougangPortalFavoriteRemoveResp(removed=False)
        await KnowledgeFileDao.adelete_batch([int(ref.id)])
        await KnowledgeDao.async_update_knowledge_update_time_by_id(int(fav_space.id))
        return ShougangPortalFavoriteRemoveResp(removed=True)

    async def get_shougang_portal_favorite_status(
        self, req: ShougangPortalFavoriteStatusReq
    ) -> ShougangPortalFavoriteStatusResp:
        fav_space = await self._find_favorite_space()
        favored: set[tuple[int, int]] = set()
        if fav_space:
            rows, _ = await KnowledgeFileDao.aget_references_by_knowledge_id(int(fav_space.id))
            for row in rows:
                meta = (row.user_metadata or {}).get("favorite_reference") or {}
                favored.add((int(meta.get("source_space_id") or 0), int(meta.get("source_file_id") or 0)))
        data = [
            ShougangPortalFavoriteStatusResultItem(
                space_id=it.space_id, file_id=it.file_id, favorited=(it.space_id, it.file_id) in favored
            )
            for it in req.items
        ]
        return ShougangPortalFavoriteStatusResp(data=data)

    async def list_shougang_portal_favorites(
        self, page: int = 1, page_size: int = 20
    ) -> ShougangPortalFavoriteFilesResp:
        fav_space = await self._find_favorite_space()
        if not fav_space:
            return ShougangPortalFavoriteFilesResp(data=[], total=0, page=page, page_size=page_size)
        rows, total = await KnowledgeFileDao.aget_references_by_knowledge_id(
            int(fav_space.id), page=page, page_size=page_size
        )
        data: list[ShougangPortalFavoriteFileItem] = []
        for ref in rows:
            meta = (ref.user_metadata or {}).get("favorite_reference") or {}
            src_space = int(meta.get("source_space_id") or 0)
            src_file = int(meta.get("source_file_id") or 0)
            alive = (await KnowledgeFileDao.query_by_id(src_file)) is not None if src_file else False
            data.append(
                ShougangPortalFavoriteFileItem(
                    favorite_file_id=int(ref.id),
                    source_space_id=src_space,
                    source_file_id=src_file,
                    title=Path(ref.file_name or "").stem,
                    file_name=str(ref.file_name or ""),
                    status="valid" if alive else "invalid",
                    updated_at=self._serialize_datetime(getattr(ref, "update_time", None)),
                )
            )
        return ShougangPortalFavoriteFilesResp(data=data, total=total, page=page, page_size=page_size)

    @staticmethod
    def _enum_value(value) -> str:
        raw = getattr(value, "value", value)
        return str(raw or "")

    @classmethod
    def _hash_shougang_portal_share_secret(cls, secret: str) -> str:
        normalized = str(secret or "")
        if not normalized:
            return ""
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            normalized.encode("utf-8"),
            salt.encode("utf-8"),
            cls._SHOUGANG_PORTAL_SHARE_SECRET_ITERATIONS,
        ).hex()
        return (
            f"{cls._SHOUGANG_PORTAL_SHARE_SECRET_ALGORITHM}$"
            f"{cls._SHOUGANG_PORTAL_SHARE_SECRET_ITERATIONS}${salt}${digest}"
        )

    @classmethod
    def _verify_shougang_portal_share_secret(cls, secret: str, secret_hash: str) -> bool:
        if not secret_hash:
            return True
        parts = str(secret_hash).split("$")
        if len(parts) != 4 or parts[0] != cls._SHOUGANG_PORTAL_SHARE_SECRET_ALGORITHM:
            return False
        try:
            iterations = int(parts[1])
        except ValueError:
            return False
        salt = parts[2]
        expected = parts[3]
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            str(secret or "").encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        ).hex()
        return hmac.compare_digest(actual, expected)

    @staticmethod
    def _generate_shougang_portal_invite_code() -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        return "".join(secrets.choice(alphabet) for _ in range(6))

    @staticmethod
    def _is_shougang_portal_share_expired(share_link: ShareLink) -> bool:
        expire_time = int(getattr(share_link, "expire_time", 0) or 0)
        create_time = getattr(share_link, "create_time", None)
        if expire_time <= 0 or not create_time:
            return False
        return create_time + timedelta(seconds=expire_time) < datetime.now()

    @staticmethod
    def _shougang_portal_share_permissions(meta_data: dict) -> ShougangPortalSharePermissions:
        permissions = meta_data.get("permissions") or {}
        return ShougangPortalSharePermissions(
            view=True,
            download=bool(permissions.get("download")),
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

    def _require_shougang_portal_file_share_link(self, share_link: ShareLink) -> dict:
        resource_type = self._enum_value(getattr(share_link, "resource_type", ""))
        if resource_type not in {
            ShareResourceTypeEnum.KNOWLEDGE_SPACE_FILE.value,
            ShareResourceTypeEnum.KNOWLEDGE_SPACE_FILE.name,
        }:
            raise NotFoundError()
        status = self._enum_value(getattr(share_link, "status", ""))
        if status not in {
            ShareLinkStatusEnum.ACTIVE.value,
            ShareLinkStatusEnum.ACTIVE.name,
        }:
            raise NotFoundError()
        meta_data = getattr(share_link, "meta_data", None) or {}
        if not isinstance(meta_data, dict):
            raise NotFoundError()
        return meta_data

    async def _resolve_shougang_portal_space_department_id(self, space_id: int) -> int:
        binding = await DepartmentKnowledgeSpaceDao.aget_by_space_id(space_id)
        if binding and getattr(binding, "department_id", None) is not None:
            return int(binding.department_id)

        scope = await KnowledgeSpaceScopeDao.aget_by_space_id(space_id)
        scope_level = self._enum_value(getattr(scope, "level", "")) if scope else ""
        if (
            scope
            and scope_level == KnowledgeSpaceLevelEnum.DEPARTMENT.value
            and self._enum_value(getattr(scope, "owner_type", "")) == KnowledgeSpaceOwnerTypeEnum.DEPARTMENT.value
            and getattr(scope, "owner_id", None) is not None
        ):
            return int(scope.owner_id)
        return 0

    async def _resolve_shougang_portal_create_share_department_id(self, source_space: Knowledge) -> int:
        space_id = int(source_space.id)
        scope = await KnowledgeSpaceScopeDao.aget_by_space_id(space_id)
        scope_level = self._enum_value(getattr(scope, "level", "")) if scope else ""
        if scope and scope_level == KnowledgeSpaceLevelEnum.PERSONAL.value:
            return await self._resolve_shougang_portal_current_user_department_id()
        if (
            scope
            and scope_level == KnowledgeSpaceLevelEnum.DEPARTMENT.value
            and self._enum_value(getattr(scope, "owner_type", "")) == KnowledgeSpaceOwnerTypeEnum.DEPARTMENT.value
            and getattr(scope, "owner_id", None) is not None
        ):
            return int(scope.owner_id)
        space_department_id = await self._resolve_shougang_portal_space_department_id(space_id)
        if space_department_id:
            return space_department_id
        return await self._resolve_shougang_portal_current_user_department_id()

    async def _resolve_shougang_portal_current_user_department_id(self) -> int:
        login_user_id = self._normalize_shougang_portal_user_id(getattr(self.login_user, "user_id", None))
        if login_user_id is None:
            return 0
        primary_department = await UserDepartmentDao.aget_user_primary_department(login_user_id)
        if primary_department and getattr(primary_department, "department_id", None) is not None:
            return int(primary_department.department_id)
        departments = await UserDepartmentDao.aget_user_departments(login_user_id)
        for department in departments or []:
            if getattr(department, "department_id", None) is not None:
                return int(department.department_id)
        return 0

    @staticmethod
    def _normalize_shougang_portal_user_id(user_id) -> int | None:
        if user_id is None or user_id == "":
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
                "knowledge_file",
                int(source_file.id),
                "share_file",
                space_id=int(source_space.id),
            )
            return
        except SpacePermissionDeniedError:
            pass

        login_user_id = self._normalize_shougang_portal_user_id(getattr(self.login_user, "user_id", None))
        if login_user_id is None:
            raise SpacePermissionDeniedError(msg="当前账号没有分享该文档的权限")

        if self._normalize_shougang_portal_user_id(getattr(source_file, "user_id", None)) == login_user_id:
            return
        if self._normalize_shougang_portal_user_id(getattr(source_space, "user_id", None)) == login_user_id:
            return

        membership = await SpaceChannelMemberDao.async_find_member(int(source_space.id), login_user_id)
        if (
            membership
            and membership.is_active
            and self._enum_value(membership.user_role) in {UserRoleEnum.CREATOR.value, UserRoleEnum.ADMIN.value}
        ):
            return

        raise SpacePermissionDeniedError(msg="当前账号没有分享该文档的权限")

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
            raise SpacePermissionDeniedError(msg="Invalid share type")
        if visibility not in {item.value for item in ShougangPortalShareVisibility}:
            raise SpacePermissionDeniedError(msg="Invalid share visibility")

        department_id = 0
        if visibility == ShougangPortalShareVisibility.DEPARTMENT.value:
            department_id = await self._resolve_shougang_portal_create_share_department_id(source_space)
            if not department_id:
                raise SpacePermissionDeniedError(
                    msg="当前账号未绑定部门，无法创建仅本部门分享",
                )

        invite_code = (
            self._generate_shougang_portal_invite_code()
            if share_type == ShougangPortalShareType.INVITE_CODE.value
            else ""
        )
        password = str(req.password or "")
        meta_data = {
            "space_id": int(req.space_id),
            "file_id": int(req.file_id),
            "file_name": str(source_file.file_name or ""),
            "share_type": share_type,
            "visibility": visibility,
            "permissions": {
                "view": True,
                "download": bool(req.allow_download),
                "upload": False,
            },
            "password_hash": self._hash_shougang_portal_share_secret(password),
            "invite_code_hash": self._hash_shougang_portal_share_secret(invite_code),
        }
        if department_id:
            meta_data["department_id"] = department_id
        tenant_id = int(getattr(self.login_user, "tenant_id", 1) or 1)
        share_link = ShareLink(
            share_token=common_util.generate_short_high_entropy_string(),
            resource_id=str(req.file_id),
            resource_type=ShareResourceTypeEnum.KNOWLEDGE_SPACE_FILE,
            share_mode=ShareMode.READ_ONLY,
            expire_time=int(req.expire_seconds or 0),
            meta_data=meta_data,
            create_user_id=str(getattr(self.login_user, "user_id", "")),
            tenant_id=tenant_id,
        )
        saved = await self._save_shougang_portal_share_link(share_link)
        return ShougangPortalShareLinkCreateResp(
            share_token=saved.share_token,
            link=f"/share/document/{saved.share_token}",
            invite_code=invite_code,
            expire_seconds=int(req.expire_seconds or 0),
        )

    async def get_shougang_portal_share_link_meta(
        self,
        share_token: str,
    ) -> ShougangPortalShareLinkMetaResp:
        share_link = await self._get_shougang_portal_share_link(share_token)
        meta_data = self._require_shougang_portal_file_share_link(share_link)
        share_type = self._enum_value(meta_data.get("share_type")) or ShougangPortalShareType.LINK.value
        visibility = self._enum_value(meta_data.get("visibility")) or ShougangPortalShareVisibility.DEPARTMENT.value
        return ShougangPortalShareLinkMetaResp(
            share_token=share_link.share_token,
            file_name=str(meta_data.get("file_name") or ""),
            share_type=share_type,
            visibility=visibility,
            permissions=self._shougang_portal_share_permissions(meta_data),
            requires_password=bool(meta_data.get("password_hash")),
            requires_invite_code=(
                share_type == ShougangPortalShareType.INVITE_CODE.value or bool(meta_data.get("invite_code_hash"))
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
            raise SpacePermissionDeniedError(msg="Share link has expired")

        password_hash = str(meta_data.get("password_hash") or "")
        if password_hash and not self._verify_shougang_portal_share_secret(req.password, password_hash):
            raise SpacePermissionDeniedError(msg="Invalid share password")

        share_type = self._enum_value(meta_data.get("share_type"))
        invite_code_hash = str(meta_data.get("invite_code_hash") or "")
        if share_type == ShougangPortalShareType.INVITE_CODE.value:
            invite_code = str(req.invite_code or "").strip().upper()
            if not invite_code or not self._verify_shougang_portal_share_secret(invite_code, invite_code_hash):
                raise SpacePermissionDeniedError(msg="Invalid invite code")

        space_id = int(meta_data.get("space_id") or 0)
        file_id = int(meta_data.get("file_id") or 0)
        if not space_id or not file_id:
            raise NotFoundError()

        visibility = self._enum_value(meta_data.get("visibility"))
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
        meta_data: dict,
    ) -> None:
        if await self._can_shougang_portal_department_share_access(
            space_id=space_id,
            share_link=share_link,
            meta_data=meta_data,
        ):
            return
        raise SpacePermissionDeniedError(
            msg="Share link is limited to the owning department, sub-departments, reviewers, or creator",
        )

    async def _can_shougang_portal_department_share_access(
        self,
        *,
        space_id: int,
        share_link: ShareLink,
        meta_data: dict,
    ) -> bool:
        user_id = int(getattr(self.login_user, "user_id", 0) or 0)
        if not user_id:
            return False

        if str(getattr(share_link, "create_user_id", "") or "") == str(user_id):
            return True

        department_id = int(meta_data.get("department_id") or 0)
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
        if dept and getattr(dept, "path", None):
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

        admin_department_ids = {int(row.id) for row in admin_departments if getattr(row, "id", None) is not None}
        if int(department_id) in admin_department_ids:
            return True

        target_dept = await DepartmentDao.aget_by_id(department_id)
        target_path = str(getattr(target_dept, "path", "") or "")
        if not target_path:
            return False
        return any(
            bool(getattr(row, "path", None)) and target_path.startswith(str(row.path)) for row in admin_departments
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
                "Failed to resolve shougang portal share reviewers for space_id={}",
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
        space_ids: list[int],
        space_level: KnowledgeSpaceLevelEnum | None,
    ) -> list[str]:
        spaces = await self._get_shougang_portal_visible_search_spaces(space_ids, space_level)
        if not spaces:
            return []
        tag_map = await TagDao.aget_tags_by_business_ids(
            business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE,
            business_ids=[str(space.id) for space in spaces],
        )
        tag_names = {str(tag.name) for tags in tag_map.values() for tag in tags if tag.name}
        return sorted(tag_names)

    async def count_shougang_portal_domain_files(self, codes: list[str]) -> dict[str, int]:
        return await KnowledgeFileDao.async_count_files_by_domain_codes(codes)

    async def get_shougang_portal_home(self, req: ShougangPortalHomeReq) -> dict:
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
        all_tags = [tag for tags in tag_map.values() for tag in tags if tag.id is not None and tag.name]
        hot_tags = list(dict.fromkeys(str(tag.name) for tag in all_tags))[: req.hot_tags_limit]
        if not section_tags:
            return {"sections": empty_sections, "tags": hot_tags}

        section_tag_ids_by_name: dict[str, list[int]] = {
            tag_name: [int(tag.id) for tag in all_tags if tag.name == tag_name and tag.id is not None]
            for tag_name in section_tags
        }
        section_tag_ids = [tag_id for tag_ids in section_tag_ids_by_name.values() for tag_id in tag_ids]
        if not section_tag_ids:
            return {"sections": empty_sections, "tags": hot_tags}

        links = await TagDao.aget_resources_by_tags(section_tag_ids, ResourceTypeEnum.SPACE_FILE)
        file_ids_by_section: dict[str, list[int]] = {tag_name: [] for tag_name in section_tags}
        tag_name_by_id = {
            tag_id: tag_name for tag_name, tag_ids in section_tag_ids_by_name.items() for tag_id in tag_ids
        }
        all_file_ids: list[int] = []
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
            order_by="update_time",
            order_sort="desc",
        )
        visible_files = await self._filter_shougang_portal_visible_files(files, spaces=spaces)
        enriched_items = await self._handle_file_folder_extra_info(visible_files)
        item_map: dict[int, ShougangPortalFileItemResp] = {}
        for item in enriched_items:
            space_id = int(item.get("knowledge_id") or 0)
            item["knowledge_name"] = space_name_map.get(space_id, str(space_id))
            if self._is_shougang_portal_file_item(item, None):
                mapped = self._map_shougang_portal_file_item(space_id, item)
                item_map[mapped.id] = mapped

        sections: dict[str, list[dict]] = {}
        for section in req.sections:
            ids = list(dict.fromkeys(file_ids_by_section.get(section.tag, [])))
            items = [item_map[file_id] for file_id in ids if file_id in item_map]
            items = self._sort_shougang_portal_file_items(items, "updated_at", None)
            sections[section.tag] = [item.model_dump(mode="json") for item in items[: section.page_size]]
        return {"sections": sections, "tags": hot_tags}

    async def get_shougang_portal_space_infos(self, space_ids: list[int]) -> list[ShougangPortalSpaceInfoItemResp]:
        if not space_ids:
            return []

        unique_space_ids = list(dict.fromkeys(int(space_id) for space_id in space_ids))
        spaces = await KnowledgeDao.async_get_spaces_by_ids(unique_space_ids, order_by="update_time")
        space_map = {int(space.id): space for space in spaces if int(space.type) == KnowledgeTypeEnum.SPACE.value}

        permission_results = await asyncio.gather(
            *[self._get_effective_permission_ids("knowledge_space", space_id) for space_id in space_map],
            return_exceptions=True,
        )
        permission_map = dict(zip(space_map.keys(), permission_results))

        visible_space_ids: list[int] = []
        has_content_permission_map: dict[int, bool] = {}
        error_map: dict[int, ShougangPortalSpaceInfoError] = {}
        is_admin = self.login_user.is_admin() if callable(getattr(self.login_user, "is_admin", None)) else False
        for space_id in unique_space_ids:
            space = space_map.get(space_id)
            if not space:
                error_map[space_id] = ShougangPortalSpaceInfoError(
                    code=SpaceNotFoundError.Code,
                    message=SpaceNotFoundError.Msg,
                )
                continue
            if is_admin:
                visible_space_ids.append(space_id)
                has_content_permission_map[space_id] = True
                continue
            permission_result = permission_map.get(space_id)
            if isinstance(permission_result, Exception):
                error_map[space_id] = ShougangPortalSpaceInfoError(
                    code=500,
                    message="Failed to get knowledge space info",
                )
                continue
            if "view_space" in permission_result:
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
        creator_ids = list(
            {
                int(space_map[space_id].user_id)
                for space_id in visible_space_ids
                if space_map[space_id].user_id != self.login_user.user_id
            }
        )
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
            int(member.business_id): member for member in (memberships or []) if str(member.business_id).isdigit()
        }
        is_global_admin = False
        is_admin = getattr(self.login_user, "is_admin", None)
        if callable(is_admin):
            is_global_admin = bool(is_admin())

        permission_level_space_ids = [
            space_id
            for space_id in visible_space_ids
            if space_map[space_id].user_id != self.login_user.user_id
            and not (member_map.get(space_id) and member_map[space_id].is_active)
            and has_content_permission_map.get(space_id)
        ]
        permission_levels: dict[int, str | None] = {}
        if permission_level_space_ids:
            levels = await asyncio.gather(
                *[
                    PermissionService.get_permission_level(
                        user_id=self.login_user.user_id,
                        object_type="knowledge_space",
                        object_id=str(space_id),
                        login_user=self.login_user,
                    )
                    for space_id in permission_level_space_ids
                ]
            )
            permission_levels = {space_id: level for space_id, level in zip(permission_level_space_ids, levels)}

        result_map: dict[int, KnowledgeSpaceInfoResp] = {}
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

        items: list[ShougangPortalSpaceInfoItemResp] = []
        for space_id in space_ids:
            result = result_map.get(space_id)
            if result:
                items.append(
                    ShougangPortalSpaceInfoItemResp(
                        id=space_id,
                        data=result.model_dump(mode="json"),
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

    @classmethod
    def _normalize_shougang_portal_business_domain_codes(cls, codes: list[str]) -> list[str]:
        normalized_codes: list[str] = []
        seen: set[str] = set()
        for raw_code in codes or []:
            code = normalize_business_domain_code(raw_code)
            if code is None:
                raise SpaceBusinessDomainCodeInvalidError()
            if code not in seen:
                normalized_codes.append(code)
                seen.add(code)
        return normalized_codes

    async def sync_shougang_portal_space_business_domain_codes(
        self,
        req: ShougangPortalSpaceBusinessDomainCodesSyncReq,
    ) -> dict[str, int]:
        if not req.bindings:
            return {"updated": 0}

        bindings: dict[int, list[str]] = {}
        for item in req.bindings:
            bindings[int(item.space_id)] = self._normalize_shougang_portal_business_domain_codes(
                item.business_domain_codes
            )

        spaces = await KnowledgeDao.async_get_spaces_by_ids(list(bindings.keys()), order_by="update_time")
        existing_space_ids = {int(space.id) for space in spaces}
        if existing_space_ids != set(bindings.keys()):
            raise SpaceNotFoundError()

        updated = await KnowledgeDao.async_update_space_business_domain_codes(bindings)
        return {"updated": updated}

    async def search_shougang_portal_files(self, req: ShougangPortalFileSearchReq) -> dict:
        perf = PortalSearchPerfContext(started_at=time.monotonic())
        perf.keyword = (req.q or "").strip()
        perf.sort = req.sort
        perf.tag_enabled = bool(req.tag)
        perf.file_ext = str(req.file_ext or "")
        perf.document_type = self._normalize_shougang_document_type_code(req.document_type)
        perf_token = _portal_search_perf_var.set(perf)
        fga_token = begin_fga_read_stats()
        try:
            result = await self._search_shougang_portal_files_impl(req)
            perf.success = True
            return result
        except Exception as exc:
            perf.error = type(exc).__name__
            raise
        finally:
            fga_stats = finish_fga_read_stats(fga_token)
            duration_ms = int((time.monotonic() - perf.started_at) * 1000)
            payload = {
                "keyword": perf.keyword,
                "sort": perf.sort,
                "tag_enabled": perf.tag_enabled,
                "file_ext": perf.file_ext,
                "document_type": perf.document_type,
                "space_count": perf.space_count,
                "es_chunk_count": perf.es_chunk_count,
                "vector_chunk_count": perf.vector_chunk_count,
                "candidate_count": perf.candidate_count,
                "visible_candidate_count": perf.visible_candidate_count,
                "final_count": perf.final_count,
                "visible_check_count": perf.visible_check_count,
                "fga_read_count": fga_stats.read_count,
                "cache_hit_count": fga_stats.cache_hit_count,
                "singleflight_wait_count": fga_stats.singleflight_wait_count,
                "fast_path_public_space_count": perf.fast_path_public_space_count,
                "rerank_model_id": perf.rerank_model_id,
                "rerank_enabled": perf.rerank_enabled,
                "rerank_attempted": perf.rerank_attempted,
                "rerank_error": perf.rerank_error,
                "top_results": perf.top_results,
                "duration_ms": duration_ms,
                "success": perf.success,
                "stage": perf.stage,
                "error": perf.error,
            }
            try:
                logger.info("[perf][portal.search] {}", payload)
            except Exception:
                pass
            _portal_search_perf_var.reset(perf_token)

    async def search_shougang_portal_qa_files_by_name(self, req: ShougangPortalQaFileSearchReq) -> dict:
        keyword = (req.q or "").strip()
        if not keyword:
            return self._build_shougang_portal_search_response([])
        spaces = await self._get_shougang_portal_visible_search_spaces(req.space_ids, None)
        if not spaces:
            return self._build_shougang_portal_search_response([])

        space_ids = [int(space.id) for space in spaces]
        files = await KnowledgeFileDao.aget_file_by_space_filters(
            knowledge_ids=space_ids,
            file_name=keyword,
            status=[KnowledgeFileStatus.SUCCESS.value],
            order_by="update_time",
            order_sort="desc",
            match_file_encoding=True,
        )
        if not files:
            return self._build_shougang_portal_search_response([])

        visible_files = await self._filter_shougang_portal_visible_files(files, spaces=spaces)
        if not visible_files:
            return self._build_shougang_portal_search_response([])

        space_name_map = {int(space.id): str(space.name or space.id) for space in spaces}
        enriched_items = await self._handle_file_folder_extra_info(visible_files)
        folder_path_map, source_path_map = await self._resolve_shougang_portal_source_paths(enriched_items)
        items: list[ShougangPortalFileItemResp] = []
        for item in enriched_items:
            space_id = int(item.get("knowledge_id") or 0)
            item_id = int(item.get("id") or 0)
            item["knowledge_name"] = space_name_map.get(space_id, str(space_id))
            item["folder_path"] = folder_path_map.get(item_id, "")
            item["source_path"] = source_path_map.get(item_id, "")
            if self._is_shougang_portal_file_item(item, None):
                items.append(self._map_shougang_portal_file_item(space_id, item))

        sorted_items = self._sort_shougang_portal_file_items(items, "relevance", keyword)
        start = (req.page - 1) * req.page_size
        page_items = sorted_items[start : start + req.page_size]
        return {
            "data": [item.model_dump(mode="json") for item in page_items],
            "total": len(sorted_items),
            "page": req.page,
            "page_size": req.page_size,
        }

    async def _search_shougang_portal_files_impl(self, req: ShougangPortalFileSearchReq) -> dict:
        _set_portal_search_stage("resolve_spaces")
        spaces = await self._get_shougang_portal_visible_search_spaces(req.space_ids, req.space_level)
        perf = _get_portal_search_perf()
        if perf is not None:
            perf.space_count = len(spaces)
        if not spaces:
            return self._build_shougang_portal_search_response([])

        _set_portal_search_stage("resolve_tag")
        space_ids = [int(space.id) for space in spaces]
        tag_file_ids = await self._get_shougang_portal_tag_file_ids(space_ids, req.tag)
        if req.tag and not tag_file_ids:
            return self._build_shougang_portal_search_response([])

        if req.q and req.q.strip():
            _set_portal_search_stage("semantic_search")
            return await self._semantic_search_shougang_portal_files(
                req=req,
                spaces=spaces,
                tag_file_ids=tag_file_ids,
            )

        _set_portal_search_stage("list_files")
        return await self._list_shougang_portal_files_without_keyword(
            req=req,
            spaces=spaces,
            tag_file_ids=tag_file_ids,
        )

    async def _list_shougang_portal_files_without_keyword(
        self,
        *,
        req: ShougangPortalFileSearchReq,
        spaces: list[Knowledge],
        tag_file_ids: list[int] | None,
    ) -> dict:
        space_ids = [int(space.id) for space in spaces]
        files = await KnowledgeFileDao.aget_file_by_space_filters(
            knowledge_ids=space_ids,
            file_name=None,
            status=[KnowledgeFileStatus.SUCCESS.value],
            file_ids=tag_file_ids,
            extra_file_ids=None,
            file_ext=req.file_ext,
            order_by="update_time",
            order_sort=self._shougang_portal_order_sort(req.sort),
        )
        if not files:
            return self._build_shougang_portal_paged_response([], req.page, req.page_size)

        files = self._filter_shougang_portal_files_by_document_type(files, req.document_type)
        if not files:
            return self._build_shougang_portal_paged_response([], req.page, req.page_size)

        visible_files = await self._filter_shougang_portal_visible_files(files, spaces=spaces)
        if not visible_files:
            return self._build_shougang_portal_paged_response([], req.page, req.page_size)

        space_name_map = {int(space.id): str(space.name or space.id) for space in spaces}
        enriched_items = await self._handle_file_folder_extra_info(visible_files)
        folder_path_map, source_path_map = await self._resolve_shougang_portal_source_paths(enriched_items)
        all_items: list[ShougangPortalFileItemResp] = []
        for item in enriched_items:
            space_id = int(item.get("knowledge_id") or 0)
            item["knowledge_name"] = space_name_map.get(space_id, str(space_id))
            item_id = int(item.get("id") or 0)
            item["folder_path"] = folder_path_map.get(item_id, "")
            item["source_path"] = source_path_map.get(item_id, "")
            if self._is_shougang_portal_file_item(item, req.file_ext, req.document_type):
                all_items.append(self._map_shougang_portal_file_item(space_id, item))

        sorted_items = self._sort_shougang_portal_file_items(all_items, req.sort, req.q)
        return self._build_shougang_portal_paged_response(sorted_items, req.page, req.page_size)

    async def _semantic_search_shougang_portal_files(
        self,
        *,
        req: ShougangPortalFileSearchReq,
        spaces: list[Knowledge],
        tag_file_ids: list[int] | None,
    ) -> dict:
        keyword = (req.q or "").strip()
        perf = _get_portal_search_perf()
        if perf is not None:
            perf.keyword = keyword
            perf.sort = req.sort
            perf.tag_enabled = bool(req.tag)
            perf.file_ext = str(req.file_ext or "")
            perf.document_type = self._normalize_shougang_document_type_code(req.document_type)
        es_chunks, vector_chunks = await asyncio.gather(
            self._search_shougang_portal_es_chunks(
                spaces=spaces,
                keyword=keyword,
                filter_file_ids=tag_file_ids,
                limit=PORTAL_SEARCH_ES_RECALL_LIMIT * PORTAL_SEARCH_OVERSAMPLE_FACTOR,
            ),
            self._search_shougang_portal_vector_chunks(
                spaces=spaces,
                keyword=keyword,
                filter_file_ids=tag_file_ids,
                limit=PORTAL_SEARCH_VECTOR_RECALL_LIMIT * PORTAL_SEARCH_OVERSAMPLE_FACTOR,
            ),
        )
        if perf is not None:
            perf.es_chunk_count = len(es_chunks)
            perf.vector_chunk_count = len(vector_chunks)
        candidates = self._group_shougang_portal_chunks_by_file(es_chunks + vector_chunks)
        ranked_candidates = self._score_shougang_portal_file_candidates(candidates)
        _increment_portal_search_perf("candidate_count", len(ranked_candidates))
        if not ranked_candidates:
            return self._build_shougang_portal_search_response([])

        visible_candidates, visible_file_map = await self._collect_visible_shougang_portal_semantic_candidates(
            ranked_candidates=ranked_candidates,
            spaces=spaces,
            tag_file_ids=tag_file_ids,
            file_ext=req.file_ext,
            document_type=req.document_type,
            sort=req.sort,
        )
        if not visible_candidates:
            return self._build_shougang_portal_search_response([])
        if perf is not None:
            perf.visible_candidate_count = len(visible_candidates)

        if not self._is_shougang_portal_updated_at_sort(req.sort):
            self._score_shougang_portal_candidate_title_matches(
                keyword=keyword,
                candidates=visible_candidates,
                file_map=visible_file_map,
            )
            visible_candidates = await self._rerank_shougang_portal_file_candidates(
                keyword=keyword,
                candidates=visible_candidates,
                file_map=visible_file_map,
                rerank_model_id=req.rerank_model_id,
                rerank_model_id_provided=self._is_pydantic_field_set(req, "rerank_model_id"),
            )
        visible_candidates = self._sort_shougang_portal_semantic_candidates(
            candidates=visible_candidates,
            sort=req.sort,
            file_map=visible_file_map,
        )[:PORTAL_SEARCH_FINAL_LIMIT]
        if perf is not None:
            perf.final_count = len(visible_candidates)
            self._set_shougang_portal_search_top_result_debug(visible_candidates, visible_file_map)
        items = await self._map_shougang_portal_candidate_items(
            candidates=visible_candidates,
            file_map=visible_file_map,
            spaces=spaces,
            file_ext=req.file_ext,
            document_type=req.document_type,
        )
        return self._build_shougang_portal_search_response(items)

    async def _collect_visible_shougang_portal_semantic_candidates(
        self,
        *,
        ranked_candidates: list[PortalFileCandidate],
        spaces: list[Knowledge],
        tag_file_ids: list[int] | None,
        file_ext: str | None,
        document_type: str | None,
        sort: str,
    ) -> tuple[list[PortalFileCandidate], dict[int, KnowledgeFile]]:
        if self._is_shougang_portal_updated_at_sort(sort):
            return await self._collect_visible_shougang_portal_updated_at_candidates(
                ranked_candidates=ranked_candidates,
                spaces=spaces,
                tag_file_ids=tag_file_ids,
                file_ext=file_ext,
                document_type=document_type,
                sort=sort,
            )

        visible_candidates: list[PortalFileCandidate] = []
        visible_file_map: dict[int, KnowledgeFile] = {}
        space_ids = [int(space.id) for space in spaces]
        for start in range(0, len(ranked_candidates), PORTAL_SEARCH_PERMISSION_BATCH_SIZE):
            batch_candidates = ranked_candidates[start : start + PORTAL_SEARCH_PERMISSION_BATCH_SIZE]
            batch_file_ids = [candidate.file_id for candidate in batch_candidates]
            files = await KnowledgeFileDao.aget_file_by_space_filters(
                knowledge_ids=space_ids,
                file_name=None,
                status=[KnowledgeFileStatus.SUCCESS.value],
                file_ids=tag_file_ids,
                extra_file_ids=batch_file_ids,
                file_ext=file_ext,
                order_by="update_time",
                order_sort=self._shougang_portal_order_sort(sort),
            )
            if not files:
                continue
            files = self._filter_shougang_portal_files_by_document_type(files, document_type)
            if not files:
                continue
            visible_files = await self._filter_shougang_portal_visible_files(files, spaces=spaces)
            visible_batch_map = {int(file.id): file for file in visible_files}
            for candidate in batch_candidates:
                file = visible_batch_map.get(candidate.file_id)
                if file is None:
                    continue
                visible_candidates.append(candidate)
                visible_file_map[candidate.file_id] = file
                if len(visible_candidates) >= PORTAL_SEARCH_FINAL_LIMIT:
                    return visible_candidates[:PORTAL_SEARCH_FINAL_LIMIT], visible_file_map
        return visible_candidates, visible_file_map

    async def _collect_visible_shougang_portal_updated_at_candidates(
        self,
        *,
        ranked_candidates: list[PortalFileCandidate],
        spaces: list[Knowledge],
        tag_file_ids: list[int] | None,
        file_ext: str | None,
        document_type: str | None,
        sort: str,
    ) -> tuple[list[PortalFileCandidate], dict[int, KnowledgeFile]]:
        space_ids = [int(space.id) for space in spaces]
        candidate_file_ids = [candidate.file_id for candidate in ranked_candidates]
        files = await KnowledgeFileDao.aget_file_by_space_filters(
            knowledge_ids=space_ids,
            file_name=None,
            status=[KnowledgeFileStatus.SUCCESS.value],
            file_ids=tag_file_ids,
            extra_file_ids=candidate_file_ids,
            file_ext=file_ext,
            order_by="update_time",
            order_sort=self._shougang_portal_order_sort(sort),
        )
        if not files:
            return [], {}
        files = self._filter_shougang_portal_files_by_document_type(files, document_type)
        if not files:
            return [], {}
        file_map = {int(file.id): file for file in files}
        ordered_candidates = sorted(
            [candidate for candidate in ranked_candidates if candidate.file_id in file_map],
            key=lambda candidate: self._get_shougang_portal_file_update_timestamp(file_map.get(candidate.file_id)),
            reverse=self._shougang_portal_order_sort(sort) == "desc",
        )
        visible_candidates: list[PortalFileCandidate] = []
        visible_file_map: dict[int, KnowledgeFile] = {}
        for start in range(0, len(ordered_candidates), PORTAL_SEARCH_PERMISSION_BATCH_SIZE):
            batch_candidates = ordered_candidates[start : start + PORTAL_SEARCH_PERMISSION_BATCH_SIZE]
            batch_files = [
                file_map[candidate.file_id] for candidate in batch_candidates if candidate.file_id in file_map
            ]
            visible_files = await self._filter_shougang_portal_visible_files(batch_files, spaces=spaces)
            visible_batch_map = {int(file.id): file for file in visible_files}
            for candidate in batch_candidates:
                file = visible_batch_map.get(candidate.file_id)
                if file is None:
                    continue
                visible_candidates.append(candidate)
                visible_file_map[candidate.file_id] = file
                if len(visible_candidates) >= PORTAL_SEARCH_FINAL_LIMIT:
                    return visible_candidates[:PORTAL_SEARCH_FINAL_LIMIT], visible_file_map
        return visible_candidates, visible_file_map

    async def _search_shougang_portal_es_chunks(
        self,
        *,
        spaces: list[Knowledge],
        keyword: str,
        filter_file_ids: list[int] | None,
        limit: int = PORTAL_SEARCH_ES_RECALL_LIMIT,
    ) -> list[PortalSearchChunk]:
        index_names = [str(space.index_name) for space in spaces if space.index_name]
        if not keyword or not index_names:
            return []
        text_query: dict[str, Any] = {
            "bool": {
                "should": [
                    {
                        "match": {
                            "text": {
                                "query": keyword,
                                "boost": 1.0,
                            }
                        }
                    },
                    {
                        "match_phrase": {
                            "text": {
                                "query": keyword,
                                "boost": 3.0,
                            }
                        }
                    },
                ],
                "minimum_should_match": 1,
            },
        }
        filters: list[dict[str, Any]] = []
        if filter_file_ids:
            filters.append({"terms": {"metadata.document_id": filter_file_ids}})
        query: dict[str, Any] = {"bool": {"must": [text_query]}}
        if filters:
            query["bool"]["filter"] = filters
        try:
            es_vector = await KnowledgeRag.init_knowledge_es_vectorstore(knowledge=spaces[0])
            es_result = await es_vector.client.search(
                index=index_names,
                body={
                    "query": query,
                    "size": limit,
                    "_source": [
                        "text",
                        "metadata",
                    ],
                },
            )
        except Exception as exc:
            logger.warning("skip shougang portal semantic es search: keyword={} error={}", keyword, exc)
            return []

        hits = ((es_result.get("hits") or {}).get("hits") or [])[:limit]
        chunks: list[PortalSearchChunk] = []
        allowed_file_ids = set(int(file_id) for file_id in filter_file_ids or [])
        for index, hit in enumerate(hits, start=1):
            source = hit.get("_source") or {}
            metadata = source.get("metadata") or {}
            if not isinstance(metadata, dict):
                metadata = {}
            chunk = self._build_shougang_portal_search_chunk(
                content=str(source.get("text") or ""),
                metadata=metadata,
                retriever="es",
                rank=index,
                score=float(hit.get("_score") or 0.0),
                source=str(metadata.get("source") or hit.get("_index") or ""),
            )
            if chunk is None:
                continue
            if allowed_file_ids and chunk.file_id not in allowed_file_ids:
                continue
            chunks.append(chunk)
        return chunks

    async def _search_shougang_portal_vector_chunks(
        self,
        *,
        spaces: list[Knowledge],
        keyword: str,
        filter_file_ids: list[int] | None,
        limit: int = PORTAL_SEARCH_VECTOR_RECALL_LIMIT,
    ) -> list[PortalSearchChunk]:
        if not keyword or not spaces:
            return []
        spaces_by_model = self._group_shougang_portal_spaces_by_embedding_model(spaces)
        if not spaces_by_model:
            return []
        results = await asyncio.gather(
            *[
                self._search_shougang_portal_vector_chunks_for_model(
                    model_id=model_id,
                    spaces=model_spaces,
                    keyword=keyword,
                    filter_file_ids=filter_file_ids,
                    limit=limit,
                )
                for model_id, model_spaces in spaces_by_model.items()
            ],
            return_exceptions=True,
        )
        chunks: list[PortalSearchChunk] = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning("skip shougang portal semantic vector search: keyword={} error={}", keyword, result)
                continue
            chunks.extend(result)
        chunks.sort(key=lambda chunk: chunk.score, reverse=True)
        chunks = chunks[:limit]
        for index, chunk in enumerate(chunks, start=1):
            chunk.rank = index
        return chunks

    @staticmethod
    def _group_shougang_portal_spaces_by_embedding_model(
        spaces: list[Knowledge],
    ) -> dict[str, list[Knowledge]]:
        spaces_by_model: dict[str, list[Knowledge]] = {}
        for space in spaces:
            model_id = str(getattr(space, "model", "") or "").strip()
            if not model_id:
                logger.warning(
                    "skip shougang portal vector search: space_id={} missing embedding model",
                    space.id,
                )
                continue
            spaces_by_model.setdefault(model_id, []).append(space)
        return spaces_by_model

    async def _search_shougang_portal_vector_chunks_for_model(
        self,
        *,
        model_id: str,
        spaces: list[Knowledge],
        keyword: str,
        filter_file_ids: list[int] | None,
        limit: int,
    ) -> list[PortalSearchChunk]:
        try:
            embedding_model = await LLMService.get_bisheng_knowledge_embedding(
                model_id=int(model_id),
                invoke_user_id=self.login_user.user_id,
            )
            query_embedding = await asyncio.to_thread(embedding_model.embed_query, keyword)
        except Exception as exc:
            logger.warning(
                "skip shougang portal semantic vector search: keyword={} model_id={} error={}",
                keyword,
                model_id,
                exc,
            )
            return []

        results = await asyncio.gather(
            *[
                self._search_shougang_portal_vector_chunks_for_space(
                    space=space,
                    keyword=keyword,
                    embedding_model=embedding_model,
                    query_embedding=query_embedding,
                    filter_file_ids=filter_file_ids,
                    limit=limit,
                )
                for space in spaces
            ],
            return_exceptions=True,
        )
        chunks: list[PortalSearchChunk] = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning("skip shougang portal semantic vector search: keyword={} error={}", keyword, result)
                continue
            chunks.extend(result)
        return chunks

    async def _search_shougang_portal_vector_chunks_for_space(
        self,
        *,
        space: Knowledge,
        keyword: str,
        embedding_model: Any,
        query_embedding: list[float],
        filter_file_ids: list[int] | None,
        limit: int,
    ) -> list[PortalSearchChunk]:
        try:
            if not space.collection_name:
                logger.warning(
                    "skip shougang portal semantic vector search: space_id={} missing collection",
                    space.id,
                )
                return []
            vectorstore = KnowledgeRag.init_milvus_vectorstore(
                space.collection_name,
                embedding_model,
            )
            search_kwargs: dict[str, Any] = {
                "k": limit,
                "param": {"ef": max(110, limit + 10)},
            }
            if filter_file_ids:
                search_kwargs["expr"] = f"document_id in {filter_file_ids}"
            docs_with_score = await vectorstore.asimilarity_search_with_relevance_scores_by_vector(
                query_embedding,
                **search_kwargs,
            )
        except Exception as exc:
            logger.warning(
                "skip shougang portal semantic vector search: keyword={} space_id={} error={}",
                keyword,
                space.id,
                exc,
            )
            return []

        chunks: list[PortalSearchChunk] = []
        allowed_file_ids = set(int(file_id) for file_id in filter_file_ids or [])
        for index, (doc, score) in enumerate(docs_with_score, start=1):
            metadata = dict(doc.metadata or {})
            chunk = self._build_shougang_portal_search_chunk(
                content=str(doc.page_content or ""),
                metadata=metadata,
                retriever="vector",
                rank=index,
                score=float(score or 0.0),
                source=str(metadata.get("source") or space.collection_name or ""),
                fallback_knowledge_id=int(space.id),
            )
            if chunk is None:
                continue
            if allowed_file_ids and chunk.file_id not in allowed_file_ids:
                continue
            chunks.append(chunk)
        return chunks

    def _build_shougang_portal_search_chunk(
        self,
        *,
        content: str,
        metadata: dict[str, Any],
        retriever: str,
        rank: int,
        score: float,
        source: str,
        fallback_knowledge_id: int = 0,
    ) -> PortalSearchChunk | None:
        file_id = self._coerce_shougang_portal_int(metadata.get("document_id") or metadata.get("file_id"))
        if not file_id:
            return None
        knowledge_id = self._coerce_shougang_portal_int(metadata.get("knowledge_id")) or fallback_knowledge_id
        return PortalSearchChunk(
            file_id=file_id,
            knowledge_id=knowledge_id,
            content=content,
            source=source,
            retriever=retriever,
            rank=rank,
            score=score,
            metadata=metadata,
        )

    @staticmethod
    def _coerce_shougang_portal_int(value: Any) -> int:
        try:
            result = int(value)
        except (TypeError, ValueError):
            return 0
        return result if result > 0 else 0

    def _group_shougang_portal_chunks_by_file(
        self,
        chunks: list[Any],
    ) -> dict[int, PortalFileCandidate]:
        candidates: dict[int, PortalFileCandidate] = {}
        for chunk in chunks:
            file_id = int(getattr(chunk, "file_id", 0) or 0)
            if file_id <= 0:
                continue
            knowledge_id = int(getattr(chunk, "knowledge_id", 0) or 0)
            candidate = candidates.setdefault(
                file_id,
                PortalFileCandidate(file_id=file_id, knowledge_id=knowledge_id),
            )
            if not candidate.knowledge_id and knowledge_id:
                candidate.knowledge_id = knowledge_id
            candidate.chunks.append(chunk)
            retriever = str(getattr(chunk, "retriever", "") or "")
            rank = int(getattr(chunk, "rank", 0) or 0)
            score = float(getattr(chunk, "score", 0.0) or 0.0)
            if retriever == "es" and rank > 0:
                if candidate.es_best_rank is None or rank < candidate.es_best_rank:
                    candidate.es_best_rank = rank
                    candidate.es_best_score = score
            elif retriever == "vector" and rank > 0:
                if candidate.vector_best_rank is None or rank < candidate.vector_best_rank:
                    candidate.vector_best_rank = rank
                    candidate.vector_best_score = score
        return candidates

    def _score_shougang_portal_file_candidates(
        self,
        candidates: dict[int, PortalFileCandidate],
    ) -> list[PortalFileCandidate]:
        for candidate in candidates.values():
            score = 0.0
            if candidate.es_best_rank is not None:
                score += PORTAL_SEARCH_ES_WEIGHT / (PORTAL_SEARCH_RRF_K + candidate.es_best_rank)
            if candidate.vector_best_rank is not None:
                score += PORTAL_SEARCH_VECTOR_WEIGHT / (PORTAL_SEARCH_RRF_K + candidate.vector_best_rank)
            candidate.fusion_score = score
        return sorted(
            candidates.values(),
            key=lambda candidate: (
                candidate.fusion_score,
                -(candidate.es_best_rank or 10_000),
                -(candidate.vector_best_rank or 10_000),
                -candidate.file_id,
            ),
            reverse=True,
        )

    def _score_shougang_portal_candidate_title_matches(
        self,
        *,
        keyword: str,
        candidates: list[PortalFileCandidate],
        file_map: dict[int, KnowledgeFile],
    ) -> None:
        for candidate in candidates:
            file = file_map.get(candidate.file_id)
            tier, score, reason = self._compute_shougang_portal_title_match(
                keyword,
                str(getattr(file, "file_name", "") or ""),
            )
            candidate.title_match_tier = tier
            candidate.title_match_score = score
            candidate.title_match_reason = reason

    @classmethod
    def _compute_shougang_portal_title_match(
        cls,
        keyword: str,
        file_name: str,
    ) -> tuple[int, float, str]:
        title_text = cls._strip_shougang_portal_file_extension(file_name)
        query_compact = cls._compact_shougang_portal_title_match_text(keyword)
        title_compact = cls._compact_shougang_portal_title_match_text(title_text)
        if not query_compact or not title_compact:
            return 0, 0.0, ""
        if title_compact == query_compact:
            return 4, 1.0, "exact"
        if query_compact in title_compact:
            return 3, 0.95, "query_phrase"

        cleaned_query = cls._remove_shougang_portal_title_match_stopwords(query_compact)
        if len(cleaned_query) >= 2 and cleaned_query != query_compact:
            if title_compact == cleaned_query:
                return 4, 1.0, "cleaned_exact"
            if cleaned_query in title_compact:
                return 3, 0.95, "cleaned_query_phrase"

        if len(title_compact) >= 4 and title_compact in query_compact:
            return 3, 0.9, "title_phrase"

        query_units = cls._build_shougang_portal_title_match_units(cleaned_query or query_compact)
        if not query_units:
            return 0, 0.0, ""
        matched_units = [unit for unit in query_units if unit in title_compact]
        matched_count = len(matched_units)
        coverage = matched_count / len(query_units)
        if matched_count >= 3 and coverage >= 0.5:
            return (
                2,
                round(min(0.89, coverage + matched_count / 1000), 6),
                (f"unit_coverage:{matched_count}/{len(query_units)}"),
            )
        if matched_count >= 2 and coverage >= 0.75:
            return (
                2,
                round(min(0.89, coverage + matched_count / 1000), 6),
                (f"unit_coverage:{matched_count}/{len(query_units)}"),
            )
        return 0, 0.0, ""

    @staticmethod
    def _strip_shougang_portal_file_extension(file_name: str) -> str:
        name = str(file_name or "").strip()
        return Path(name).stem or name

    @staticmethod
    def _compact_shougang_portal_title_match_text(text: str) -> str:
        return re.sub(r"[\W_]+", "", str(text or "").lower(), flags=re.UNICODE)

    @staticmethod
    def _remove_shougang_portal_title_match_stopwords(text: str) -> str:
        cleaned = str(text or "")
        for word in PORTAL_SEARCH_TITLE_MATCH_STOPWORDS:
            if len(cleaned) > len(word):
                cleaned = cleaned.replace(word, "")
        return cleaned

    @staticmethod
    def _build_shougang_portal_title_match_units(text: str) -> list[str]:
        units: list[str] = []
        for segment in re.findall(r"[\u4e00-\u9fff]+|[a-z0-9]+", str(text or "").lower()):
            if not segment:
                continue
            if re.fullmatch(r"[\u4e00-\u9fff]+", segment):
                if len(segment) <= 2:
                    units.append(segment)
                    continue
                units.extend(segment[index : index + 2] for index in range(len(segment) - 1))
                continue
            if len(segment) >= 2:
                units.append(segment)
        return list(dict.fromkeys(units))

    async def _rerank_shougang_portal_file_candidates(
        self,
        *,
        keyword: str,
        candidates: list[PortalFileCandidate],
        file_map: dict[int, KnowledgeFile],
        rerank_model_id: str | None = None,
        rerank_model_id_provided: bool = False,
    ) -> list[PortalFileCandidate]:
        model_id = self._resolve_shougang_portal_rerank_model_id(
            rerank_model_id,
            request_model_id_provided=rerank_model_id_provided,
        )
        perf = _get_portal_search_perf()
        if perf is not None:
            perf.rerank_model_id = model_id
        if not model_id or not candidates:
            return candidates
        try:
            if perf is not None:
                perf.rerank_attempted = True
            rerank_model = await LLMService.get_bisheng_rerank(model_id=int(model_id))
            documents = [
                Document(
                    page_content=self._get_shougang_portal_candidate_rerank_text(candidate, file_map),
                    metadata={
                        "file_id": candidate.file_id,
                        "knowledge_id": candidate.knowledge_id,
                        "fusion_score": candidate.fusion_score,
                    },
                )
                for candidate in candidates
            ]
            reranked_docs = await rerank_model.acompress_documents(documents=documents, query=keyword)
        except Exception as exc:
            if perf is not None:
                perf.rerank_error = type(exc).__name__
            logger.warning("skip shougang portal semantic rerank: keyword={} error={}", keyword, exc)
            return candidates

        if not reranked_docs:
            return candidates
        if perf is not None:
            perf.rerank_enabled = True
        candidate_map = {candidate.file_id: candidate for candidate in candidates}
        for doc in reranked_docs:
            file_id = self._coerce_shougang_portal_int((doc.metadata or {}).get("file_id"))
            candidate = candidate_map.get(file_id)
            if not candidate:
                continue
            try:
                candidate.rerank_score = float((doc.metadata or {}).get("relevance_score"))
            except (TypeError, ValueError):
                candidate.rerank_score = None
        return candidates

    @staticmethod
    def _resolve_shougang_portal_rerank_model_id(
        request_model_id: str | None = None,
        *,
        request_model_id_provided: bool = False,
    ) -> str:
        if request_model_id_provided:
            return str(request_model_id or "").strip()
        request_model_id = str(request_model_id or "").strip()
        if request_model_id:
            return request_model_id
        env_model_id = os.getenv(PORTAL_SEARCH_RERANK_MODEL_ID_ENV, "").strip()
        if env_model_id:
            return env_model_id
        return str(PORTAL_SEARCH_RERANK_MODEL_ID or "").strip()

    @staticmethod
    def _is_pydantic_field_set(model: BaseModel, field_name: str) -> bool:
        fields_set = getattr(model, "model_fields_set", None)
        if fields_set is None:
            fields_set = getattr(model, "__fields_set__", set())
        return field_name in fields_set

    def _get_shougang_portal_candidate_rerank_text(
        self,
        candidate: PortalFileCandidate,
        file_map: dict[int, KnowledgeFile],
    ) -> str:
        chunks = sorted(
            candidate.chunks,
            key=lambda chunk: (
                0 if str(getattr(chunk, "content", "") or "").strip() else 1,
                int(getattr(chunk, "rank", 10_000) or 10_000),
            ),
        )
        file = file_map.get(candidate.file_id)
        file_name = str(getattr(file, "file_name", "") or candidate.file_id)
        title_text = self._strip_shougang_portal_file_extension(file_name)
        for chunk in chunks:
            content = str(getattr(chunk, "content", "") or "").strip()
            if content:
                return f"文档名称: {title_text}\n相关内容: {content}" if title_text else content
        return f"文档名称: {title_text}" if title_text else file_name

    def _sort_shougang_portal_semantic_candidates(
        self,
        *,
        candidates: list[PortalFileCandidate],
        sort: str,
        file_map: dict[int, KnowledgeFile],
    ) -> list[PortalFileCandidate]:
        if self._is_shougang_portal_updated_at_sort(sort):
            return sorted(
                candidates,
                key=lambda candidate: self._get_shougang_portal_file_update_timestamp(file_map.get(candidate.file_id)),
                reverse=self._shougang_portal_order_sort(sort) == "desc",
            )
        return sorted(
            candidates,
            key=lambda candidate: (
                candidate.title_match_tier,
                candidate.title_match_score,
                candidate.rerank_score is not None,
                candidate.rerank_score if candidate.rerank_score is not None else float("-inf"),
                candidate.fusion_score,
                self._get_shougang_portal_file_update_timestamp(file_map.get(candidate.file_id)),
            ),
            reverse=True,
        )

    def _set_shougang_portal_search_top_result_debug(
        self,
        candidates: list[PortalFileCandidate],
        file_map: dict[int, KnowledgeFile],
    ) -> None:
        perf = _get_portal_search_perf()
        if perf is None:
            return
        top_results: list[dict[str, Any]] = []
        for index, candidate in enumerate(candidates[:5], start=1):
            file = file_map.get(candidate.file_id)
            top_results.append(
                {
                    "rank": index,
                    "file_id": candidate.file_id,
                    "knowledge_id": candidate.knowledge_id,
                    "file_name": str(getattr(file, "file_name", "") or ""),
                    "es_rank": candidate.es_best_rank,
                    "vector_rank": candidate.vector_best_rank,
                    "es_score": candidate.es_best_score,
                    "vector_score": candidate.vector_best_score,
                    "fusion_score": round(float(candidate.fusion_score or 0.0), 6),
                    "rerank_score": candidate.rerank_score,
                    "title_match_tier": candidate.title_match_tier,
                    "title_match_score": candidate.title_match_score,
                    "title_match_reason": candidate.title_match_reason,
                }
            )
        perf.top_results = top_results

    @staticmethod
    def _get_shougang_portal_file_update_timestamp(file: KnowledgeFile | None) -> float:
        value = getattr(file, "update_time", None) if file else None
        if isinstance(value, datetime):
            return value.timestamp()
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except ValueError:
                return 0.0
        return 0.0

    async def _map_shougang_portal_candidate_items(
        self,
        *,
        candidates: list[PortalFileCandidate],
        file_map: dict[int, KnowledgeFile],
        spaces: list[Knowledge],
        file_ext: str | None,
        document_type: str | None,
    ) -> list[ShougangPortalFileItemResp]:
        ordered_files = [file_map[candidate.file_id] for candidate in candidates if candidate.file_id in file_map]
        if not ordered_files:
            return []
        space_name_map = {int(space.id): str(space.name or space.id) for space in spaces}
        enriched_items = await self._handle_file_folder_extra_info(ordered_files)
        folder_path_map, source_path_map = await self._resolve_shougang_portal_source_paths(enriched_items)
        item_map: dict[int, ShougangPortalFileItemResp] = {}
        for item in enriched_items:
            space_id = int(item.get("knowledge_id") or 0)
            item["knowledge_name"] = space_name_map.get(space_id, str(space_id))
            item_id = int(item.get("id") or 0)
            item["folder_path"] = folder_path_map.get(item_id, "")
            item["source_path"] = source_path_map.get(item_id, "")
            if self._is_shougang_portal_file_item(item, file_ext, document_type):
                item_map[item_id] = self._map_shougang_portal_file_item(space_id, item)
        return [item_map[candidate.file_id] for candidate in candidates if candidate.file_id in item_map]

    @staticmethod
    def _build_shougang_portal_search_response(items: list[ShougangPortalFileItemResp]) -> dict:
        final_items = items[:PORTAL_SEARCH_FINAL_LIMIT]
        return {
            "data": [item.model_dump(mode="json") for item in final_items],
            "total": len(final_items),
            "page": 1,
            "page_size": PORTAL_SEARCH_FINAL_LIMIT,
        }

    @staticmethod
    def _build_shougang_portal_paged_response(
        items: list[ShougangPortalFileItemResp],
        page: int,
        page_size: int,
    ) -> dict:
        safe_page = max(int(page or 1), 1)
        safe_page_size = min(max(int(page_size or 20), 1), 100)
        start = (safe_page - 1) * safe_page_size
        page_items = items[start : start + safe_page_size]
        return {
            "data": [item.model_dump(mode="json") for item in page_items],
            "total": len(items),
            "page": safe_page,
            "page_size": safe_page_size,
        }

    async def _get_shougang_portal_visible_search_spaces(
        self,
        requested_space_ids: list[int],
        space_level: KnowledgeSpaceLevelEnum | None,
    ) -> list[Knowledge]:
        cache_key = self._shougang_portal_visible_space_cache_key(requested_space_ids, space_level)
        cached = await self._get_cached_shougang_portal_visible_spaces(cache_key)
        if cached is not None:
            return cached
        spaces = await self._compute_shougang_portal_visible_search_spaces(requested_space_ids, space_level)
        await self._set_cached_shougang_portal_visible_spaces(cache_key, spaces)
        return spaces

    def _shougang_portal_visible_space_cache_key(
        self,
        requested_space_ids: list[int],
        space_level: KnowledgeSpaceLevelEnum | None,
    ) -> tuple:
        tenant_id = getattr(self.login_user, "tenant_id", None) or get_current_tenant_id() or ""
        space_ids = tuple(dict.fromkeys(int(space_id) for space_id in requested_space_ids if int(space_id) > 0))
        return (
            str(tenant_id),
            str(self.login_user.user_id),
            space_ids,
            str(self._space_level_value(space_level) or ""),
        )

    async def _get_cached_shougang_portal_visible_spaces(self, cache_key: tuple) -> list[Knowledge] | None:
        try:
            async with _PORTAL_VISIBLE_SPACE_CACHE_LOCK:
                cached = _PORTAL_VISIBLE_SPACE_CACHE.get(cache_key)
                if cached is None:
                    return None
                expires_at, spaces = cached
                if expires_at <= time.monotonic():
                    _PORTAL_VISIBLE_SPACE_CACHE.pop(cache_key, None)
                    return None
                return list(spaces)
        except Exception as exc:
            logger.warning("skip shougang portal visible space cache read: error={}", exc)
            return None

    async def _set_cached_shougang_portal_visible_spaces(self, cache_key: tuple, spaces: list[Knowledge]) -> None:
        try:
            async with _PORTAL_VISIBLE_SPACE_CACHE_LOCK:
                _PORTAL_VISIBLE_SPACE_CACHE[cache_key] = (
                    time.monotonic() + _PORTAL_VISIBLE_SPACE_CACHE_TTL,
                    list(spaces),
                )
        except Exception as exc:
            logger.warning("skip shougang portal visible space cache write: error={}", exc)

    async def _compute_shougang_portal_visible_search_spaces(
        self,
        requested_space_ids: list[int],
        space_level: KnowledgeSpaceLevelEnum | None,
    ) -> list[Knowledge]:
        space_ids = await self._resolve_shougang_portal_search_space_ids(requested_space_ids, space_level)
        if not space_ids:
            return []
        spaces = await KnowledgeDao.async_get_spaces_by_ids(space_ids, order_by="update_time")
        space_map = {int(space.id): space for space in spaces if int(space.type) == KnowledgeTypeEnum.SPACE.value}
        ordered_spaces = [space_map[space_id] for space_id in space_ids if space_id in space_map]
        if not ordered_spaces:
            return []

        is_global_admin = False
        is_admin = getattr(self.login_user, "is_admin", None)
        if callable(is_admin):
            is_global_admin = bool(is_admin())

        visible_spaces: list[Knowledge] = []
        permission_checks = []
        permission_spaces: list[Knowledge] = []
        for space in ordered_spaces:
            if (
                is_global_admin
                or int(space.user_id or 0) == int(self.login_user.user_id)
                or self._is_square_preview_space(space)
            ):
                visible_spaces.append(space)
                continue
            permission_spaces.append(space)
            permission_checks.append(self._get_effective_permission_ids("knowledge_space", int(space.id)))

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
                if "view_space" in permission_result:
                    visible_spaces.append(space)
        visible_space_ids = {int(space.id) for space in visible_spaces}
        return [space for space in ordered_spaces if int(space.id) in visible_space_ids]

    async def _resolve_shougang_portal_search_space_ids(
        self,
        requested_space_ids: list[int],
        space_level: KnowledgeSpaceLevelEnum | None,
    ) -> list[int]:
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
            resolved_level = (
                scope.level
                if scope
                else (
                    KnowledgeSpaceLevelEnum.DEPARTMENT
                    if space_id in department_space_ids
                    else KnowledgeSpaceLevelEnum.PERSONAL
                )
            )
            if resolved_level == space_level:
                result.append(space_id)
        return result

    async def _get_shougang_portal_tag_file_ids(self, space_ids: list[int], tag_name: str | None) -> list[int] | None:
        if not tag_name:
            return None
        tag_map = await TagDao.aget_tags_by_business_ids(
            business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE,
            business_ids=[str(space_id) for space_id in space_ids],
            name=tag_name,
        )
        tag_ids = [int(tag.id) for tags in tag_map.values() for tag in tags if tag.id is not None]
        if not tag_ids:
            return []
        resources = await TagDao.aget_resources_by_tags(tag_ids, ResourceTypeEnum.SPACE_FILE)
        file_ids: list[int] = []
        for resource in resources:
            resource_id = str(resource.resource_id or "")
            if resource_id.isdigit():
                file_ids.append(int(resource_id))
        return list(dict.fromkeys(file_ids))

    async def _get_shougang_portal_keyword_file_ids(
        self,
        *,
        spaces: list[Knowledge],
        keyword: str | None,
        filter_file_ids: list[int] | None,
    ) -> list[int]:
        if not keyword:
            return []
        index_names = [str(space.index_name) for space in spaces if space.index_name]
        if not index_names:
            return []
        query: dict = {"match_phrase": {"text": keyword}}
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
            es_result = await es_vector.client.search(
                index=index_names,
                body={
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
                },
            )
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

    async def _filter_shougang_portal_visible_files(
        self,
        files: list[KnowledgeFile],
        *,
        spaces: list[Knowledge] | None = None,
    ) -> list[KnowledgeFile]:
        grouped_files: dict[int, list[KnowledgeFile]] = {}
        for file in files:
            grouped_files.setdefault(int(file.knowledge_id), []).append(file)

        public_space_ids = await self._get_shougang_portal_public_space_ids(
            list(grouped_files.keys()),
            spaces=spaces,
        )
        visible_files: list[KnowledgeFile] = []
        for space_id, items in grouped_files.items():
            if space_id in public_space_ids:
                visible_files.extend(items)
                _increment_portal_search_perf("fast_path_public_space_count", len(items))
                continue
            try:
                visible_files.extend(await self._filter_visible_child_items(items, space_id=space_id))
            except Exception as exc:
                logger.warning("skip shougang portal file visibility check: space_id={} error={}", space_id, exc)
        return visible_files

    async def _get_shougang_portal_public_space_ids(
        self,
        space_ids: list[int],
        *,
        spaces: list[Knowledge] | None = None,
    ) -> set[int]:
        unique_space_ids = list(dict.fromkeys(int(space_id) for space_id in space_ids if int(space_id) > 0))
        if not unique_space_ids:
            return set()

        unresolved = set(unique_space_ids)
        public_space_ids: set[int] = set()
        for space in spaces or []:
            space_id = int(space.id)
            if space_id not in unresolved:
                continue
            space_level = getattr(space, "space_level", None)
            if self._space_level_value(space_level) == KnowledgeSpaceLevelEnum.PUBLIC.value:
                public_space_ids.add(space_id)
                unresolved.discard(space_id)
            elif space_level is not None:
                unresolved.discard(space_id)

        if unresolved:
            try:
                scopes = await KnowledgeSpaceScopeDao.aget_map_by_space_ids(list(unresolved))
            except Exception as exc:
                logger.warning("skip shougang portal public fast path scope lookup: error={}", exc)
                return public_space_ids
            for space_id in unresolved:
                scope = scopes.get(space_id)
                if scope and self._space_level_value(scope.level) == KnowledgeSpaceLevelEnum.PUBLIC.value:
                    public_space_ids.add(space_id)
        return public_space_ids

    @staticmethod
    def _space_level_value(space_level: Any) -> Any:
        return getattr(space_level, "value", space_level)

    async def _get_shougang_portal_tag_ids(self, space_id: int, tag_name: str | None) -> list[int] | None:
        if not tag_name:
            return None
        tags = await TagDao.get_tags_by_business(
            business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE,
            business_id=str(space_id),
            name=tag_name,
        )
        return [int(tag.id) for tag in tags if tag.id is not None]

    def _is_shougang_portal_file_item(
        self,
        item: dict,
        file_ext: str | None,
        document_type: str | None = None,
    ) -> bool:
        if int(item.get("file_type", -1)) != FileType.FILE.value:
            return False
        file_name = str(item.get("file_name") or "")
        if file_ext and self._get_file_ext(file_name) != file_ext.strip().lower().lstrip("."):
            return False
        normalized_document_type = self._normalize_shougang_document_type_code(document_type)
        if normalized_document_type and self._get_shougang_document_type_code(item) != normalized_document_type:
            return False
        return True

    def _map_shougang_portal_file_item(self, space_id: int, item: dict) -> ShougangPortalFileItemResp:
        file_name = str(item.get("file_name") or "")
        tag_infos = [
            {
                "tag_name": str(tag.get("name")),
                "resource_type": str(tag.get("resource_type") or ""),
            }
            for tag in item.get("tags") or []
            if isinstance(tag, dict) and tag.get("name")
        ]
        return ShougangPortalFileItemResp(
            id=int(item.get("id") or 0),
            space_id=space_id,
            title=Path(file_name).stem or file_name,
            summary=str(item.get("abstract") or ""),
            source=str(item.get("knowledge_name") or item.get("space_name") or space_id),
            updated_at=self._serialize_datetime(item.get("update_time")),
            tags=[tag["tag_name"] for tag in tag_infos],
            tag_infos=tag_infos,
            file_ext=self._get_file_ext(file_name),
            file_size=str(item.get("file_size") or ""),
            file_encoding=str(
                item.get("file_encoding")
                or item.get("fileEncoding")
                or item.get("document_code")
                or item.get("file_no")
                or ""
            ),
            folder_path=str(item.get("folder_path") or ""),
            source_path=str(item.get("source_path") or ""),
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
        items: list[ShougangPortalFileItemResp],
        sort: str,
        keyword: str | None,
    ) -> list[ShougangPortalFileItemResp]:
        if KnowledgeSpaceService._shougang_portal_order_sort(sort) == "asc":
            return sorted(items, key=lambda item: item.updated_at)
        if KnowledgeSpaceService._is_shougang_portal_updated_at_sort(sort) or not keyword:
            return sorted(items, key=lambda item: item.updated_at, reverse=True)
        keyword_lower = keyword.lower()

        def score(item: ShougangPortalFileItemResp) -> tuple[int, str]:
            title = item.title.lower()
            summary = item.summary.lower()
            tags = [
                tag_text.lower()
                for tag_text in (KnowledgeSpaceService._shougang_portal_tag_text(tag) for tag in item.tags)
                if tag_text
            ]
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

    @staticmethod
    def _is_shougang_portal_updated_at_sort(sort: str) -> bool:
        return sort in {"updated_at", "updated_at_desc", "updated_at_asc"}

    @staticmethod
    def _shougang_portal_order_sort(sort: str) -> str:
        return "asc" if sort == "updated_at_asc" else "desc"

    @staticmethod
    def _normalize_shougang_document_type_code(value: Any) -> str:
        return str(value or "").strip().upper()

    @classmethod
    def _filter_shougang_portal_files_by_document_type(
        cls,
        files: list[KnowledgeFile],
        document_type: str | None,
    ) -> list[KnowledgeFile]:
        normalized = cls._normalize_shougang_document_type_code(document_type)
        if not normalized:
            return files
        return [file for file in files if cls._get_shougang_document_type_code(file) == normalized]

    @classmethod
    def _get_shougang_document_type_code(cls, item: Any) -> str:
        if isinstance(item, dict):
            file_encoding = str(
                item.get("file_encoding")
                or item.get("fileEncoding")
                or item.get("document_code")
                or item.get("file_no")
                or ""
            )
        else:
            file_encoding = str(getattr(item, "file_encoding", "") or "")
        parts = [part.strip() for part in file_encoding.split("-")]
        if len(parts) < 2:
            return ""
        return cls._normalize_shougang_document_type_code(parts[1])

    @staticmethod
    def _shougang_portal_tag_text(tag: Any) -> str:
        if isinstance(tag, str):
            return tag
        if isinstance(tag, dict):
            return str(tag.get("tag_name") or tag.get("name") or "")
        return str(getattr(tag, "tag_name", None) or getattr(tag, "name", None) or "")

    async def delete_space(self, space_id: int) -> None:
        space = await KnowledgeDao.aquery_by_id(space_id)
        if not space or space.type != KnowledgeTypeEnum.SPACE.value:
            raise SpaceNotFoundError()
        if getattr(space, "is_favorite", False):
            raise FavoriteSpaceProtectedError()
        await self._require_permission_id("knowledge_space", space_id, "delete_space")
        child_resources = await self._list_space_child_resources(space_id)
        original_members = await SpaceChannelMemberDao.async_get_members_by_space(space_id)
        original_member_ids = [member.user_id for member in original_members]

        # Cleaned vectorData in
        await asyncio.to_thread(KnowledgeService.delete_knowledge_file_in_vector, space)

        # CleanedminioData
        await asyncio.to_thread(KnowledgeService.delete_knowledge_file_in_minio, space_id)

        await KnowledgeDao.async_delete_knowledge(knowledge_id=space_id)
        await KnowledgeSpaceContentStat.enqueue_space_delete_stat_async(space_id)
        await self._send_space_event_notification(
            action_code=SPACE_DELETED_MESSAGE,
            receiver_user_ids=original_member_ids,
            space_id=space_id,
            space_name=space.name,
            navigable=False,
        )

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
        await self._cleanup_resource_tuples(child_resources + [("knowledge_space", space_id)])

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
        await KnowledgeAuditTelemetryService.audit_delete_knowledge_space(self.login_user, self.request, space)
        KnowledgeAuditTelemetryService.telemetry_delete_knowledge(self.login_user)
        return

    async def update_knowledge_space(
        self,
        space_id: int,
        name: str | None = None,
        description: str | None = None,
        icon: str | None = None,
        auth_type: AuthTypeEnum | None = None,
        is_released: bool = False,
        auto_tag_enabled: bool | None = None,
        auto_tag_library_id: int | None = None,
        auto_tag_library_ids: list[int] | None = None,
        auto_tag_custom_tags: list[str] | None = None,
    ) -> Knowledge:
        """Modify an existing knowledge space."""
        space = await KnowledgeDao.aquery_by_id(space_id)
        if not space or space.type != KnowledgeTypeEnum.SPACE.value:
            raise SpaceNotFoundError()
        if getattr(space, "is_favorite", False):
            raise FavoriteSpaceProtectedError()

        await self._require_permission_id("knowledge_space", space_id, "edit_space")

        old_auth_type = space.auth_type
        normalized_name = self._normalize_space_name(name) if name is not None else None
        name_changed = normalized_name is not None and normalized_name != space.name

        if name_changed:
            scope = await KnowledgeSpaceScopeDao.aget_by_space_id(space_id)
            if scope is None:
                raise SpaceInvalidScopeOwnerError(msg="Knowledge space scope does not exist")
            await self._ensure_space_name_unique_in_scope(
                name=normalized_name,
                level=scope.level,
                owner_type=scope.owner_type,
                owner_id=int(scope.owner_id),
                exclude_id=space_id,
                tenant_id=int(scope.tenant_id or space.tenant_id or self.login_user.tenant_id),
            )
        if normalized_name is not None:
            space.name = normalized_name
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
            or auto_tag_library_ids is not None
            or auto_tag_custom_tags is not None
        )
        if auto_tag_touched:
            desired_enabled = space.auto_tag_enabled if auto_tag_enabled is None else auto_tag_enabled
            desired_library_id = auto_tag_library_id
            desired_library_ids = auto_tag_library_ids
            desired_custom_tags = auto_tag_custom_tags
            if (
                desired_enabled
                and desired_library_id is None
                and desired_library_ids is None
                and desired_custom_tags is None
            ):
                desired_library_ids = await KnowledgeTagLibraryLinkDao.alist_library_ids_by_knowledge(space.id)
                if not desired_library_ids and space.auto_tag_library_id:
                    desired_library_ids = [space.auto_tag_library_id]

            resolved_enabled, resolved_library_id = await self._apply_auto_tag_binding(
                knowledge=space,
                auto_tag_enabled=desired_enabled,
                auto_tag_library_id=desired_library_id,
                auto_tag_library_ids=desired_library_ids,
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
        if old_auth_type != AuthTypeEnum.PRIVATE and new_auth_type == AuthTypeEnum.PRIVATE:
            removed_members = await SpaceChannelMemberDao.async_get_members_by_space(space_id)
            removed_user_ids = [
                member.user_id for member in removed_members if member.user_role != UserRoleEnum.CREATOR
            ]
            child_resources = await self._list_space_child_resources(space_id)
            await self.__class__.clear_space_authorization_for_private(
                space=space,
                child_resources=child_resources,
            )
            await SpaceChannelMemberDao.async_delete_non_creator_members(space_id)
            final_removed_user_ids = []
            for user_id in removed_user_ids:
                if not await self._user_can_read_space(user_id, space_id):
                    final_removed_user_ids.append(user_id)
            await self._send_space_event_notification(
                action_code=SPACE_MADE_PRIVATE_MESSAGE,
                receiver_user_ids=final_removed_user_ids,
                space_id=space_id,
                space_name=space.name,
                navigable=False,
            )
        elif old_auth_type == AuthTypeEnum.APPROVAL and new_auth_type == AuthTypeEnum.PUBLIC:
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

    async def _format_member_spaces(self, members: list[SpaceChannelMember], order_by: str) -> list[KnowledgeRead]:
        if not members:
            return []

        members_map = {int(one.business_id): one for one in members}
        res = await KnowledgeDao.async_get_spaces_by_ids(list(members_map.keys()), order_by)
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

    async def get_my_created_spaces(self, order_by: str = "update_time") -> list[KnowledgeRead]:
        members = await SpaceChannelMemberDao.async_get_user_created_members(self.login_user.user_id)
        if members:
            department_space_ids = set(
                (
                    await DepartmentKnowledgeSpaceDao.aget_department_ids_by_space_ids(
                        [int(member.business_id) for member in members]
                    )
                ).keys()
            )
            members = [member for member in members if int(member.business_id) not in department_space_ids]
        return await self._format_member_spaces(members, order_by)

    async def get_my_managed_spaces(self, order_by: str = "name") -> list[KnowledgeRead]:
        members = await SpaceChannelMemberDao.async_get_user_managed_members(self.login_user.user_id)
        accessible_ids = await PermissionService.list_accessible_ids(
            user_id=self.login_user.user_id,
            relation="can_manage",
            object_type="knowledge_space",
            login_user=self.login_user,
        )
        space_ids = {int(member.business_id) for member in members}
        if accessible_ids is not None:
            space_ids |= {int(space_id) for space_id in accessible_ids if str(space_id).isdigit()}
        return await self._format_accessible_spaces(
            list(space_ids),
            order_by,
            memberships=members,
            required_permission_id="manage_space_relation",
        )

    async def get_my_followed_spaces(self, order_by: str = "update_time") -> list[KnowledgeRead]:
        """
        Return the spaces the current user follows (non-creator).
        Pinned spaces always appear first; within each pinned/non-pinned group
        the caller-specified order_by is applied.
        """
        # Fetch members ordered by is_pinned DESC so we know which are pinned
        members = await SpaceChannelMemberDao.async_get_user_followed_members(self.login_user.user_id)
        accessible_ids = await PermissionService.list_accessible_ids(
            user_id=self.login_user.user_id,
            relation="can_read",
            object_type="knowledge_space",
            login_user=self.login_user,
        )
        space_ids = {int(member.business_id) for member in members}
        if accessible_ids is not None:
            space_ids |= {int(space_id) for space_id in accessible_ids if str(space_id).isdigit()}
        return await self._format_accessible_spaces(
            list(space_ids),
            order_by,
            memberships=members,
            exclude_created=True,
            required_permission_id="view_space",
        )

    async def _list_accessible_spaces(
        self,
        order_by: str = "update_time",
    ) -> list[KnowledgeRead]:
        members = await SpaceChannelMemberDao.async_get_user_space_members(self.login_user.user_id)
        space_ids = {int(member.business_id) for member in members if str(member.business_id).isdigit()}
        created_ids, accessible_ids, public_space_ids = await asyncio.gather(
            KnowledgeDao.aget_knowledge_ids_created_by(
                self.login_user.user_id,
                KnowledgeTypeEnum.SPACE,
            ),
            PermissionService.list_accessible_ids(
                user_id=self.login_user.user_id,
                relation="can_read",
                object_type="knowledge_space",
                login_user=self.login_user,
            ),
            KnowledgeSpaceScopeDao.aget_space_ids_by_level(KnowledgeSpaceLevelEnum.PUBLIC),
        )
        space_ids.update(int(space_id) for space_id in created_ids)
        space_ids.update(int(space_id) for space_id in public_space_ids)
        if accessible_ids is None:
            all_space_ids = await KnowledgeDao.aget_knowledge_ids_by_type(KnowledgeTypeEnum.SPACE)
            space_ids.update(all_space_ids)
        else:
            space_ids.update(int(space_id) for space_id in accessible_ids if str(space_id).isdigit())

        return await self._format_accessible_spaces(
            list(space_ids),
            order_by,
            memberships=members,
            required_permission_id="view_space",
        )

    async def get_grouped_spaces(
        self,
        order_by: str = "update_time",
    ) -> GroupedKnowledgeSpacesResp:
        spaces = await self._list_accessible_spaces(order_by)
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

    async def get_spaces_by_level(
        self,
        space_level: KnowledgeSpaceLevelEnum | str,
        order_by: str = "update_time",
    ) -> list[KnowledgeRead]:
        target_level = self._normalize_space_level(space_level)
        favorite_space_id: int | None = None
        if target_level == KnowledgeSpaceLevelEnum.PERSONAL:
            favorite_space = await self._ensure_favorite_space()
            favorite_space_id = int(favorite_space.id)

        spaces = await self._list_accessible_spaces(order_by)
        result = [space for space in spaces if space.space_level == target_level]

        if favorite_space_id is not None:
            for space in result:
                if int(space.id) == favorite_space_id:
                    space.is_favorite = True
            result.sort(key=lambda space: not bool(getattr(space, "is_favorite", False)))

        return result

    async def global_search_files(
        self,
        keyword: str,
        page: int = 1,
        page_size: int = 30,
    ) -> dict:
        """Search files by name across all spaces the user can access.

        Returns tree-structured results grouped by space level then space, with
        resolved folder paths for each matching file.
        """
        grouped = await self.get_grouped_spaces()
        all_spaces: list[KnowledgeRead] = (
            grouped.public_spaces + grouped.department_spaces + grouped.team_spaces + grouped.personal_spaces
        )
        if not all_spaces:
            return {"total": 0, "page": page, "page_size": page_size, "data": []}

        space_id_list = [int(space.id) for space in all_spaces]
        space_by_id = {int(space.id): space for space in all_spaces}

        files = await KnowledgeFileDao.aget_file_by_space_filters(
            space_id_list,
            file_name=keyword.strip() if keyword else None,
            status=[KnowledgeFileStatus.SUCCESS.value],
        )
        # Only keep actual files (not folders)
        files = [f for f in files if int(f.file_type) != FileType.DIR.value]

        total = len(files)
        start = (page - 1) * page_size
        page_files = files[start : start + page_size]

        # Resolve folder paths in bulk
        folder_ids: set[int] = set()
        for f in page_files:
            for part in (f.file_level_path or "").split("/"):
                if part:
                    folder_ids.add(int(part))

        folder_name_map: dict[int, str] = {}
        if folder_ids:
            folders = await KnowledgeFileDao.aget_file_by_ids(list(folder_ids))
            folder_name_map = {
                int(fd.id): str(fd.file_name or "") for fd in folders if int(fd.file_type) == FileType.DIR.value
            }

        # Build flat list of results enriched with space/folder info
        level_order = {
            KnowledgeSpaceLevelEnum.PUBLIC: 0,
            KnowledgeSpaceLevelEnum.DEPARTMENT: 1,
            KnowledgeSpaceLevelEnum.TEAM: 2,
            KnowledgeSpaceLevelEnum.PERSONAL: 3,
        }
        level_labels = {
            KnowledgeSpaceLevelEnum.PUBLIC: "公共知识库",
            KnowledgeSpaceLevelEnum.DEPARTMENT: "部门知识库",
            KnowledgeSpaceLevelEnum.TEAM: "团队知识库",
            KnowledgeSpaceLevelEnum.PERSONAL: "个人知识库",
        }

        result_items = []
        for f in page_files:
            space = space_by_id.get(int(f.knowledge_id))
            if not space:
                continue
            level = space.space_level or KnowledgeSpaceLevelEnum.PERSONAL
            folder_segments: list[str] = []
            for part in (f.file_level_path or "").split("/"):
                if part:
                    name = folder_name_map.get(int(part))
                    if name:
                        folder_segments.append(name)
            result_items.append(
                {
                    "file_id": f.id,
                    "file_name": f.file_name,
                    "file_type_ext": (f.file_name or "").rsplit(".", 1)[-1].lower()
                    if "." in (f.file_name or "")
                    else "",
                    "space_id": int(f.knowledge_id),
                    "space_name": space.name or "",
                    "space_level": str(level.value) if isinstance(level, KnowledgeSpaceLevelEnum) else str(level),
                    "space_level_label": level_labels.get(level, str(level)),
                    "space_level_order": level_order.get(level, 99),
                    "folder_path": folder_segments,
                }
            )

        result_items.sort(key=lambda x: (x["space_level_order"], x["space_name"], x["folder_path"], x["file_name"]))
        return {"total": total, "page": page, "page_size": page_size, "data": result_items}

    async def get_authorized_space_options(
        self,
        keyword: str = "",
        page: int = 1,
        page_size: int = 20,
        order_by: str = "name",
    ) -> dict:
        """Return spaces the current user can use in workflow selectors."""
        grouped = await self.get_grouped_spaces(order_by=order_by)
        spaces = grouped.public_spaces + grouped.department_spaces + grouped.team_spaces + grouped.personal_spaces
        normalized_keyword = (keyword or "").strip().lower()
        if normalized_keyword:
            spaces = [space for space in spaces if normalized_keyword in (space.name or "").lower()]

        total = len(spaces)
        start = max(page - 1, 0) * page_size
        end = start + page_size
        return {
            "data": spaces[start:end],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": end < total,
        }

    async def pin_space(self, space_id: int, is_pinned: bool = True) -> bool:
        return await SpaceChannelMemberDao.pin_space_id(space_id, self.login_user.user_id, is_pinned)

    async def get_knowledge_square(self, keyword: str = None, page: int = 1, page_size: int = 20) -> dict:
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
        creator_users_task = UserDao.aget_user_by_ids(creator_ids) if creator_ids else None
        if self.login_user.is_admin():
            if creator_users_task:
                creator_users, success_file_map = await asyncio.gather(
                    creator_users_task,
                    KnowledgeFileDao.async_count_success_files_batch(space_ids_int),
                )
            else:
                creator_users = []
                success_file_map = await KnowledgeFileDao.async_count_success_files_batch(space_ids_int)
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
            row[0].id: self._resolve_subscription_status_from_fields(row[1], row[2]) for row in rows
        }
        square_members = await SpaceChannelMemberDao.async_get_all_members_for_spaces(
            self.login_user.user_id,
            [str(space_id) for space_id in space_ids_int],
        )
        square_member_map = {
            int(member.business_id): member for member in square_members if str(member.business_id).isdigit()
        }
        readable_space_id_set = set()
        readable_space_with_view_permission = set()
        if readable_space_ids is not None:
            readable_space_id_set = {int(space_id) for space_id in readable_space_ids if str(space_id).isdigit()}
        readable_candidates = [
            space_id
            for space_id in readable_space_id_set
            if resolved_subscription_status.get(space_id) != SpaceSubscriptionStatusEnum.SUBSCRIBED
        ]
        if readable_candidates:
            effective_permission_ids = await asyncio.gather(
                *[self._get_effective_permission_ids("knowledge_space", space_id) for space_id in readable_candidates]
            )
            readable_space_with_view_permission = {
                space_id
                for space_id, permission_ids in zip(readable_candidates, effective_permission_ids)
                if "view_space" in permission_ids
            }

        is_global_admin = False
        is_admin = getattr(self.login_user, "is_admin", None)
        if callable(is_admin):
            is_global_admin = bool(is_admin())

        permission_level_map: dict[int, str | None] = {}
        permission_probe_ids = [
            row[0].id
            for row in rows
            if row[0].user_id != self.login_user.user_id
            and self._resolve_subscription_status_from_fields(row[1], row[2]) != SpaceSubscriptionStatusEnum.SUBSCRIBED
        ]
        if permission_probe_ids and not is_global_admin:
            permission_levels = await asyncio.gather(
                *[
                    PermissionService.get_permission_level(
                        user_id=self.login_user.user_id,
                        object_type="knowledge_space",
                        object_id=str(space_id),
                        login_user=self.login_user,
                    )
                    for space_id in permission_probe_ids
                ]
            )
            permission_level_map = {space_id: level for space_id, level in zip(permission_probe_ids, permission_levels)}

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
                        "is_followed": subscription_status == SpaceSubscriptionStatusEnum.SUBSCRIBED,
                        "is_pending": subscription_status == SpaceSubscriptionStatusEnum.PENDING,
                        "subscription_status": subscription_status,
                        "user_name": creator.user_name if creator else str(space.user_id),
                        "avatar": await UserService.get_avatar_share_link(creator.avatar) if creator else None,
                        "file_num": success_file_map.get(space.id, 0),
                        "follower_num": subscriber_count,
                        "user_role": user_role,
                        "can_unsubscribe": await self._can_unsubscribe_space(space, member_info),
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
        self, space_id: int, page: int, page_size: int, keyword: str | None = None
    ) -> SpaceMemberPageResponse:
        from bisheng.user.domain.services.user import UserService

        """
        Paginate through the list of space members.
        - Verify if the current user has read permission
        - Support fuzzy search by username
        - Return user information and associated user groups
        - Sorting: Creators and administrators at the top, regular members sorted by user_id
        """
        await self._require_permission_id("knowledge_space", space_id, "manage_space_relation")

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
                    user_avatar=await UserService.get_avatar_share_link(user.avatar) if user else None,
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
        await self._require_permission_id("knowledge_space", req.space_id, "manage_space_relation")

        # Get current user's SCM role for business logic decisions
        current_role = await SpaceChannelMemberDao.async_get_active_member_role(req.space_id, self.login_user.user_id)

        # 2. Query target member
        target_membership = await SpaceChannelMemberDao.async_find_member(space_id=req.space_id, user_id=req.user_id)
        if not target_membership or not target_membership.is_active:
            raise ValueError("The target user is not a member of this space")

        # 3. Modifying the creator's role is not allowed
        if target_membership.user_role == UserRoleEnum.CREATOR:
            raise ValueError("Modifying the creator's role is not allowed")

        # 4. Admin permission limits
        if current_role == UserRoleEnum.ADMIN:
            # Admins cannot set others as admins
            if req.role == UserRoleEnum.ADMIN.value:
                raise ValueError("Admins do not have permission to set others as admins")
            # Admins cannot modify the roles of other admins
            if target_membership.user_role == UserRoleEnum.ADMIN:
                raise ValueError("Admins do not have permission to modify the roles of other admins")

        # 5. Check maximum limit when setting as an admin
        if req.role == UserRoleEnum.ADMIN.value:
            current_admins = await SpaceChannelMemberDao.async_get_members_by_space(
                space_id=req.space_id, user_roles=[UserRoleEnum.ADMIN]
            )
            if len(current_admins) >= 5:
                raise ValueError("Maximum number of administrators reached")

        should_notify_admin_assignment = (
            target_membership.user_role == UserRoleEnum.MEMBER and req.role == UserRoleEnum.ADMIN.value
        )
        should_notify_admin_revoked = (
            target_membership.user_role == UserRoleEnum.ADMIN and req.role == UserRoleEnum.MEMBER.value
        )
        had_manage_access = False
        if should_notify_admin_assignment:
            had_manage_access = await self._user_can_manage_space(
                target_membership.user_id,
                req.space_id,
            )

        # 6. Update role in SpaceChannelMember
        target_membership.user_role = UserRoleEnum(req.role)
        await SpaceChannelMemberDao.update(target_membership)
        await self.__class__.sync_direct_space_user_permissions(
            req.space_id,
            target_membership.user_id,
            target_membership.user_role,
            is_active=True,
        )

        if should_notify_admin_assignment and not had_manage_access:
            await self._send_admin_assignment_notification(
                space_id=req.space_id,
                target_user_id=target_membership.user_id,
            )
        if should_notify_admin_revoked:
            if not await self._user_can_manage_space(target_membership.user_id, req.space_id):
                await self._send_space_event_notification(
                    action_code=SPACE_ADMIN_REVOKED_MESSAGE,
                    receiver_user_ids=[target_membership.user_id],
                    space_id=req.space_id,
                    navigable=True,
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
        await self._require_permission_id("knowledge_space", req.space_id, "manage_space_relation")

        # Get current user's SCM role for business logic decisions
        current_role = await SpaceChannelMemberDao.async_get_active_member_role(req.space_id, self.login_user.user_id)

        # 2. Cannot remove yourself
        if req.user_id == self.login_user.user_id:
            raise ValueError("Cannot remove yourself")

        # 3. Query target member
        target_membership = await SpaceChannelMemberDao.async_find_member(space_id=req.space_id, user_id=req.user_id)
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
        await SpaceChannelMemberDao.delete_space_member(space_id=req.space_id, user_id=req.user_id)
        if not await self._user_can_read_space(req.user_id, req.space_id):
            await self._send_space_event_notification(
                action_code=SPACE_MEMBER_REMOVED_MESSAGE,
                receiver_user_ids=[req.user_id],
                space_id=req.space_id,
                navigable=False,
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
            action_code=SPACE_ADMIN_ASSIGNMENT_MESSAGE,
        )

    async def _send_space_event_notification(
        self,
        *,
        action_code: str,
        receiver_user_ids: list[int],
        space_id: int,
        space_name: str | None = None,
        navigable: bool = False,
    ) -> None:
        if not self.message_service or not receiver_user_ids:
            return
        try:
            if space_name is None:
                space = await KnowledgeDao.aquery_by_id(space_id)
                space_name = space.name if space else str(space_id)
            await self.message_service.send_generic_notify(
                sender=self.login_user.user_id,
                receiver_user_ids=receiver_user_ids,
                content_item_list=build_notify_content(
                    action_code=action_code,
                    target_name=space_name,
                    business_type="knowledge_space_id",
                    business_id=space_id,
                    actor_user_id=self.login_user.user_id,
                    actor_user_name=getattr(self.login_user, "user_name", None),
                    navigable=navigable,
                ),
                action_code=action_code,
            )
        except Exception:
            _logger.exception(
                "failed to send knowledge-space event notification: action_code=%s space_id=%s",
                action_code,
                space_id,
            )

    @staticmethod
    async def _user_can_manage_space(user_id: int, space_id: int) -> bool:
        return await PermissionService.check(
            user_id=user_id,
            relation="can_manage",
            object_type="knowledge_space",
            object_id=str(space_id),
        )

    @staticmethod
    async def _user_can_read_space(user_id: int, space_id: int) -> bool:
        return await PermissionService.check(
            user_id=user_id,
            relation="can_read",
            object_type="knowledge_space",
            object_id=str(space_id),
        )

    async def _enrich_with_version_info(self, items: list[KnowledgeFile]) -> list[KnowledgeFile]:
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
        primary_versions = await self.version_repo.find_primary_versions_by_file_ids(file_id_list)
        # Map: knowledge_file_id -> KnowledgeDocumentVersion
        ver_by_file: dict[int, KnowledgeDocumentVersion] = {v.knowledge_file_id: v for v in primary_versions}

        # Count all versions per document to determine is_multi_version.
        # Batch by unique document_ids to avoid N queries.
        # Uses the module-level get_async_db_session so that tests can patch it.
        from sqlalchemy import func as _func

        doc_ids = list({v.document_id for v in primary_versions})
        doc_version_counts: dict[int, int] = {}
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

    async def _resolve_shougang_portal_source_folder_paths(self, items: list[dict]) -> dict[int, str]:
        folder_path_map, _ = await self._resolve_shougang_portal_source_paths(items)
        return folder_path_map

    async def _resolve_shougang_portal_source_paths(self, items: list[dict]) -> tuple[dict[int, str], dict[int, str]]:
        """Resolve readable source folder paths for published portal files.

        Published files are usually flattened to the root of the public space
        (the approval publish handler copies them with target_file_level_path=''),
        so their original folder structure is recovered from
        user_metadata.shougang_portal_publish.{source_space_id, source_file_id}.
        Files without publish metadata fall back to their own knowledge_id and
        file_level_path. If the physical file path is root but the file is the
        primary version of a logical document, the document's folder path is
        used before falling back to a root source path.

        Returns maps for published file id -> "<source space>/<folder>/<folder>"
        and published file id -> "<source space>><folder>/<file>".
        Root source files use only "<source space>" in source_path.
        Folder ids in file_level_path are resolved to names in one batch query.
        """
        source_file_by_item: dict[int, int] = {}
        source_file_ids: set[int] = set()
        current_source_by_item: dict[int, tuple[int, str, str]] = {}
        for item in items:
            item_id = int(item.get("id") or 0)
            knowledge_id = int(item.get("knowledge_id") or item.get("space_id") or 0)
            if item_id and knowledge_id:
                current_source_by_item[item_id] = (
                    knowledge_id,
                    str(item.get("file_level_path") or ""),
                    str(item.get("file_name") or item.get("title") or ""),
                )

            metadata = item.get("user_metadata") or {}
            publish = metadata.get("shougang_portal_publish") if isinstance(metadata, dict) else None
            source_file_id = publish.get("source_file_id") if isinstance(publish, dict) else None
            if source_file_id:
                source_file_by_item[item_id] = int(source_file_id)
                source_file_ids.add(int(source_file_id))

        source_files = await KnowledgeFileDao.aget_file_by_ids(list(source_file_ids)) if source_file_ids else []
        source_file_map = {int(f.id): f for f in source_files}

        published_source_by_item: dict[int, tuple[int, str, str]] = {}
        for item_id, source_file_id in source_file_by_item.items():
            source_file = source_file_map.get(source_file_id)
            if source_file is None:
                continue
            published_source_by_item[item_id] = (
                int(source_file.knowledge_id),
                str(source_file.file_level_path or ""),
                str(source_file.file_name or ""),
            )

        document_source_by_item: dict[int, tuple[int, str, str]] = {}
        if current_source_by_item and self.version_repo and self.doc_repo:
            versions = await self.version_repo.find_primary_versions_by_file_ids(list(current_source_by_item.keys()))
            version_by_file = {
                int(version.knowledge_file_id): version
                for version in versions
                if getattr(version, "knowledge_file_id", None) is not None
            }
            document_ids = list(
                {
                    int(version.document_id)
                    for version in version_by_file.values()
                    if getattr(version, "document_id", None) is not None
                }
            )
            documents = await self.doc_repo.find_by_ids(document_ids) if document_ids else []
            document_map = {
                int(document.id): document for document in documents if getattr(document, "id", None) is not None
            }
            for item_id, (knowledge_id, _file_level_path, file_name) in current_source_by_item.items():
                version = version_by_file.get(item_id)
                document = document_map.get(int(version.document_id)) if version else None
                document_path = str(getattr(document, "file_level_path", "") or "") if document else ""
                if document_path:
                    document_source_by_item[item_id] = (
                        int(getattr(document, "knowledge_id", knowledge_id) or knowledge_id),
                        document_path,
                        file_name,
                    )

        source_record_by_item: dict[int, tuple[int, str, str]] = {}
        for item_id in set(current_source_by_item) | set(published_source_by_item) | set(document_source_by_item):
            published_source = published_source_by_item.get(item_id)
            current_source = current_source_by_item.get(item_id)
            document_source = document_source_by_item.get(item_id)
            if published_source and published_source[1]:
                source_record_by_item[item_id] = published_source
            elif current_source and current_source[1]:
                source_record_by_item[item_id] = current_source
            elif document_source and document_source[1]:
                source_record_by_item[item_id] = document_source
            elif published_source:
                source_record_by_item[item_id] = published_source
            elif current_source:
                source_record_by_item[item_id] = current_source
            elif document_source:
                source_record_by_item[item_id] = document_source

        if not source_record_by_item:
            return {}, {}

        folder_ids: set[int] = set()
        source_space_ids: set[int] = set()
        for knowledge_id, file_level_path, _file_name in source_record_by_item.values():
            source_space_ids.add(knowledge_id)
            folder_ids.update(int(part) for part in file_level_path.split("/") if part)

        folder_name_map: dict[int, str] = {}
        if folder_ids:
            folders = await KnowledgeFileDao.aget_file_by_ids(list(folder_ids))
            folder_name_map = {
                int(f.id): str(f.file_name or "") for f in folders if int(f.file_type) == FileType.DIR.value
            }

        space_name_map: dict[int, str] = {}
        if source_space_ids:
            source_spaces = await KnowledgeDao.async_get_spaces_by_ids(list(source_space_ids))
            space_name_map = {int(s.id): str(s.name or s.id) for s in source_spaces}

        folder_path_map: dict[int, str] = {}
        source_path_map: dict[int, str] = {}
        for item_id, (knowledge_id, file_level_path, file_name) in source_record_by_item.items():
            space_name = space_name_map.get(knowledge_id, str(knowledge_id))
            folder_segments: list[str] = []
            for part in file_level_path.split("/"):
                folder_name = folder_name_map.get(int(part)) if part else None
                if folder_name:
                    folder_segments.append(folder_name)
            folder_path_map[item_id] = "/".join([space_name, *folder_segments])
            if folder_segments:
                source_tail_segments = [*folder_segments, *([file_name] if file_name else [])]
                source_path_map[item_id] = f"{space_name}>{'/'.join(source_tail_segments)}"
            else:
                source_path_map[item_id] = space_name
        return folder_path_map, source_path_map

    async def _count_folder_file_stats(
        self,
        folder: KnowledgeFile,
        *,
        permission_context: dict | None = None,
    ) -> dict[str, int]:
        from sqlalchemy import or_
        from sqlmodel import col

        prefix = f"{folder.file_level_path or ''}/{folder.id}"
        stmt = (
            select(KnowledgeFile.status, func.count(KnowledgeFile.id))
            .where(
                KnowledgeFile.knowledge_id == folder.knowledge_id,
                KnowledgeFile.file_type == FileType.FILE.value,
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

        total = sum(row[1] for row in rows)
        success = sum(row[1] for row in rows if row[0] == KnowledgeFileStatus.SUCCESS.value)
        processing = sum(row[1] for row in rows if row[0] in in_progress_statuses)
        visible_success = await self._count_visible_success_files_under_folder(
            folder,
            prefix,
            permission_context=permission_context,
        )
        return {
            "file_num": total,
            "success_file_num": success,
            "visible_success_file_num": visible_success,
            "processing_file_num": processing,
        }

    async def _load_folder_stat_counts(self, folders: list[KnowledgeFile]) -> dict[int, dict[str, int]]:
        folder_counts: dict[int, dict[str, int]] = {}
        if not folders:
            return folder_counts

        folders_by_space: dict[int, list[KnowledgeFile]] = {}
        for folder in folders:
            folders_by_space.setdefault(int(folder.knowledge_id), []).append(folder)

        async def count_folder(folder: KnowledgeFile, permission_context: dict):
            folder_counts[int(folder.id)] = await self._count_folder_file_stats(
                folder,
                permission_context=permission_context,
            )

        for space_id, space_folders in folders_by_space.items():
            permission_context = await self._build_child_permission_context(space_id)
            await asyncio.gather(*(count_folder(folder, permission_context) for folder in space_folders))

        return folder_counts

    async def get_space_folder_stats(self, space_id: int, folder_ids: list[int]) -> dict:
        unique_folder_ids = self._dedupe_ids([int(folder_id) for folder_id in folder_ids or []])
        if not unique_folder_ids:
            return {"stats": []}

        await self._require_read_permission(space_id)
        folders = await KnowledgeFileDao.aget_file_by_ids(unique_folder_ids)
        folder_by_id = {int(folder.id): folder for folder in folders}
        if set(folder_by_id) != set(unique_folder_ids):
            raise SpaceFolderNotFoundError()

        ordered_folders: list[KnowledgeFile] = []
        for folder_id in unique_folder_ids:
            folder = self._ensure_space_folder(folder_by_id.get(folder_id), space_id)
            ordered_folders.append(folder)

        await asyncio.gather(
            *(self._require_resource_permission("can_read", "folder", int(folder.id)) for folder in ordered_folders)
        )

        folder_counts = await self._load_folder_stat_counts(ordered_folders)
        return {
            "stats": [
                {
                    "folder_id": folder_id,
                    **folder_counts.get(
                        folder_id,
                        {
                            "file_num": 0,
                            "success_file_num": 0,
                            "visible_success_file_num": 0,
                            "processing_file_num": 0,
                        },
                    ),
                }
                for folder_id in unique_folder_ids
            ]
        }

    async def _handle_file_folder_extra_info(
        self,
        res: list[KnowledgeFile],
        *,
        include_folder_counts: bool = True,
    ) -> list[dict]:
        folder_ids = []
        file_ids = []
        for one in res:
            if one.file_type == FileType.DIR:
                folder_ids.append(one.id)
            else:
                file_ids.append(one.id)

        folder_counts = {}
        if include_folder_counts and folder_ids:
            folders = [f for f in res if f.file_type == FileType.DIR]
            folder_counts = await self._load_folder_stat_counts(folders)

        # file need find all tags
        file_tags = {}
        if file_ids:
            tag_dict = await asyncio.to_thread(
                TagDao.get_tags_by_resource_batch,
                [ResourceTypeEnum.SPACE_FILE],
                [str(fid) for fid in file_ids],
            )
            for fid_str, tags in tag_dict.items():
                file_tags[int(fid_str)] = [{"id": t.id, "name": t.name, "resource_type": t.resource_type} for t in tags]

        result = []
        for one in res:
            item = one.model_dump()
            if one.file_type == FileType.DIR:
                if include_folder_counts:
                    counts = folder_counts.get(
                        int(one.id),
                        {
                            "file_num": 0,
                            "success_file_num": 0,
                            "visible_success_file_num": 0,
                            "processing_file_num": 0,
                        },
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
                item["has_similar"] = getattr(one, "_has_similar", (one.similar_status == 1))
            result.append(item)

        return result

    async def _count_visible_success_files_under_folder(
        self,
        folder: KnowledgeFile,
        prefix: str,
        *,
        permission_context: dict | None = None,
    ) -> int:
        children = await SpaceFileDao.get_children_by_prefix(
            folder.knowledge_id,
            prefix,
            file_status=KnowledgeFileStatus.SUCCESS,
        )
        files = [item for item in children or [] if self._is_qa_scope_file(item, int(folder.knowledge_id))]
        if not files:
            return 0
        visible_files = await self._filter_visible_child_items(
            files,
            space_id=int(folder.knowledge_id),
            context=permission_context,
        )
        return len(visible_files)

    async def _filter_visible_child_items(
        self,
        items: list[KnowledgeFile],
        *,
        space_id: int,
        context: dict | None = None,
    ) -> list[KnowledgeFile]:
        _increment_portal_search_perf("visible_check_count", len(items))
        semaphore = asyncio.Semaphore(_CHILD_PERMISSION_CHECK_CONCURRENCY)
        permission_context = context or await self._build_child_permission_context(space_id)

        async def can_view(item: KnowledgeFile) -> bool:
            async with semaphore:
                permission_id = "view_folder" if item.file_type == FileType.DIR.value else "view_file"
                effective_permissions = await self._get_child_item_effective_permission_ids(
                    item,
                    space_id=space_id,
                    context=permission_context,
                )
                return permission_id in effective_permissions

        visibility = await asyncio.gather(*(can_view(item) for item in items))
        return [item for item, allowed in zip(items, visibility) if allowed]

    @staticmethod
    def _paginate_items(items: list[KnowledgeFile], page: int, page_size: int) -> list[KnowledgeFile]:
        if not page or not page_size:
            return items
        start = (page - 1) * page_size
        return items[start : start + page_size]

    async def _scan_visible_child_items(
        self,
        *,
        space_id: int,
        parent_id: int | None,
        file_ids: list[int] | None,
        order_field: str,
        order_sort: str,
        file_status: list[int] | None,
        file_type: int | None,
        page_size: int,
        cursor: list | None = None,
        exclude_file_ids: list[int] | None = None,
    ) -> tuple[list[KnowledgeFile], bool]:
        """F027 cursor-paginated scan: keep fetching batches via keyset, fold
        through ReBAC filtering, stop once we've accumulated ``page_size + 1``
        visible items (the +1 probes ``has_more``) or the DB is exhausted.

        Returns ``(visible_page_items, has_more)`` — the visible items are
        already truncated to ``page_size`` if ``has_more`` is True.
        """
        from bisheng.knowledge.domain.models.knowledge_space_file import (
            build_child_order_cursor_key,
            normalize_child_order_field,
            normalize_child_order_sort,
        )

        visible_page_items: list[KnowledgeFile] = []
        order_field = normalize_child_order_field(order_field)
        order_sort = normalize_child_order_sort(order_sort)
        permission_context = await self._build_child_permission_context(space_id)
        batch_cursor: list | None = list(cursor) if cursor else None

        while True:
            batch_items = await SpaceFileDao.async_list_children(
                space_id,
                parent_id,
                file_ids=file_ids,
                order_field=order_field,
                order_sort=order_sort,
                file_status=file_status,
                page=0,  # cursor mode bypasses OFFSET
                page_size=_CHILD_PERMISSION_SCAN_BATCH_SIZE,
                file_type=file_type,
                exclude_file_ids=exclude_file_ids,
                cursor=batch_cursor,
            )
            if not batch_items:
                break

            visible_batch = await self._filter_visible_child_items(
                batch_items,
                space_id=space_id,
                context=permission_context,
            )
            for item in visible_batch:
                visible_page_items.append(item)
                if len(visible_page_items) > page_size:
                    # Got the +1 probe — done scanning.
                    return visible_page_items[:page_size], True

            # Advance batch_cursor to the LAST DB row of this batch (not last
            # visible) so the next batch picks up strictly after; if we used
            # the last visible, items filtered out between them would be
            # re-emitted on the next batch.
            last_db = batch_items[-1]
            batch_cursor = build_child_order_cursor_key(last_db, order_field)

            if len(batch_items) < _CHILD_PERMISSION_SCAN_BATCH_SIZE:
                break

        return visible_page_items, False

    async def list_space_children(
        self,
        space_id: int,
        parent_id: int | None = None,
        file_ids: list[int] | None = None,
        order_field: str = "file_type",
        order_sort: str = "asc",
        file_status: list[int] = None,
        cursor: str | None = None,
        page_size: int = 20,
        file_type: int | None = None,
    ) -> "PageInfiniteCursorData":
        """F027 cursor-paginated listing of direct children under a parent folder.

        Response shape (PageInfiniteCursorData): ``{data, page_size, has_more,
        next_cursor}``. Legacy ``total`` / ``page`` fields removed (AC-03);
        clients drive infinite-scroll via ``has_more`` + ``next_cursor``.
        """
        from bisheng.common.cursor import CursorDecodeError, decode_cursor, encode_cursor
        from bisheng.common.errcode.knowledge_space import KnowledgeSpaceInvalidCursorError
        from bisheng.common.schemas.api import PageInfiniteCursorData
        from bisheng.knowledge.domain.models.knowledge_space_file import (
            build_child_order_cursor_key,
            child_order_cursor_key_len,
            normalize_child_order_field,
            normalize_child_order_sort,
        )

        if parent_id:
            await self._require_folder_relation(space_id, parent_id, "can_read")
        else:
            await self._require_read_permission(space_id)

        order_field = normalize_child_order_field(order_field)
        order_sort = normalize_child_order_sort(order_sort)
        context = f"space_children|order={order_field}_{(order_sort or 'asc').lower()}"
        try:
            decoded = decode_cursor(
                cursor,
                expected_key_len=child_order_cursor_key_len(order_field),
                expected_context=context,
            )
        except CursorDecodeError as exc:
            raise KnowledgeSpaceInvalidCursorError(exception=exc)

        # Exclude non-primary version files so only the current primary revision is visible.
        exclude_file_ids: list[int] | None = None
        if self.version_repo is not None:
            exclude_file_ids = await self.version_repo.find_non_primary_file_ids_by_knowledge_ids([space_id]) or None

        visible_page_items, has_more = await self._scan_visible_child_items(
            space_id=space_id,
            parent_id=parent_id,
            file_ids=file_ids,
            order_field=order_field,
            order_sort=order_sort,
            file_status=file_status,
            file_type=file_type,
            page_size=page_size,
            cursor=decoded,
            exclude_file_ids=exclude_file_ids,
        )

        # Enrich page items with version fields (version_no, is_multi_version, has_similar).
        await self._enrich_with_version_info(visible_page_items)

        data = await self._handle_file_folder_extra_info(
            visible_page_items,
            include_folder_counts=False,
        )

        next_cursor: str | None = None
        if has_more and visible_page_items:
            last = visible_page_items[-1]
            next_cursor = encode_cursor(
                build_child_order_cursor_key(last, order_field),
                context=context,
            )

        return PageInfiniteCursorData(
            data=data,
            page_size=page_size,
            has_more=has_more,
            next_cursor=next_cursor,
        )

    async def resolve_qa_scope_file_ids(
        self,
        *,
        folder_refs: list,
        file_refs: list,
        max_files: int = 20,
    ) -> dict[int, list[int]]:
        resolved: dict[int, list[int]] = {}
        seen: set[tuple[int, int]] = set()

        async def add_file(space_id: int, file_id: int) -> None:
            key = (space_id, file_id)
            if key in seen:
                return
            seen.add(key)
            resolved.setdefault(space_id, []).append(file_id)
            if len(seen) > max_files:
                raise ValueError("一次最多可选择20个文件进行问答。")

        for ref in file_refs or []:
            space_id = self._scope_ref_int(ref, "knowledge_space_id")
            file_id = self._scope_ref_int(ref, "file_id")
            if space_id <= 0 or file_id <= 0:
                continue
            await self._require_read_permission(space_id)
            file_record = await KnowledgeFileDao.query_by_id(file_id)
            if not self._is_qa_scope_file(file_record, space_id):
                continue
            await self._require_permission_id("knowledge_file", file_id, "view_file", space_id=space_id)
            await add_file(space_id, file_id)

        for ref in folder_refs or []:
            space_id = self._scope_ref_int(ref, "knowledge_space_id")
            folder_id = self._scope_ref_int(ref, "folder_id")
            if space_id <= 0 or folder_id <= 0:
                continue
            await self._require_read_permission(space_id)
            folder = await KnowledgeFileDao.query_by_id(folder_id)
            if not self._is_qa_scope_folder(folder, space_id):
                continue
            await self._require_permission_id("folder", folder_id, "view_folder", space_id=space_id)
            prefix = f"{getattr(folder, 'file_level_path', '') or ''}/{folder.id}"
            children = await SpaceFileDao.get_children_by_prefix(
                space_id,
                prefix,
                file_status=KnowledgeFileStatus.SUCCESS,
            )
            files = [item for item in children or [] if self._is_qa_scope_file(item, space_id)]
            visible_files = await self._filter_visible_child_items(files, space_id=space_id)
            for item in visible_files:
                await add_file(space_id, int(item.id))

        if not seen:
            raise ValueError("请选择可用于问答的文件。")
        return {space_id: ids for space_id, ids in sorted(resolved.items())}

    @staticmethod
    def _scope_ref_int(ref: Any, field_name: str) -> int:
        value = ref.get(field_name) if isinstance(ref, dict) else getattr(ref, field_name, 0)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _is_qa_scope_file(file_record: Any, space_id: int) -> bool:
        if file_record is None:
            return False
        return (
            KnowledgeSpaceService._coerce_int(getattr(file_record, "knowledge_id", 0), 0) == int(space_id)
            and KnowledgeSpaceService._coerce_int(getattr(file_record, "file_type", -1), -1) == FileType.FILE.value
            and KnowledgeSpaceService._coerce_int(getattr(file_record, "status", -1), -1)
            == KnowledgeFileStatus.SUCCESS.value
        )

    @staticmethod
    def _is_qa_scope_folder(file_record: Any, space_id: int) -> bool:
        if file_record is None:
            return False
        return (
            KnowledgeSpaceService._coerce_int(getattr(file_record, "knowledge_id", 0), 0) == int(space_id)
            and KnowledgeSpaceService._coerce_int(getattr(file_record, "file_type", -1), -1) == FileType.DIR.value
        )

    @staticmethod
    def _coerce_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    async def search_space_children(
        self,
        space_id: int,
        parent_id: int | None = None,
        tag_ids: list[int] = None,
        keyword: str = None,
        page: int = 1,
        page_size: int = 20,
        file_status: list[int] = None,
        order_field: str = "file_type",
        order_sort: str = "asc",
    ) -> dict:
        space = await self._require_read_permission(space_id)
        if not parent_id:
            await self._require_permission_id("knowledge_space", space_id, "view_space")

        file_level_path = None
        filter_files = []

        if parent_id:
            parent_folder = await self._require_folder_relation(space_id, parent_id, "can_read")
            await self._require_permission_id("folder", parent_id, "view_folder", space_id=space_id)
            file_level_path = f"{parent_folder.file_level_path}/{parent_folder.id}"
            children_ids = await SpaceFileDao.get_children_by_prefix(space_id, file_level_path)
            if not children_ids:
                return {"total": 0, "page": page, "page_size": page_size, "data": []}
            filter_files = [one.id for one in children_ids]

        if tag_ids:
            resources = await TagDao.aget_resources_by_tags(tag_ids, ResourceTypeEnum.SPACE_FILE)
            if not resources:
                return {"total": 0, "page": page, "page_size": page_size, "data": []}
            if filter_files:
                filter_files = list(set(filter_files) & set([int(one.resource_id) for one in resources]))
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
            es_vector = await KnowledgeRag.init_knowledge_es_vectorstore(knowledge=space)
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
        exclude_file_ids: list[int] | None = None
        if self.version_repo is not None:
            exclude_file_ids = await self.version_repo.find_non_primary_file_ids() or None

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
        parent_id: int | None = None,
    ) -> KnowledgeFile:
        if parent_id:
            await self._require_permission_id("folder", parent_id, "create_folder", space_id=knowledge_id)
        else:
            await self._require_permission_id("knowledge_space", knowledge_id, "create_folder")
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

        self._check_name_sensitive_words(folder_name)

        if await SpaceFileDao.count_folder_by_name(knowledge_id, folder_name, file_level_path) > 0:
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
        await self._require_permission_id("folder", folder_id, "rename_folder", space_id=folder.knowledge_id)
        self._check_name_sensitive_words(new_name)

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
        await self._require_permission_id("folder", folder_id, "delete_folder", space_id=space_id)
        space = await KnowledgeDao.aquery_by_id(space_id)
        if not space:
            raise SpaceNotFoundError()
        self._ensure_space_async_task_tenant_consistency(space, "delete_folder")

        prefix = f"{folder.file_level_path}/{folder.id}"
        children = await SpaceFileDao.get_children_by_prefix(folder.knowledge_id, prefix)
        floder_ids = [folder_id]
        file_ids = []
        resource_tuples_to_cleanup = [("folder", folder_id)]
        for child in children:
            if child.file_type == FileType.DIR.value:
                await self._require_permission_id("folder", child.id, "delete_folder", space_id=space_id)
                floder_ids.append(child.id)
                resource_tuples_to_cleanup.append(("folder", child.id))
            else:
                await self._require_permission_id("knowledge_file", child.id, "delete_file", space_id=space_id)
                file_ids.append(child.id)
                resource_tuples_to_cleanup.append(("knowledge_file", child.id))

        expanded_file_ids = await self._cascade_version_links_on_delete(file_ids) if file_ids else []
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

    async def get_folder_file_parent(self, space_id: int, file_id: int) -> list[dict]:
        file_record = await self._require_file_or_folder_relation(space_id, file_id, "can_read")
        await self._require_permission_id(
            "folder" if file_record.file_type == FileType.DIR.value else "knowledge_file",
            file_record.id,
            "view_folder" if file_record.file_type == FileType.DIR.value else "view_file",
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
                    "file_name": file_list.get(one).file_name if file_list.get(one) else one,
                }
            )
        return res

    @staticmethod
    def _format_datetime(value) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return str(value)

    @staticmethod
    def _folder_ids_from_level_path(file_level_path: str | None) -> list[int]:
        return [int(part) for part in (file_level_path or "").split("/") if part.isdigit()]

    @classmethod
    def _parent_folder_id_from_level_path(cls, file_level_path: str | None) -> int | None:
        folder_ids = cls._folder_ids_from_level_path(file_level_path)
        return folder_ids[-1] if folder_ids else None

    @classmethod
    def _folder_path_name_from_map(cls, file_level_path: str | None, folder_map: dict[int, KnowledgeFile]) -> str:
        folder_ids = cls._folder_ids_from_level_path(file_level_path)
        if not folder_ids:
            return "根目录"
        names = [
            folder_map[folder_id].file_name if folder_map.get(folder_id) else str(folder_id) for folder_id in folder_ids
        ]
        return "/".join(names) if names else "根目录"

    @classmethod
    def _upload_folder_candidate_path(cls, folder: KnowledgeFile, folder_map: dict[int, KnowledgeFile]) -> str:
        folder_ids = [*cls._folder_ids_from_level_path(folder.file_level_path), int(folder.id)]
        names = [
            folder_map[folder_id].file_name if folder_map.get(folder_id) else str(folder_id) for folder_id in folder_ids
        ]
        return "/".join(names) if names else folder.file_name

    @staticmethod
    def _extract_llm_json_text(raw: str) -> str:
        text = (raw or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return text

    @staticmethod
    def _resolve_upload_recommend_model_id(workbench_llm) -> int | None:
        if not workbench_llm:
            return None
        candidates = [
            getattr(workbench_llm, "chat_title_llm", None),
            getattr(workbench_llm, "task_model", None),
        ]
        models = getattr(workbench_llm, "models", None) or []
        if models:
            candidates.append(models[0])
        for model in candidates:
            model_id = getattr(model, "id", None)
            if model_id:
                try:
                    return int(model_id)
                except (TypeError, ValueError):
                    return model_id
        return None

    @staticmethod
    def _root_upload_folder_recommendation(
        file: UploadFolderRecommendFileReq,
        reason: str,
    ) -> UploadFolderRecommendationItemResp:
        return UploadFolderRecommendationItemResp(
            client_file_id=file.client_file_id,
            file_name=file.file_name,
            recommended_folder_id=None,
            recommended_folder_name="根目录",
            recommended_folder_path="根目录",
            reason=reason,
        )

    async def _filter_recommendable_upload_folders(
        self,
        space_id: int,
        folders: list[KnowledgeFile],
    ) -> list[KnowledgeFile]:
        recommendable_folders: list[KnowledgeFile] = []
        for folder in folders:
            folder_id = getattr(folder, "id", None)
            if folder_id is None:
                continue
            try:
                await self._require_permission_id("folder", int(folder_id), "view_folder", space_id=space_id)
                await self._require_permission_id("folder", int(folder_id), "upload_file", space_id=space_id)
            except SpacePermissionDeniedError:
                continue
            recommendable_folders.append(folder)
        return recommendable_folders

    def _build_upload_folder_recommend_messages(
        self,
        files: list[UploadFolderRecommendFileReq],
        folder_candidates: list[dict],
    ) -> list[dict[str, str]]:
        system_prompt = (
            "你是企业知识空间文件目录推荐助手。"
            "只能从已有目录候选中为每个文件选择最合适的目录；"
            "不能创造新目录；没有合适目录时推荐根目录，folder_id 使用 null；"
            "每个文件都必须返回结果；只输出 JSON。"
        )
        user_prompt = (
            "已有目录候选：\n"
            f"{json.dumps(folder_candidates, ensure_ascii=False)}\n\n"
            "待推荐文件：\n"
            f"{json.dumps([file.model_dump() for file in files], ensure_ascii=False)}\n\n"
            "输出格式：\n"
            '{"items":[{"client_file_id":"local-1","recommended_folder_id":37,"reason":"简短原因"}]}'
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    async def recommend_upload_folders(
        self,
        space_id: int,
        files: list[UploadFolderRecommendFileReq],
    ) -> UploadFolderRecommendationResp:
        await self._require_permission_id("knowledge_space", space_id, "upload_file")
        if not files:
            return UploadFolderRecommendationResp(items=[])

        folders = await KnowledgeFileDao.aget_folders_by_space(space_id)
        folders = await self._filter_recommendable_upload_folders(space_id, folders)
        folder_map = {int(folder.id): folder for folder in folders if getattr(folder, "id", None) is not None}
        if not folder_map:
            return UploadFolderRecommendationResp(
                items=[
                    self._root_upload_folder_recommendation(file, "当前知识空间暂无目录，降级到根目录")
                    for file in files
                ]
            )

        folder_candidates = [
            {
                "folder_id": int(folder.id),
                "folder_name": folder.file_name,
                "folder_path": self._upload_folder_candidate_path(folder, folder_map),
            }
            for folder in folders
            if getattr(folder, "id", None) is not None
        ]

        raw_items: dict[str, dict] = {}
        try:
            workbench_llm = await LLMService.get_workbench_llm()
            model_id = self._resolve_upload_recommend_model_id(workbench_llm)
            if not model_id:
                raise RuntimeError("workbench chat model is not configured")
            llm = await LLMService.get_bisheng_llm(
                model_id=model_id,
                app_id=ApplicationTypeEnum.DAILY_CHAT.value,
                app_name="shougang_upload_folder_recommend",
                app_type=ApplicationTypeEnum.DAILY_CHAT,
                user_id=self.login_user.user_id,
            )
            response = await llm.ainvoke(self._build_upload_folder_recommend_messages(files, folder_candidates))
            payload = json.loads(self._extract_llm_json_text(getattr(response, "content", "") or ""))
            raw_items = {
                str(item.get("client_file_id")): item
                for item in payload.get("items", [])
                if isinstance(item, dict) and item.get("client_file_id") is not None
            }
        except Exception as exc:
            logger.warning(
                "upload folder recommendation fallback to root: space_id={} user_id={} error={}",
                space_id,
                self.login_user.user_id,
                exc,
            )
            return UploadFolderRecommendationResp(
                items=[self._root_upload_folder_recommendation(file, "AI 推荐目录失败，降级到根目录") for file in files]
            )

        items: list[UploadFolderRecommendationItemResp] = []
        for file in files:
            raw_item = raw_items.get(file.client_file_id) or {}
            raw_folder_id = raw_item.get("recommended_folder_id")
            try:
                recommended_folder_id = int(raw_folder_id) if raw_folder_id is not None else None
            except (TypeError, ValueError):
                recommended_folder_id = None
            reason = str(raw_item.get("reason") or "").strip()
            if recommended_folder_id is None:
                items.append(self._root_upload_folder_recommendation(file, reason or "未匹配到已有目录，降级到根目录"))
                continue
            folder = folder_map.get(recommended_folder_id)
            if not folder:
                items.append(self._root_upload_folder_recommendation(file, "AI 返回目录不存在，降级到根目录"))
                continue
            items.append(
                UploadFolderRecommendationItemResp(
                    client_file_id=file.client_file_id,
                    file_name=file.file_name,
                    recommended_folder_id=recommended_folder_id,
                    recommended_folder_name=folder.file_name,
                    recommended_folder_path=self._upload_folder_candidate_path(folder, folder_map),
                    reason=reason,
                )
            )
        return UploadFolderRecommendationResp(items=items)

    async def list_my_uploaded_files(
        self,
        page: int = 1,
        page_size: int = 20,
        space_id: int | None = None,
        status: int | None = None,
        keyword: str | None = None,
    ) -> PageData[ShougangPortalUploadedFileResp]:
        files, total = await KnowledgeFileDao.alist_user_uploaded_files(
            user_id=self.login_user.user_id,
            page=page,
            page_size=page_size,
            space_id=space_id,
            status=status,
            keyword=keyword,
        )
        if not files:
            return PageData(data=[], total=total)

        space_ids = sorted({int(file.knowledge_id) for file in files if file.knowledge_id})
        spaces = await KnowledgeDao.async_get_spaces_by_ids(space_ids) if space_ids else []
        space_name_map = {int(space.id): space.name for space in spaces if getattr(space, "id", None) is not None}
        space_level_map = {}
        for space in spaces:
            if getattr(space, "id", None) is None:
                continue
            space_id = int(space.id)
            space_level = getattr(space, "space_level", None)
            if space_level is None:
                space_level = await self._get_space_level(space_id)
            space_level_map[space_id] = space_level

        folder_ids: set[int] = set()
        for file in files:
            folder_ids.update(self._folder_ids_from_level_path(file.file_level_path))
        folder_records = await KnowledgeFileDao.aget_file_by_ids(list(folder_ids)) if folder_ids else []
        folder_map = {int(folder.id): folder for folder in folder_records if getattr(folder, "id", None) is not None}

        file_ids = [int(file.id) for file in files if getattr(file, "id", None) is not None]
        file_tags: dict[int, list[dict]] = {}
        if file_ids:
            tag_dict = await asyncio.to_thread(
                TagDao.get_tags_by_resource_batch,
                [ResourceTypeEnum.SPACE_FILE],
                [str(file_id) for file_id in file_ids],
            )
            for file_id, tags in tag_dict.items():
                try:
                    normalized_file_id = int(file_id)
                except (TypeError, ValueError):
                    continue
                file_tags[normalized_file_id] = [{"id": tag.id, "name": tag.name} for tag in tags]

        data = [
            ShougangPortalUploadedFileResp(
                id=int(file.id),
                knowledge_id=int(file.knowledge_id),
                knowledge_name=space_name_map.get(int(file.knowledge_id), ""),
                space_level=space_level_map.get(int(file.knowledge_id)),
                file_name=file.file_name,
                file_level_path=file.file_level_path or "",
                parent_id=self._parent_folder_id_from_level_path(file.file_level_path),
                folder_path_name=self._folder_path_name_from_map(file.file_level_path, folder_map),
                status=file.status,
                file_encoding=file.file_encoding,
                tags=file_tags.get(int(file.id), []),
                abstract=file.abstract or "",
                create_time=self._format_datetime(file.create_time),
                update_time=self._format_datetime(file.update_time),
            )
            for file in files
        ]
        return PageData(data=data, total=total)

    @classmethod
    def _parent_tuple_ref_from_level_path(
        cls,
        file_level_path: str | None,
        space_id: int,
    ) -> tuple[str, int]:
        parent_folder_id = cls._parent_folder_id_from_level_path(file_level_path)
        if parent_folder_id is not None:
            return "folder", parent_folder_id
        return "knowledge_space", space_id

    async def _replace_resource_parent_tuple(
        self,
        *,
        object_type: str,
        object_id: int,
        old_parent_type: str,
        old_parent_id: int,
        new_parent_type: str,
        new_parent_id: int,
    ) -> None:
        if old_parent_type == new_parent_type and old_parent_id == new_parent_id:
            return
        await PermissionService.batch_write_tuples(
            [
                TupleOperation(
                    action="delete",
                    user=f"{old_parent_type}:{old_parent_id}",
                    relation="parent",
                    object=f"{object_type}:{object_id}",
                ),
                TupleOperation(
                    action="write",
                    user=f"{new_parent_type}:{new_parent_id}",
                    relation="parent",
                    object=f"{object_type}:{object_id}",
                ),
            ],
            crash_safe=True,
            raise_on_failure=True,
            stop_on_failure=True,
        )

    async def _sync_document_folder_for_file(self, file_id: int, file_level_path: str, level: int) -> None:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(KnowledgeDocumentVersion.document_id).where(
                    KnowledgeDocumentVersion.knowledge_file_id == file_id,
                )
            )
            document_id = result.first()
            if not document_id:
                return
            await session.exec(
                update(KnowledgeDocument)
                .where(KnowledgeDocument.id == int(document_id))
                .values(file_level_path=file_level_path, level=level)
            )
            await session.commit()

    async def move_file_folder(
        self,
        space_id: int,
        file_id: int,
        target_folder_id: int | None,
    ) -> KnowledgeSpaceFileResponse:
        file_record = await KnowledgeFileDao.query_by_id(file_id)
        file_record = self._ensure_space_file(file_record, space_id)
        await self._require_permission_id("knowledge_file", file_id, "rename_file", space_id=space_id)

        old_file_level_path = file_record.file_level_path or ""
        old_parent_type, old_parent_id = self._parent_tuple_ref_from_level_path(old_file_level_path, space_id)
        if target_folder_id is None:
            await self._require_permission_id("knowledge_space", space_id, "upload_file")
            next_file_level_path = ""
            next_level = 0
            new_parent_type = "knowledge_space"
            new_parent_id = space_id
        else:
            target_folder = await KnowledgeFileDao.query_by_id(target_folder_id)
            target_folder = self._ensure_space_folder(target_folder, space_id)
            await self._require_permission_id("folder", target_folder_id, "upload_file", space_id=space_id)
            next_file_level_path = f"{target_folder.file_level_path or ''}/{target_folder_id}"
            next_level = (target_folder.level or 0) + 1
            new_parent_type = "folder"
            new_parent_id = target_folder_id

        duplicate_count = await SpaceFileDao.count_file_by_name_in_path(
            space_id,
            file_record.file_name,
            next_file_level_path,
            exclude_id=file_id,
        )
        if duplicate_count > 0:
            raise SpaceFileNameDuplicateError()

        file_record.file_level_path = next_file_level_path
        file_record.level = next_level
        file_record.updater_id = self.login_user.user_id
        file_record.updater_name = self.login_user.user_name
        updated_file = await KnowledgeFileDao.async_update(file_record)
        await self._replace_resource_parent_tuple(
            object_type="knowledge_file",
            object_id=file_id,
            old_parent_type=old_parent_type,
            old_parent_id=old_parent_id,
            new_parent_type=new_parent_type,
            new_parent_id=new_parent_id,
        )
        await self._sync_document_folder_for_file(file_id, next_file_level_path, next_level)
        await self.update_folder_update_time(old_file_level_path)
        if next_file_level_path != old_file_level_path:
            await self.update_folder_update_time(next_file_level_path)
        await KnowledgeDao.async_update_knowledge_update_time_by_id(space_id)
        return KnowledgeSpaceFileResponse(**updated_file.model_dump())

    async def move_folder(
        self,
        space_id: int,
        folder_id: int,
        target_folder_id: int | None,
    ) -> KnowledgeSpaceFileResponse:
        """Move a folder (and all its descendants) to a new location within the same space."""
        folder = await KnowledgeFileDao.query_by_id(folder_id)
        folder = self._ensure_space_folder(folder, space_id)
        await self._require_permission_id("folder", folder_id, "rename_file", space_id=space_id)

        old_folder_path = folder.file_level_path or ""
        old_level = folder.level or 0
        # The path prefix shared by all descendants of this folder.
        old_prefix = f"{old_folder_path}/{folder_id}" if old_folder_path else f"/{folder_id}"

        old_parent_type, old_parent_id = self._parent_tuple_ref_from_level_path(old_folder_path, space_id)

        if target_folder_id is None:
            await self._require_permission_id("knowledge_space", space_id, "upload_file")
            new_parent_path = ""
            new_level = 0
            new_parent_type = "knowledge_space"
            new_parent_id_val = space_id
        else:
            if target_folder_id == folder_id:
                raise SpaceFolderCircularMoveError()
            target = await KnowledgeFileDao.query_by_id(target_folder_id)
            target = self._ensure_space_folder(target, space_id)
            await self._require_permission_id("folder", target_folder_id, "upload_file", space_id=space_id)

            # Reject moves into the folder's own subtree.
            target_path = target.file_level_path or ""
            if target_path == old_prefix or target_path.startswith(f"{old_prefix}/"):
                raise SpaceFolderCircularMoveError()

            new_parent_path = f"{target_path}/{target_folder_id}" if target_path else f"/{target_folder_id}"
            new_level = (target.level or 0) + 1
            new_parent_type = "folder"
            new_parent_id_val = target_folder_id

        # Check for duplicate folder name in destination.
        duplicate_count = await SpaceFileDao.count_folder_by_name(
            space_id, folder.file_name, new_parent_path, exclude_id=folder_id
        )
        if duplicate_count > 0:
            raise SpaceFolderDuplicateError()

        new_prefix = f"{new_parent_path}/{folder_id}" if new_parent_path else f"/{folder_id}"
        level_diff = new_level - old_level

        # Check that moving the subtree won't exceed the 10-level depth limit.
        # Find the deepest level among all descendants and apply the level_diff.
        if level_diff != 0:
            max_descendant_level = await SpaceFileDao.max_level_under_prefix(space_id, old_prefix)
            if max_descendant_level is not None and max_descendant_level + level_diff > 10:
                raise SpaceFolderDepthError()

        # Update folder record and all descendants in a single transaction.
        folder.file_level_path = new_parent_path
        folder.level = new_level
        folder.updater_id = self.login_user.user_id
        folder.updater_name = self.login_user.user_name
        await SpaceFileDao.update_descendants_path(
            space_id=space_id,
            old_prefix=old_prefix,
            new_prefix=new_prefix,
            level_diff=level_diff,
            folder=folder,
        )
        updated_folder = folder

        # Update OpenFGA parent tuple for the folder itself only.
        await self._replace_resource_parent_tuple(
            object_type="folder",
            object_id=folder_id,
            old_parent_type=old_parent_type,
            old_parent_id=old_parent_id,
            new_parent_type=new_parent_type,
            new_parent_id=new_parent_id_val,
        )

        await self.update_folder_update_time(old_folder_path)
        if new_parent_path != old_folder_path:
            await self.update_folder_update_time(new_parent_path)
        await KnowledgeDao.async_update_knowledge_update_time_by_id(space_id)
        return KnowledgeSpaceFileResponse(**updated_folder.model_dump())

    # ──────────────────────────── Files ───────────────────────────────────────

    async def import_web_link(
        self,
        knowledge_id: int,
        url: str,
        title: str | None = None,
        parent_id: int | None = None,
        file_category_code: str | None = None,
        overwrite: bool = False,
    ) -> KnowledgeFile:
        if parent_id:
            await self._require_permission_id("folder", parent_id, "upload_file", space_id=knowledge_id)
        else:
            await self._require_permission_id("knowledge_space", knowledge_id, "upload_file")

        db_knowledge = await KnowledgeDao.aquery_by_id(knowledge_id)
        if not db_knowledge:
            raise SpaceFolderNotFoundError()
        self._ensure_space_async_task_tenant_consistency(db_knowledge, "import_web_link")

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

        result = await KnowledgeWebLinkImportService.fetch(url)
        file_name = self._build_web_link_file_name(title or result.title, result.final_url)
        markdown_bytes = result.markdown.encode("utf-8")

        duplicate_files: list[KnowledgeFile] = []
        content_duplicates = KnowledgeFileDao.get_file_by_condition(knowledge_id=knowledge_id, md5_=result.content_hash)
        name_duplicates = KnowledgeFileDao.get_file_by_condition(knowledge_id=knowledge_id, file_name=file_name)
        for duplicate_file in [*(content_duplicates or []), *(name_duplicates or [])]:
            if duplicate_file and all(existing.id != duplicate_file.id for existing in duplicate_files):
                duplicate_files.append(duplicate_file)

        if duplicate_files and not overwrite:
            if content_duplicates:
                raise SpaceFileDuplicateError()
            raise SpaceFileNameDuplicateError()
        overwrite_file = duplicate_files[0] if duplicate_files and overwrite else None
        replaced_total_bytes = int(overwrite_file.file_size or 0) if overwrite_file else 0
        replaced_user_bytes = (
            int(overwrite_file.file_size or 0)
            if overwrite_file and overwrite_file.user_id == self.login_user.user_id
            else 0
        )

        role_user_limit_bytes = await QuotaService.get_knowledge_space_upload_limit_bytes(self.login_user)
        current_user_total = int(await SpaceFileDao.get_user_total_file_size(self.login_user.user_id))
        target_tid = db_knowledge.tenant_id
        tenant_remaining_bytes = await QuotaService.get_tenant_storage_remaining_bytes(target_tid)
        if tenant_remaining_bytes is not None:
            tenant_used_at_start_bytes = await QuotaService.get_tenant_storage_used_bytes(target_tid)
            tenant_cap_bytes = tenant_used_at_start_bytes + tenant_remaining_bytes
            next_tenant_total_bytes = tenant_used_at_start_bytes - replaced_total_bytes + result.content_length
        else:
            tenant_cap_bytes = None
            next_tenant_total_bytes = 0
        if tenant_cap_bytes is not None and next_tenant_total_bytes > tenant_cap_bytes:
            blocker = (
                target_tid,
                "tenant_limit",
                round(next_tenant_total_bytes / (1024**3), 2),
                round(tenant_cap_bytes / (1024**3), 2),
                "",
            )
            raise QuotaService._make_storage_quota_error(blocker, "storage_gb")
        if (
            role_user_limit_bytes is not None
            and current_user_total - replaced_user_bytes + result.content_length > role_user_limit_bytes
        ):
            raise SpaceFileSizeLimitError()

        split_rule_dict = FileProcessBase(knowledge_id=knowledge_id).model_dump()
        split_rule_dict["separator"] = _WEB_LINK_SEPARATORS
        split_rule_dict["separator_rule"] = _WEB_LINK_SEPARATOR_RULES
        split_rule_dict["chunk_overlap"] = 0
        normalized_file_category_code = self.normalize_file_category_code(file_category_code)
        if normalized_file_category_code:
            split_rule_dict[self.file_category_code_key] = normalized_file_category_code

        imported_at = datetime.now().isoformat(timespec="seconds")
        web_link_display_title = self._web_link_display_title(file_name)
        if overwrite_file:
            return await self._overwrite_web_link_file(
                db_file=overwrite_file,
                url=url,
                result=result,
                file_name=file_name,
                markdown_bytes=markdown_bytes,
                split_rule_dict=split_rule_dict,
                imported_at=imported_at,
                level=level,
                file_level_path=file_level_path,
                new_parent_type=parent_type,
                new_parent_id=parent_resource_id,
            )

        db_file = KnowledgeFile(
            knowledge_id=knowledge_id,
            tenant_id=db_knowledge.tenant_id,
            file_name=file_name,
            file_size=result.content_length,
            md5=result.content_hash,
            split_rule=json.dumps(split_rule_dict, ensure_ascii=False),
            user_id=self.login_user.user_id,
            user_name=self.login_user.user_name,
            updater_id=self.login_user.user_id,
            updater_name=self.login_user.user_name,
            level=level,
            file_level_path=file_level_path,
            file_source=FileSource.WEB_LINK.value,
            user_metadata={
                "source_type": "web_link",
                "source_url": url,
                "final_url": result.final_url,
                "web_title": web_link_display_title,
                "imported_at": imported_at,
            },
        )

        created_files: list[KnowledgeFile] = []
        minio_client = get_minio_storage_sync()
        html_snapshot_object_name = ""
        try:
            db_file = KnowledgeFileDao.add_file(db_file)
            created_files.append(db_file)
            db_file.object_name = KnowledgeUtils.get_knowledge_file_object_name(db_file.id, db_file.file_name)
            minio_client.put_object_sync(
                bucket_name=minio_client.bucket,
                object_name=db_file.object_name,
                file=markdown_bytes,
                content_type="text/markdown; charset=utf-8",
            )
            if result.html_snapshot:
                html_snapshot_object_name = f"preview/{db_file.id}.html"
                minio_client.put_object_sync(
                    bucket_name=minio_client.bucket,
                    object_name=html_snapshot_object_name,
                    file=result.html_snapshot.encode("utf-8"),
                    content_type="text/html; charset=utf-8",
                )
                db_file.user_metadata = {
                    **(db_file.user_metadata or {}),
                    "html_snapshot_object_name": html_snapshot_object_name,
                }
            db_file = KnowledgeFileDao.update(db_file)
            await self._create_primary_document_for_file(db_file)
            await self._initialize_child_resource_permissions(
                "knowledge_file",
                db_file.id,
                parent_type,
                parent_resource_id,
            )
        except Exception:
            try:
                if getattr(db_file, "object_name", None):
                    minio_client.remove_object_sync(bucket_name=minio_client.bucket, object_name=db_file.object_name)
                if html_snapshot_object_name:
                    minio_client.remove_object_sync(
                        bucket_name=minio_client.bucket,
                        object_name=html_snapshot_object_name,
                    )
                await self._cleanup_created_knowledge_files(created_files)
            except Exception as cleanup_exc:
                logger.warning(f"Failed to cleanup web link import after error: {cleanup_exc}")
            raise

        KnowledgeService.audit_telemetry_service.telemetry_new_knowledge_file(self.login_user)
        preview_cache_key = self.get_preview_cache_key(knowledge_id, result.final_url, md5_value=result.content_hash)
        file_worker.parse_knowledge_file_celery.delay(db_file.id, preview_cache_key)
        await self.update_folder_update_time(file_level_path)
        await KnowledgeDao.async_update_knowledge_update_time_by_id(knowledge_id)
        return db_file

    async def _overwrite_web_link_file(
        self,
        *,
        db_file: KnowledgeFile,
        url: str,
        result: WebLinkImportResult,
        file_name: str,
        markdown_bytes: bytes,
        split_rule_dict: dict,
        imported_at: str,
        level: int,
        file_level_path: str,
        new_parent_type: str,
        new_parent_id: int,
    ) -> KnowledgeFile:
        old_file_level_path = db_file.file_level_path or ""
        old_parent_type, old_parent_id = self._parent_tuple_ref_from_level_path(
            old_file_level_path,
            db_file.knowledge_id,
        )
        minio_client = get_minio_storage_sync()
        old_object_name = db_file.object_name
        object_name = KnowledgeUtils.get_knowledge_file_object_name(db_file.id, file_name)
        html_snapshot_object_name = f"preview/{db_file.id}.html" if result.html_snapshot else ""

        minio_client.put_object_sync(
            bucket_name=minio_client.bucket,
            object_name=object_name,
            file=markdown_bytes,
            content_type="text/markdown; charset=utf-8",
        )
        if result.html_snapshot:
            minio_client.put_object_sync(
                bucket_name=minio_client.bucket,
                object_name=html_snapshot_object_name,
                file=result.html_snapshot.encode("utf-8"),
                content_type="text/html; charset=utf-8",
            )
        if old_object_name and old_object_name != object_name:
            try:
                minio_client.remove_object_sync(bucket_name=minio_client.bucket, object_name=old_object_name)
            except Exception as exc:
                logger.warning(f"Failed to remove old web link object after overwrite: {exc}")

        db_file.file_name = file_name
        db_file.file_size = result.content_length
        db_file.md5 = result.content_hash
        db_file.object_name = object_name
        db_file.split_rule = json.dumps(split_rule_dict, ensure_ascii=False)
        db_file.updater_id = self.login_user.user_id
        db_file.updater_name = self.login_user.user_name
        db_file.level = level
        db_file.file_level_path = file_level_path
        db_file.file_source = FileSource.WEB_LINK.value
        db_file.status = KnowledgeFileStatus.WAITING.value
        db_file.remark = ""
        db_file.similar_status = 0
        db_file.simhash = None
        db_file.user_metadata = {
            "source_type": "web_link",
            "source_url": url,
            "final_url": result.final_url,
            "web_title": self._web_link_display_title(file_name),
            "imported_at": imported_at,
            **({"html_snapshot_object_name": html_snapshot_object_name} if html_snapshot_object_name else {}),
        }
        db_file = await KnowledgeFileDao.async_update(db_file)

        await self._replace_resource_parent_tuple(
            object_type="knowledge_file",
            object_id=db_file.id,
            old_parent_type=old_parent_type,
            old_parent_id=old_parent_id,
            new_parent_type=new_parent_type,
            new_parent_id=new_parent_id,
        )
        await self._sync_document_folder_for_file(db_file.id, file_level_path, level)
        preview_cache_key = self.get_preview_cache_key(
            db_file.knowledge_id,
            result.final_url,
            md5_value=result.content_hash,
        )
        file_worker.retry_knowledge_file_celery.delay(db_file.id, preview_cache_key)
        await KnowledgeSpaceContentStat.enqueue_file_stat_async([db_file.id])
        await self.update_folder_update_time(old_file_level_path)
        if file_level_path != old_file_level_path:
            await self.update_folder_update_time(file_level_path)
        await KnowledgeDao.async_update_knowledge_update_time_by_id(db_file.knowledge_id)
        return db_file

    @staticmethod
    def _web_link_display_title(file_name: str) -> str:
        if file_name.lower().endswith(".md"):
            return file_name[:-3]
        return file_name

    @staticmethod
    def _normalize_web_link_file_name(name: str) -> str:
        cleaned = (name or "").strip()
        if not cleaned:
            return cleaned
        if cleaned.lower().endswith(".md"):
            return cleaned
        return f"{cleaned}.md"

    @staticmethod
    def _build_web_link_file_name(title: str, url: str) -> str:
        display_title = (title or "").strip() or KnowledgeWebLinkImportService._title_from_url(url)
        display_title = re.sub(r"[\x00-\x1f\\/:*?\"<>|]+", " ", display_title)
        display_title = re.sub(r"\s+", " ", display_title).strip(". ").strip()
        if not display_title:
            display_title = "web-link"
        return f"{display_title[:180]}.md"

    @staticmethod
    def _resolve_upload_file_source(file_name: str, default_source: str) -> str:
        file_ext = (file_name.rsplit(".", 1)[-1] if "." in file_name else "").lower()
        if file_ext in _AUDIO_FILE_EXTENSIONS:
            return FileSource.AUDIO_TRANSCRIPT.value
        if file_ext in _VIDEO_FILE_EXTENSIONS:
            return FileSource.VIDEO_TRANSCRIPT.value
        return default_source

    async def _create_primary_document_for_file(self, db_file: KnowledgeFile) -> None:
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

    async def _cleanup_created_knowledge_files(self, created_files: list[KnowledgeFile]) -> None:
        created_file_ids = [created_file.id for created_file in created_files if getattr(created_file, "id", None)]
        if not created_file_ids:
            return
        expanded_ids = await self._cascade_version_links_on_delete(created_file_ids)
        try:
            await self._cleanup_resource_tuples(
                [("knowledge_file", created_file_id) for created_file_id in expanded_ids]
            )
        finally:
            await KnowledgeFileDao.adelete_batch(expanded_ids)

    async def add_file(
        self,
        knowledge_id: int,
        file_path: list[str],
        parent_id: int | None = None,
        file_category_code: str | None = None,
        business_domain_code: str | None = None,
        manual_tag_ids: list[int] | None = None,
        manual_tag_names: list[str] | None = None,
        file_source: FileSource = None,
        skip_approval: bool = False,
    ) -> list[KnowledgeSpaceFileResponse]:
        if file_source is None:
            file_source = FileSource.SPACE_UPLOAD
        if parent_id:
            await self._require_permission_id("folder", parent_id, "upload_file", space_id=knowledge_id)
        else:
            await self._require_permission_id("knowledge_space", knowledge_id, "upload_file")

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
        role_user_limit_bytes = await QuotaService.get_knowledge_space_upload_limit_bytes(self.login_user)
        logger.debug(f"space_file_upload_limit_bytes={role_user_limit_bytes} user_id={self.login_user.user_id}")
        current_user_total = int(await SpaceFileDao.get_user_total_file_size(self.login_user.user_id))

        # Tenant-level cap: applies to the *target tenant* of the destination
        # knowledge space, regardless of the writer's role/admin status.
        # Raises 19403 here if the tenant chain is already exhausted.
        target_tid = db_knowledge.tenant_id
        tenant_remaining_bytes = await QuotaService.get_tenant_storage_remaining_bytes(target_tid)
        if tenant_remaining_bytes is not None:
            tenant_used_at_start_bytes = await QuotaService.get_tenant_storage_used_bytes(target_tid)
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
        split_rule_dict = file_split_rule.model_dump()
        normalized_file_category_code = self.normalize_file_category_code(file_category_code)
        if normalized_file_category_code:
            split_rule_dict[self.file_category_code_key] = normalized_file_category_code
        normalized_business_domain_code = self.normalize_business_domain_code(business_domain_code)
        if normalized_business_domain_code:
            split_rule_dict[self.business_domain_code_key] = normalized_business_domain_code
        process_files = []
        failed_files = []
        preview_cache_keys = []
        created_files = []

        # Check file names against sensitive words before processing any files.
        for fp in file_path:
            fname = fp.rsplit("/", 1)[-1] if "/" in fp else fp
            self._check_filename_sensitive_words(fname)

        async def cleanup_created_files() -> None:
            created_file_ids = [created_file.id for created_file in created_files if getattr(created_file, "id", None)]
            if not created_file_ids:
                return
            # Most rollback paths fire before the V1 doc/version rows are
            # written, so the cascade is a defensive no-op here. Kept for the
            # case where a partial create leaves stale chain rows.
            expanded_ids = await self._cascade_version_links_on_delete(created_file_ids)
            try:
                await self._cleanup_resource_tuples(
                    [("knowledge_file", created_file_id) for created_file_id in expanded_ids]
                )
            finally:
                await KnowledgeFileDao.adelete_batch(expanded_ids)

        try:
            for one in file_path:
                db_file = KnowledgeService.process_one_file(
                    self.login_user,
                    knowledge=db_knowledge,
                    file_info=KnowledgeFileOne(file_path=one, excel_rule=ExcelRule()),
                    split_rule=dict(split_rule_dict),
                    file_kwargs={
                        "level": level,
                        "file_level_path": file_level_path,
                        "file_source": file_source.value,
                    },
                )
                if db_file.status != KnowledgeFileStatus.FAILED.value:
                    next_file_source = self._resolve_upload_file_source(db_file.file_name, file_source.value)
                    if db_file.file_source != next_file_source:
                        db_file.file_source = next_file_source
                        db_file = KnowledgeFileDao.update(db_file)
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
                    failed_file.old_file_level_path = await get_folder_name(db_file.file_level_path)
                    failed_file.file_level_path = file_level_path
                    failed_files.append(failed_file)
                # Tenant-level cap: applies to admins as well; the write triggered by
                # this upload would push the target tenant over its storage_gb cap.
                if tenant_cap_bytes is not None and current_tenant_total_bytes > tenant_cap_bytes:
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
                if role_user_limit_bytes is not None and current_user_total > role_user_limit_bytes:
                    raise SpaceFileSizeLimitError()
            for created_file in created_files:
                await self._initialize_child_resource_permissions(
                    "knowledge_file",
                    created_file.id,
                    parent_type,
                    parent_resource_id,
                )
            await KnowledgeService.apply_manual_upload_tags(
                login_user=self.login_user,
                knowledge=db_knowledge,
                files=process_files,
                manual_tag_ids=manual_tag_ids,
                manual_tag_names=manual_tag_names,
            )
        except Exception:
            try:
                await cleanup_created_files()
            except Exception as cleanup_exc:
                logger.warning(f"Failed to cleanup files after knowledge space upload error: {cleanup_exc}")
            raise
        for index, one in enumerate(process_files):
            file_worker.parse_knowledge_file_celery.delay(one.id, preview_cache_keys[index])
        await self.update_folder_update_time(file_level_path)
        await KnowledgeDao.async_update_knowledge_update_time_by_id(knowledge_id)
        return failed_files + process_files

    async def rename_file(self, file_id: int, new_name: str) -> KnowledgeFile:
        from bisheng.worker.knowledge.rebuild_knowledge_worker import (
            rebuild_knowledge_file_chunk,
        )

        file_record = await self._get_file_for_action(file_id)
        await self._require_permission_id("knowledge_file", file_id, "rename_file", space_id=file_record.knowledge_id)
        space = await KnowledgeDao.aquery_by_id(file_record.knowledge_id)
        if not space:
            raise SpaceNotFoundError()
        self._ensure_space_async_task_tenant_consistency(space, "rename_file")

        if file_record.file_source == FileSource.WEB_LINK.value:
            new_name = self._normalize_web_link_file_name(new_name)

        old_suffix = file_record.file_name.rsplit(".", 1)[-1] if "." in file_record.file_name else ""
        new_suffix = new_name.rsplit(".", 1)[-1] if "." in new_name else ""
        if old_suffix != new_suffix:
            raise SpaceFileExtensionError()
        self._check_filename_sensitive_words(new_name)

        if await SpaceFileDao.count_file_by_name(file_record.knowledge_id, new_name, exclude_id=file_id) > 0:
            raise SpaceFileNameDuplicateError()

        file_record.file_name = new_name
        file_record.updater_id = self.login_user.user_id
        file_record.updater_name = self.login_user.user_name
        if file_record.file_source == FileSource.WEB_LINK.value:
            metadata = dict(file_record.user_metadata or {})
            metadata["web_title"] = self._web_link_display_title(new_name)
            file_record.user_metadata = metadata
        updated_file = await KnowledgeFileDao.async_update(file_record)
        await KnowledgeSpaceContentStat.enqueue_file_stat_async([file_id])

        if updated_file.status == KnowledgeFileStatus.SUCCESS.value:
            rebuild_knowledge_file_chunk.delay(file_id=file_id)
        await self.update_folder_update_time(file_record.file_level_path)
        await KnowledgeDao.async_update_knowledge_update_time_by_id(file_record.knowledge_id)
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
        if await KnowledgeFileDao.acount_by_file_encoding(cleaned, exclude_id=file_id) > 0:
            raise SpaceFileEncodingDuplicateError()

        file_record.file_encoding = cleaned
        file_record.updater_id = self.login_user.user_id
        file_record.updater_name = self.login_user.user_name
        return await KnowledgeFileDao.async_update(file_record)

    async def _cascade_version_links_on_delete(self, file_ids: list[int]) -> list[int]:
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

        pending_per_doc: dict[int, list] = {}
        for fid in file_ids:
            v = await self.version_repo.find_by_knowledge_file_id(fid)
            if v is None:
                continue
            pending_per_doc.setdefault(v.document_id, []).append(v)

        expanded: set[int] = set(file_ids)
        versions_to_delete: list[int] = []
        documents_to_delete: list[int] = []

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
        await self._require_permission_id("knowledge_file", file_id, "delete_file", space_id=file_record.knowledge_id)
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
        await self._cleanup_resource_tuples([("knowledge_file", fid) for fid in expanded_ids])
        await self.update_folder_update_time(file_record.file_level_path)
        await KnowledgeDao.async_update_knowledge_update_time_by_id(file_record.knowledge_id)

    async def get_file_preview(self, file_id: int) -> dict:
        file_record = await self._require_file_relation(file_id, "can_read")
        await self._require_permission_id("knowledge_file", file_id, "view_file", space_id=file_record.knowledge_id)

        asyncio.create_task(self._log_file_preview_success(file_record))  # noqa: RUF006
        if not self._is_portal_bff_proxy_request():
            asyncio.create_task(self._log_portal_document_read_success(file_record))  # noqa: RUF006

        return KnowledgeService.get_file_share_detail(file_record)

    def _is_portal_bff_proxy_request(self) -> bool:
        return is_portal_bff_proxy_source(self.request.headers.get(PORTAL_BFF_TELEMETRY_SOURCE_HEADER))

    async def _log_portal_document_read_success(self, file_record: KnowledgeFile) -> None:
        try:
            PortalTelemetryEventService.log_event_sync(
                user_id=self.login_user.user_id,
                event_type=BaseTelemetryTypeEnum.PORTAL_DOCUMENT_READ,
                event_data=PortalDocumentReadEventData(
                    source_app="bisheng_my_knowledge",
                    scene="document_preview",
                    entry_point="my_knowledge_preview",
                    resource_type="document",
                    space_id=file_record.knowledge_id,
                    file_id=file_record.id,
                    status="success",
                ),
            )
        except (RuntimeError, ValueError, TypeError):
            logger.exception("Failed to log portal document read telemetry.")

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

    async def get_file_download(self, file_id: int, *, space_id: int | None = None) -> dict:
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
    async def get_space_tags(self, space_id: int) -> list[Tag | ReviewTag]:
        await self._require_read_permission(space_id)
        await self._require_permission_id("knowledge_space", space_id, "view_space")
        tags = await TagDao.get_tags_by_business(
            business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE, business_id=str(space_id)
        )
        review_tags = await ReviewTagDao.get_tags_by_business(
            business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE,
            business_id=str(space_id),
        )
        approved_names = {(tag.name or "").strip().lower() for tag in tags if (tag.name or "").strip()}
        merged: list[Tag | ReviewTag] = list(tags)
        for review_tag in review_tags:
            name = (review_tag.name or "").strip()
            if name and name.lower() not in approved_names:
                merged.append(review_tag)

        seen_names = {(tag.name or "").strip().lower() for tag in merged if (tag.name or "").strip()}
        library_ids = await KnowledgeTagLibraryLinkDao.alist_library_ids_by_knowledge(space_id)
        for library_id in library_ids:
            library_tags = await TagLibraryTagService.list_tags(int(library_id))
            for library_tag in library_tags:
                name = (library_tag.name or "").strip()
                if not name:
                    continue
                name_key = name.lower()
                if name_key in seen_names:
                    continue
                seen_names.add(name_key)
                merged.append(library_tag)

        return merged

    async def _find_bound_library_tag_by_name(self, space_id: int, tag_name: str) -> Tag | None:
        normalized = (tag_name or "").strip()
        if not normalized:
            return None
        library_ids = await KnowledgeTagLibraryLinkDao.alist_library_ids_by_knowledge(space_id)
        for library_id in library_ids:
            library_tags = await TagLibraryTagService.list_tags(int(library_id))
            for library_tag in library_tags:
                if (library_tag.name or "").strip() == normalized:
                    return library_tag
        return None

    async def add_space_tag(self, space_id: int, tag_name: str) -> Tag | ReviewTag:
        await self._require_permission_id("knowledge_space", space_id, "edit_space")

        existing_tags = await TagDao.get_tags_by_business(
            business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE,
            business_id=str(space_id),
            name=tag_name,
        )
        for tag in existing_tags:
            if tag.name == tag_name:
                return tag

        existing_review_tags = await ReviewTagDao.get_tags_by_business(
            business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE,
            business_id=str(space_id),
            name=tag_name,
        )
        for review_tag in existing_review_tags:
            if review_tag.name == tag_name:
                return review_tag

        library_tag = await self._find_bound_library_tag_by_name(space_id, tag_name)
        if library_tag:
            await self._require_review_tag_feature_enabled()
            return library_tag

        await self._require_review_tag_feature_enabled()

        new_tag = ReviewTag(
            name=tag_name,
            user_id=self.login_user.user_id,
            business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE,
            business_id=str(space_id),
            resource_type=TagResourceTypeEnum.MANUAL_TAG,
            is_deleted=False,
            create_time=datetime.now(),
            update_time=datetime.now(),
        )
        return await ReviewTagDao.ainsert_review_tag(new_tag)

    async def delete_space_tag(self, space_id: int, tag_id: int):
        await self._require_permission_id("knowledge_space", space_id, "edit_space")
        return await TagDao.delete_business_tag(
            tag_id,
            business_id=str(space_id),
            business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE,
        )

    async def update_file_tags(self, space_id: int, file_id: int, tag_ids: list[int], review_tag_ids: list[int]):
        """2：支持对单文件的标签管理: Overwrite tags for a single file."""
        await self._get_file_for_action(file_id, space_id=space_id)
        await self._require_permission_id("knowledge_file", file_id, "rename_file", space_id=space_id)

        resource_id = str(file_id)
        resource_type = ResourceTypeEnum.SPACE_FILE
        if tag_ids and len(tag_ids) > 0:
            await TagDao.aupdate_resource_tags(tag_ids, resource_id, resource_type, self.login_user.user_id)
        if review_tag_ids and len(review_tag_ids) > 0:
            await self._require_review_tag_feature_enabled()
            await ReviewTagDao.aupdate_resource_tags(
                review_tag_ids, resource_id, resource_type, self.login_user.user_id
            )
        await KnowledgeDao.async_update_knowledge_update_time_by_id(space_id)

    async def batch_add_file_tags(
        self, space_id: int, file_ids: list[int], tag_ids: list[int], review_tag_ids: list[int]
    ):
        """1：支持对文件批量添加标签: Batch add tags to files."""
        await self._require_read_permission(space_id)
        if not file_ids or not tag_ids or not review_tag_ids:
            return

        files = await self._get_space_files_or_raise(space_id, file_ids)

        resource_type = ResourceTypeEnum.SPACE_FILE
        for file_record in files:
            await self._require_permission_id("knowledge_file", file_record.id, "rename_file", space_id=space_id)
            if tag_ids and len(tag_ids) > 0:
                await TagDao.add_tags(tag_ids, str(file_record.id), resource_type, self.login_user.user_id)
            if review_tag_ids and len(review_tag_ids) > 0:
                await self._require_review_tag_feature_enabled()
                await ReviewTagDao.add_tags(review_tag_ids, str(file_record.id), resource_type, self.login_user.user_id)

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
        file_category_code = self.normalize_file_category_code(req_data.get("file_category_code"))
        business_domain_code = self.normalize_business_domain_code(req_data.get("business_domain_code"))
        if file_category_code:
            for retry_file in db_file_retry:
                retry_file["split_rule"] = self.with_file_category_code_in_split_rule(
                    retry_file.get("split_rule"),
                    file_category_code,
                )
        if business_domain_code:
            for retry_file in db_file_retry:
                retry_file["split_rule"] = self.with_business_domain_code_in_split_rule(
                    retry_file.get("split_rule"),
                    business_domain_code,
                )

        id2input = {file.get("id"): file for file in db_file_retry}
        file_ids = list(id2input.keys())
        db_files = await KnowledgeFileDao.aget_file_by_ids(file_ids)
        if not db_files:
            return []

        for db_file in db_files:
            if db_file.knowledge_id != space_id:
                raise SpaceFileNotFoundError()
            await self._require_resource_permission("can_edit", "knowledge_file", db_file.id)

        tmp, file_level_path = await self.process_retry_files(db_files, id2input, self.login_user)
        await KnowledgeService.apply_manual_upload_tags(
            login_user=self.login_user,
            knowledge=space,
            files=tmp,
            manual_tag_ids=req_data.get("manual_tag_ids"),
            manual_tag_names=req_data.get("manual_tag_names"),
        )
        if tmp:
            await KnowledgeSpaceContentStat.enqueue_file_stat_async([one.id for one in tmp])

        for folder_path in file_level_path:
            await self.update_folder_update_time(folder_path)

        await KnowledgeDao.async_update_knowledge_update_time_by_id(space_id)
        return []

    async def batch_retry_failed_files(self, space_id: int, file_ids: list[int]):
        from bisheng.worker import retry_knowledge_file_celery

        space = await KnowledgeDao.aquery_by_id(space_id)
        if not space:
            raise SpaceNotFoundError()
        await self._require_read_permission(space_id)
        self._ensure_space_async_task_tenant_consistency(space, "batch_retry_failed_files")

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
            if file.file_type == FileType.FILE.value and file.status in retryable_status:
                await self._require_resource_permission("can_edit", "knowledge_file", file.id)
                retry_knowledge_file_celery.delay(file.id)
                all_file_ids.append(file.id)
                all_file_level_path.add(file.file_level_path)
            elif file.file_type == FileType.DIR.value:
                await self._require_resource_permission("can_edit", "folder", file.id)
                all_failed_files = await SpaceFileDao.get_children_by_prefix(
                    knowledge_id=space_id, prefix=file.file_level_path + f"/{file.id}"
                )
                for item in all_failed_files:
                    if item.status in retryable_status and item.file_type == FileType.FILE.value:
                        await self._require_resource_permission("can_edit", "knowledge_file", item.id)
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

    async def batch_delete(self, knowledge_id: int, file_ids: list[int], folder_ids: list[int]):
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
                file_record = await self._get_file_for_action(file_id, space_id=knowledge_id)
                await self._require_permission_id("knowledge_file", file_id, "delete_file", space_id=knowledge_id)
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
            await self._cleanup_resource_tuples([("knowledge_file", file_id) for file_id in expanded_file_ids])

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

    async def batch_download(self, space_id: int, file_ids: list[int], folder_ids: list[int]) -> str:
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
            await self._require_permission_id("knowledge_file", file_id, "download_file", space_id=space_id)
            direct_files.append(file_record)

        # Files & sub-folders under every requested folder_id
        folder_db_records: list[KnowledgeFile] = []
        for folder_id in self._dedupe_ids(folder_ids):
            folder = await self._get_folder_for_action(space_id, folder_id)
            await self._require_permission_id("folder", folder_id, "download_folder", space_id=space_id)
            prefix = f"{folder.file_level_path}/{folder.id}"
            descendants = await SpaceFileDao.get_children_by_prefix(folder.knowledge_id, prefix)
            for descendant in descendants:
                if descendant.file_type == FileType.DIR.value:
                    await self._require_permission_id("folder", descendant.id, "download_folder", space_id=space_id)
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
        all_records: list[KnowledgeFile] = direct_files + folder_db_records

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

        def resolve_dir_path(file_level_path: str | None) -> str:
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
                if rec.file_source == FileSource.CHANNEL.value and rec.preview_file_object_name:
                    target_object_name = rec.preview_file_object_name
                    name, _ = os.path.splitext(rec.file_name)
                    local_path = os.path.join(local_dir, f"{name}.html")

                if not target_object_name:  # no stored object – skip
                    continue

                try:
                    response = minio.download_object_sync(object_name=target_object_name)
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
            await minio.put_object_tmp(minio_object_name, Path(zip_path), content_type="application/zip")
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
            MembershipStatusEnum.ACTIVE if space.auth_type == AuthTypeEnum.PUBLIC else MembershipStatusEnum.PENDING
        )

        existing = await SpaceChannelMemberDao.async_find_member(space_id, self.login_user.user_id)
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
            if existing.status == MembershipStatusEnum.PENDING and target_status == MembershipStatusEnum.PENDING:
                return {
                    "status": "pending",
                    "space_id": space_id,
                }

        if not existing or existing.status == MembershipStatusEnum.REJECTED:
            count = await SpaceChannelMemberDao.async_count_user_space_subscriptions(self.login_user.user_id)
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
                    ip_address=get_request_ip(self.request) if self.request else None,
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
            "status": "subscribed" if member.status == MembershipStatusEnum.ACTIVE else "pending",
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

        current_membership = await SpaceChannelMemberDao.async_find_member(space_id, self.login_user.user_id)
        if not await self._can_unsubscribe_space(space, current_membership):
            raise SpacePermissionDeniedError()

        await self._revoke_direct_space_user_permissions(space_id, self.login_user.user_id)
        deleted = await SpaceChannelMemberDao.delete_space_member(space_id, self.login_user.user_id)
        return deleted
