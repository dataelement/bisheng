from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bisheng.common.models.space_channel_member import UserRoleEnum
from bisheng.knowledge.domain.constants import normalize_business_domain_code
from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum, KnowledgeBase
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileRead
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceOwnerTypeEnum,
)


class SpaceSubscriptionStatusEnum(str, Enum):
    SUBSCRIBED = "subscribed"
    PENDING = "pending"
    REJECTED = "rejected"
    NOT_SUBSCRIBED = "not_subscribed"


class KnowledgeSpaceCreateReq(BaseModel):
    name: str = Field(..., max_length=200, description="Knowledge Space Name")
    description: str | None = Field(None, description="Knowledge Space Description")
    icon: str | None = Field(None, description="Icon Object Name")
    auth_type: AuthTypeEnum = Field(AuthTypeEnum.PUBLIC, description="Authentication Type")
    is_released: bool = Field(default=False, description="Knowledge Space Status")
    space_level: KnowledgeSpaceLevelEnum = Field(
        default=KnowledgeSpaceLevelEnum.PERSONAL,
        description="Knowledge space level: public/department/team/personal",
    )
    department_id: int | None = Field(None, description="Department id for department spaces")
    user_group_id: int | None = Field(None, description="User group id for team spaces")
    auto_tag_enabled: bool = Field(default=False, description="Whether uploaded files participate in auto tagging")
    auto_tag_library_id: int | None = Field(
        default=None, description="Bound knowledge-space tag library ID (legacy single binding)"
    )
    auto_tag_library_ids: list[int] | None = Field(
        default=None,
        description="Bound knowledge-space tag library IDs (supports multiple libraries)",
    )
    auto_tag_custom_tags: list[str] | None = Field(
        default=None,
        description=(
            "Custom auto-tag list for this space; mutually exclusive with "
            "auto_tag_library_id. When provided, a private tag library is "
            "upserted server-side."
        ),
    )


class KnowledgeSpaceInfoResp(KnowledgeBase):
    id: int = Field(..., description="Knowledge Space ID")
    business_domain_codes: list[str] = Field(
        default_factory=list,
        description="Portal business-domain codes bound to this knowledge space",
    )
    is_pinned: bool = Field(default=False, description="Knowledge Space pinned by current user or not")
    user_name: str = Field(default="", description="Knowledge Space creator name")
    avatar: str | None = Field(default=None, description="Knowledge Space creator avatar")
    follower_num: int = Field(1, description="Follower Number")
    file_num: int = Field(1, description="Total File Number")
    is_followed: bool = Field(default=False, description="Knowledge Space followed by current user or not")
    is_pending: bool = Field(default=False, description="Knowledge Space pending or not")
    subscription_status: SpaceSubscriptionStatusEnum = Field(
        default=SpaceSubscriptionStatusEnum.NOT_SUBSCRIBED,
        description="Current user subscription status",
    )
    can_unsubscribe: bool = Field(default=False, description="Whether current user can unsubscribe from this space")
    user_role: UserRoleEnum | None = Field(default=None, description="Knowledge Space user role")
    space_kind: Literal["normal", "department"] = Field(default="normal", description="Knowledge space kind")
    department_id: int | None = Field(default=None, description="Bound department id for department spaces")
    department_name: str | None = Field(default=None, description="Bound department name for department spaces")
    approval_enabled: bool | None = Field(default=None, description="Whether department-space uploads require approval")
    sensitive_check_enabled: bool | None = Field(
        default=None,
        description="Whether department-space uploads require content safety check",
    )
    space_level: KnowledgeSpaceLevelEnum = Field(
        default=KnowledgeSpaceLevelEnum.PERSONAL,
        description="Knowledge space level",
    )
    owner_type: KnowledgeSpaceOwnerTypeEnum | None = Field(default=None, description="Scope owner type")
    owner_id: int | None = Field(default=None, description="Scope owner id")
    owner_name: str | None = Field(default=None, description="Scope owner display name")
    auto_tag_mode: Literal["library", "custom"] = Field(
        default="library",
        description="Discriminator: 'library' for an admin-managed tag library, 'custom' for a private library backed by user-entered tags.",
    )
    auto_tag_custom_tags: list[str] | None = Field(
        default=None,
        description="Populated only when auto_tag_mode == 'custom'; mirrors the private library's tag list.",
    )

    @field_validator("business_domain_codes", mode="before")
    @classmethod
    def normalize_business_domain_codes(cls, value: Any):
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip().upper() for item in value if str(item).strip()]
        return value


class ShougangPortalSpaceInfoReq(BaseModel):
    space_ids: list[int] = Field(..., min_length=1, max_length=200, description="Knowledge Space IDs")


class ShougangPortalSpaceInfoError(BaseModel):
    code: int = Field(..., description="Error code")
    message: str = Field(..., description="Error message")


class ShougangPortalSpaceInfoItemResp(BaseModel):
    id: int = Field(..., description="Knowledge Space ID")
    data: dict = Field(default_factory=dict, description="Knowledge Space info; empty when failed")
    error: ShougangPortalSpaceInfoError | None = Field(default=None, description="Error info when failed")


class ShougangPortalSpaceInfoResp(BaseModel):
    spaces: list[ShougangPortalSpaceInfoItemResp] = Field(
        default_factory=list,
        description="Knowledge Space info items",
    )


class KnowledgeSpaceCreateOptionDepartment(BaseModel):
    id: int
    name: str
    path_name: str | None = None


class KnowledgeSpaceCreateOptionUserGroup(BaseModel):
    id: int
    group_name: str


class KnowledgeSpaceCreateOptionsResp(BaseModel):
    can_create_public: bool = False
    can_create_department: bool = False
    can_create_team: bool = False
    can_create_personal: bool = True
    departments: list[KnowledgeSpaceCreateOptionDepartment] = Field(default_factory=list)
    user_groups: list[KnowledgeSpaceCreateOptionUserGroup] = Field(default_factory=list)
    default_space_level: KnowledgeSpaceLevelEnum = KnowledgeSpaceLevelEnum.PERSONAL


class KnowledgeSpaceCreateOptionDepartmentsResp(BaseModel):
    data: list[dict] = Field(default_factory=list)
    total: int = 0


class KnowledgeSpaceCreateOptionUserGroupsResp(BaseModel):
    data: list[KnowledgeSpaceCreateOptionUserGroup] = Field(default_factory=list)
    total: int = 0


class GroupedKnowledgeSpacesResp(BaseModel):
    public_spaces: list[KnowledgeSpaceInfoResp] = Field(default_factory=list)
    department_spaces: list[KnowledgeSpaceInfoResp] = Field(default_factory=list)
    team_spaces: list[KnowledgeSpaceInfoResp] = Field(default_factory=list)
    personal_spaces: list[KnowledgeSpaceInfoResp] = Field(default_factory=list)


class ShougangPortalSpaceLevelItem(BaseModel):
    value: KnowledgeSpaceLevelEnum
    label: str


class ShougangPortalSpaceLevelsResp(BaseModel):
    levels: list[ShougangPortalSpaceLevelItem] = Field(default_factory=list)


class ShougangPortalPersonalSpaceItemResp(BaseModel):
    id: int = Field(..., description="Knowledge Space ID")
    name: str = Field(..., description="Knowledge Space name")
    description: str = Field(default="", description="Knowledge Space description")
    file_count: int = Field(default=0, description="Successful file count")
    updated_at: str = Field(default="", description="Last update time")
    is_favorite: bool = Field(default=False, description="是否为『我的收藏』固定库")


class ShougangPortalPersonalSpacesResp(BaseModel):
    data: list[ShougangPortalPersonalSpaceItemResp] = Field(default_factory=list)
    total: int = 0


class ShougangPortalFavoriteCreateReq(BaseModel):
    source_space_id: int = Field(..., gt=0)
    source_file_id: int = Field(..., gt=0)


class ShougangPortalFavoriteCreateResp(BaseModel):
    favorite_file_id: int
    space_id: int
    source_space_id: int
    source_file_id: int
    title: str = ""


class ShougangPortalFavoriteRemoveReq(BaseModel):
    source_space_id: int = Field(..., gt=0)
    source_file_id: int = Field(..., gt=0)


class ShougangPortalFavoriteRemoveResp(BaseModel):
    removed: bool = False


class ShougangPortalFavoriteStatusItem(BaseModel):
    space_id: int = Field(..., gt=0)
    file_id: int = Field(..., gt=0)


class ShougangPortalFavoriteStatusReq(BaseModel):
    items: list[ShougangPortalFavoriteStatusItem] = Field(default_factory=list)


class ShougangPortalFavoriteStatusResultItem(BaseModel):
    space_id: int
    file_id: int
    favorited: bool = False


class ShougangPortalFavoriteStatusResp(BaseModel):
    data: list[ShougangPortalFavoriteStatusResultItem] = Field(default_factory=list)


class ShougangPortalFavoriteFileItem(BaseModel):
    favorite_file_id: int
    source_space_id: int
    source_file_id: int
    title: str = ""
    file_name: str = ""
    status: Literal["valid", "invalid"] = "valid"
    updated_at: str = ""


class ShougangPortalFavoriteFilesResp(BaseModel):
    data: list[ShougangPortalFavoriteFileItem] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class ShougangPortalFavoriteSpaceResp(BaseModel):
    space_id: int
    name: str = "我的收藏"


class ShougangPortalShareType(str, Enum):
    LINK = "link"
    INVITE_CODE = "invite_code"


class ShougangPortalShareVisibility(str, Enum):
    DEPARTMENT = "department"
    PUBLIC = "public"


class ShougangPortalSharePermissions(BaseModel):
    view: bool = Field(default=True)
    download: bool = Field(default=False)
    upload: bool = Field(default=False)


class ShougangPortalShareLinkCreateReq(BaseModel):
    space_id: int = Field(..., gt=0, description="Source knowledge space ID")
    file_id: int = Field(..., gt=0, description="Source file ID")
    share_type: ShougangPortalShareType = Field(default=ShougangPortalShareType.LINK)
    visibility: ShougangPortalShareVisibility = Field(default=ShougangPortalShareVisibility.DEPARTMENT)
    allow_download: bool = Field(default=False)
    password: str = Field(default="", max_length=128)
    expire_seconds: int = Field(default=0, ge=0, le=31_536_000)


class ShougangPortalShareLinkCreateResp(BaseModel):
    share_token: str
    link: str
    invite_code: str = ""
    expire_seconds: int = 0


class ShougangPortalShareLinkMetaResp(BaseModel):
    share_token: str
    file_name: str = ""
    share_type: ShougangPortalShareType = ShougangPortalShareType.LINK
    visibility: ShougangPortalShareVisibility = ShougangPortalShareVisibility.DEPARTMENT
    permissions: ShougangPortalSharePermissions = Field(default_factory=ShougangPortalSharePermissions)
    requires_password: bool = False
    requires_invite_code: bool = False
    expired: bool = False


class ShougangPortalShareLinkVerifyReq(BaseModel):
    password: str = Field(default="", max_length=128)
    invite_code: str = Field(default="", max_length=32)


class ShougangPortalShareLinkAccessResp(BaseModel):
    share_token: str
    space_id: int
    file_id: int
    allow_download: bool = False


class ShougangPortalTagSearchReq(BaseModel):
    space_ids: list[int] = Field(default_factory=list, max_length=200, description="Candidate knowledge space IDs")
    space_level: KnowledgeSpaceLevelEnum | None = Field(default=None, description="Knowledge space level filter")
    business_domain_code: str | None = Field(
        default=None, max_length=16, description="Business domain code from file_encoding segment 3"
    )

    @field_validator("business_domain_code", mode="before")
    @classmethod
    def normalize_business_domain_code_field(cls, value: Any):
        if value in (None, ""):
            return None
        normalized = normalize_business_domain_code(value)
        if not normalized:
            raise ValueError("business_domain_code is invalid")
        return normalized


class ShougangPortalTagSearchResp(BaseModel):
    tags: list[str] = Field(default_factory=list)


class ShougangPortalDomainFileCountReq(BaseModel):
    codes: list[str] = Field(
        default_factory=list, max_length=200, description="Business-domain codes, e.g. ['PP','QM']"
    )


class ShougangPortalDomainFileCountResp(BaseModel):
    counts: dict[str, int] = Field(default_factory=dict)


class ShougangPortalSpaceBusinessDomainCodesItem(BaseModel):
    space_id: int = Field(..., gt=0)
    business_domain_codes: list[str] = Field(default_factory=list, max_length=200)


class ShougangPortalSpaceBusinessDomainCodesSyncReq(BaseModel):
    bindings: list[ShougangPortalSpaceBusinessDomainCodesItem] = Field(default_factory=list, max_length=500)


class ShougangPortalSpaceBusinessDomainCodesSyncResp(BaseModel):
    updated: int = 0


class ShougangPortalFileSearchReq(BaseModel):
    q: str | None = Field(default=None, description="Search keyword")
    tag: str | None = Field(default=None, description="Space tag name")
    space_ids: list[int] = Field(default_factory=list, max_length=200, description="Candidate knowledge space IDs")
    space_level: KnowledgeSpaceLevelEnum | None = Field(default=None, description="Knowledge space level filter")
    file_ext: str | None = Field(default=None, description="File extension filter")
    document_type: str | None = Field(default=None, description="Document type code from file_encoding segment 2")
    business_domain_code: str | None = Field(
        default=None, max_length=16, description="Business domain code from file_encoding segment 3"
    )
    sort: str = Field(
        default="relevance", description="Sort mode: relevance / updated_at / updated_at_desc / updated_at_asc"
    )
    rerank_model_id: str | None = Field(
        default=None, description="Optional rerank model ID for this portal search request"
    )
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    @field_validator("business_domain_code", mode="before")
    @classmethod
    def normalize_business_domain_code_field(cls, value: Any):
        if value in (None, ""):
            return None
        normalized = normalize_business_domain_code(value)
        if not normalized:
            raise ValueError("business_domain_code is invalid")
        return normalized


class ShougangPortalFileTagResp(BaseModel):
    tag_name: str = ""
    resource_type: str = ""


class ShougangPortalFileItemResp(BaseModel):
    id: int
    space_id: int
    title: str
    summary: str = ""
    source: str = ""
    updated_at: str = ""
    tags: list[str] = Field(default_factory=list)
    tag_infos: list[ShougangPortalFileTagResp] = Field(default_factory=list)
    file_ext: str = ""
    file_size: str = ""
    file_encoding: str = ""
    folder_path: str = Field(
        default="",
        description="Readable source folder path '<source space>/<folder>/<folder>'. "
        "Empty when the file has no resolvable source (e.g. uploaded "
        "directly to the public space without publish metadata).",
    )
    source_path: str = Field(
        default="",
        description="Readable document source path '<source space>><folder>/<file>'; "
        "root-level source files use only '<source space>'.",
    )


class ShougangPortalFileSearchResp(BaseModel):
    data: list[ShougangPortalFileItemResp] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class ShougangPortalQaFileSearchReq(BaseModel):
    q: str = Field(..., min_length=1, description="File name keyword")
    space_ids: list[int] = Field(default_factory=list, max_length=200, description="Candidate knowledge space IDs")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class ShougangPortalQaFileSearchResp(ShougangPortalFileSearchResp):
    pass


class ShougangPortalHomeSectionReq(BaseModel):
    tag: str
    page_size: int = Field(default=6, ge=1, le=100)


class ShougangPortalHomeReq(BaseModel):
    space_ids: list[int] = Field(default_factory=list, max_length=200, description="Candidate knowledge space IDs")
    space_level: KnowledgeSpaceLevelEnum | None = Field(default=None, description="Knowledge space level filter")
    sections: list[ShougangPortalHomeSectionReq] = Field(default_factory=list, max_length=20)
    hot_tags_limit: int = Field(default=8, ge=0, le=100)


class ShougangPortalHomeResp(BaseModel):
    sections: dict[str, list[ShougangPortalFileItemResp]] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class ShougangPortalTelemetryEventReq(BaseModel):
    event_type: Literal["portal_favorite", "portal_qa", "portal_document_read", "portal_document_download"]
    source_app: str = Field(..., min_length=1, max_length=64)
    scene: str = Field(..., min_length=1, max_length=128)
    entry_point: str = Field(..., min_length=1, max_length=128)
    resource_type: str = Field(default="document", max_length=64)
    status: Literal["success"] = "success"
    space_id: int | str | None = None
    file_id: int | str | None = None
    target_space_id: int | str | None = None
    source_space_id: int | str | None = None
    source_file_id: int | str | None = None
    conversation_id: str | None = Field(default=None, max_length=128)


class ShougangPortalHomeStatsResp(BaseModel):
    read_count: int = 0
    favorite_count: int = 0
    qa_count: int = 0
    total_files: int = 0


class KnowledgeSpaceUpdateReq(BaseModel):
    name: str | None = Field(None, max_length=200, description="Knowledge Space Name")
    description: str | None = Field(None, description="Knowledge Space Description")
    icon: str | None = Field(None, description="Icon Object Name")
    auth_type: AuthTypeEnum | None = Field(None, description="Authentication Type")
    is_released: bool = Field(default=False, description="Knowledge Space Status")
    auto_tag_enabled: bool | None = Field(
        default=None, description="Whether uploaded files participate in auto tagging"
    )
    auto_tag_library_id: int | None = Field(
        default=None, description="Bound knowledge-space tag library ID (legacy single binding)"
    )
    auto_tag_library_ids: list[int] | None = Field(
        default=None,
        description="Bound knowledge-space tag library IDs (supports multiple libraries)",
    )
    auto_tag_custom_tags: list[str] | None = Field(
        default=None,
        description=(
            "Custom auto-tag list for this space; mutually exclusive with "
            "auto_tag_library_id. When provided, a private tag library is "
            "upserted server-side."
        ),
    )


class DepartmentKnowledgeSpaceBatchItem(BaseModel):
    department_id: int = Field(..., description="Department.id")
    name: str | None = Field(None, max_length=200, description="Optional custom space name")
    description: str | None = Field(None, description="Optional custom space description")
    icon: str | None = Field(None, description="Optional icon object name")
    auth_type: AuthTypeEnum | None = Field(None, description="Optional auth type override")
    is_released: bool | None = Field(None, description="Optional release override")


class DepartmentKnowledgeSpaceBatchCreateReq(BaseModel):
    items: list[DepartmentKnowledgeSpaceBatchItem] = Field(
        default_factory=list,
        description="Department knowledge space batch create items",
    )


class FolderCreateReq(BaseModel):
    name: str = Field(..., description="Folder Name")
    parent_id: int | None = Field(None, description="Parent Folder ID")


class FolderRenameReq(BaseModel):
    name: str = Field(..., description="New Folder Name")


class MoveFolderReq(BaseModel):
    target_folder_id: int | None = Field(default=None, description="Target folder ID; null means root")


class FileCreateReq(BaseModel):
    file_path: list[str] = Field(..., description="File Path")
    parent_id: int | None = Field(None, description="Parent Folder ID")
    file_category_code: str | None = Field(None, max_length=16, description="Selected business file category code")
    business_domain_code: str | None = Field(None, max_length=16, description="Selected business domain code")
    manual_tag_ids: list[int] = Field(default_factory=list, description="Selected existing tag IDs")
    manual_tag_names: list[str] = Field(default_factory=list, description="Selected tag names")

    @field_validator("business_domain_code", mode="before")
    @classmethod
    def normalize_business_domain_code_field(cls, value: Any):
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        normalized = normalize_business_domain_code(value)
        if not normalized:
            raise ValueError("business_domain_code is invalid")
        return normalized

    @field_validator("manual_tag_ids", mode="before")
    @classmethod
    def normalize_manual_tag_ids(cls, value: Any):
        if value is None:
            return []
        return value

    @field_validator("manual_tag_names", mode="before")
    @classmethod
    def normalize_manual_tag_names(cls, value: Any):
        if value is None:
            return []
        return value


class WebLinkCreateReq(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048, description="Web page URL")
    title: str | None = Field(None, max_length=200, description="Optional display title")
    parent_id: int | None = Field(None, description="Parent Folder ID")
    file_category_code: str | None = Field(None, max_length=16, description="Selected business file category code")
    overwrite: bool = Field(False, description="Overwrite an existing web link file with the same name or content")


class UploadFolderRecommendFileReq(BaseModel):
    client_file_id: str = Field(..., min_length=1, max_length=128, description="Frontend local file ID")
    file_name: str = Field(..., min_length=1, max_length=255, description="Upload file name")


class UploadFolderRecommendationReq(BaseModel):
    files: list[UploadFolderRecommendFileReq] = Field(
        default_factory=list,
        max_length=100,
        description="Files that need upload folder recommendations",
    )


class UploadFolderRecommendationItemResp(BaseModel):
    client_file_id: str
    file_name: str
    recommended_folder_id: int | None = None
    recommended_folder_name: str = "根目录"
    recommended_folder_path: str = "根目录"
    reason: str = ""


class UploadFolderRecommendationResp(BaseModel):
    items: list[UploadFolderRecommendationItemResp] = Field(default_factory=list)


class MoveFileFolderReq(BaseModel):
    target_folder_id: int | None = Field(default=None, description="Target folder ID; null means root")


class ShougangPortalUploadedFileResp(BaseModel):
    id: int
    knowledge_id: int
    knowledge_name: str = ""
    space_level: KnowledgeSpaceLevelEnum | None = None
    business_domain_codes: list[str] = Field(default_factory=list)
    file_name: str
    file_level_path: str = ""
    parent_id: int | None = None
    folder_path_name: str = "根目录"
    status: int | None = None
    file_encoding: str | None = None
    tags: list[dict] = Field(default_factory=list)
    abstract: str = ""
    create_time: str = ""
    update_time: str = ""


class FileRenameReq(BaseModel):
    name: str = Field(..., description="New File Name")


class FileEncodingUpdateReq(BaseModel):
    encoding: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="New file encoding (free text, 1-64 chars)",
    )


class BatchDeleteReq(BaseModel):
    file_ids: list[int] = Field(default_factory=list, description="List of file IDs to delete")
    folder_ids: list[int] = Field(default_factory=list, description="List of folder IDs to delete")


class BatchDownloadReq(BaseModel):
    file_ids: list[int] = Field(default_factory=list, description="List of file IDs to download")
    folder_ids: list[int] = Field(default_factory=list, description="List of folder IDs to download")


class ChatReq(BaseModel):
    model_config = ConfigDict(validate_by_alias=True, validate_by_name=True)

    query: str = Field(..., description="User Query")
    model_id: int = Field(..., alias="modelId", description="Selected LLM model ID")


class ChatFolderReq(ChatReq):
    folder_id: int = Field(default=0, description="Folder ID")
    chat_id: str = Field(..., description="Chat ID")
    tags: list[dict] | None = Field(None, description="List of Tag info for filtering")


class SubscribeSpaceResp(BaseModel):
    status: str = Field(..., description="Subscription status: 'subscribed' or 'pending'")
    space_id: int = Field(..., description="Knowledge Space ID")


class SpaceListReq(BaseModel):
    parent_id: int | None = Field(None, description="Parent Folder ID; omit for root level")
    page: int = Field(1, ge=1, description="Page number (1-indexed)")
    page_size: int = Field(20, ge=1, le=200, description="Items per page")


class SpaceMemberResponse(BaseModel):
    """Space Member Response"""

    user_id: int = Field(..., description="User ID")
    user_name: str = Field(..., description="User Name")
    user_avatar: str | None = Field(None, description="User Avatar URL")
    user_role: str = Field(..., description="User Role in Space: creator / admin / member")
    user_groups: list[dict] = Field(
        default_factory=list,
        description="User Groups the member belongs to, each group is represented as a dict with group details",
    )


class SpaceMemberPageResponse(BaseModel):
    """Space Member Page Response"""

    data: list[SpaceMemberResponse] = Field(
        default_factory=list, description="List of space members in the current page"
    )
    total: int = Field(..., description="Total number of space members")


class UpdateSpaceMemberRoleRequest(BaseModel):
    """Update Space Member Role Request"""

    space_id: int = Field(default=0, description="Space ID")
    user_id: int = Field(..., description="Target User ID")
    role: Literal["admin", "member"] = Field(..., description="New Role to Assign: admin / member")


class RemoveSpaceMemberRequest(BaseModel):
    """Remove Space Member Request"""

    space_id: int = Field(default=0, description="Space ID")
    user_id: int = Field(..., description="Target User ID to Remove")


class KnowledgeSpaceFolderStatsReq(BaseModel):
    """Batch folder statistics request."""

    folder_ids: list[int] = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Folder IDs to load statistics for",
    )
    file_status: list[int] | None = Field(
        default=None,
        description="Optional file status filter applied to folder statistics",
    )
    keyword: str | None = Field(
        default=None,
        description="Optional keyword filter applied to folder statistics",
    )
    tag_ids: list[int] | None = Field(
        default=None,
        description="Optional tag ID filter applied to folder statistics",
    )


class KnowledgeSpaceFolderStatsItemResp(BaseModel):
    """Folder statistics item."""

    folder_id: int = Field(..., description="Folder ID")
    file_num: int = Field(0, description="Total file count under the folder")
    success_file_num: int = Field(0, description="Successful file count under the folder")
    visible_success_file_num: int = Field(
        0,
        description="Visible successful file count under the folder",
    )
    processing_file_num: int = Field(
        0,
        description="Processing/waiting/rebuilding file count under the folder",
    )


class KnowledgeSpaceFolderStatsResp(BaseModel):
    """Batch folder statistics response."""

    stats: list[KnowledgeSpaceFolderStatsItemResp] = Field(
        default_factory=list,
        description="Folder statistics items in request order",
    )


class KnowledgeSpaceFileResponse(KnowledgeFileRead):
    """Knowledge Space File Response"""

    summary: str = Field(default="", description="Read-only summary mapped from file abstract")
    old_file_level_path: str | None = Field(None, description="Old File Level Path")
    approval_request_id: int | None = Field(None, description="Approval request id for pending uploads")
    approval_status: str | None = Field(None, description="Approval status for pending uploads")
    approval_reason: str | None = Field(None, description="Approval or safety reject reason")
    is_pending_approval: bool = Field(default=False, description="Whether the file is still pending approval")
    # Version management fields (populated by list_space_children when version feature is enabled)
    version_no: int | None = Field(default=None, description="Primary version number for multi-version docs")
    is_multi_version: bool = Field(default=False, description="Whether this file's logical document has >1 version")
    has_similar: bool = Field(
        default=False,
        description="Whether this file has unresolved similar candidates (similar_status == 1)",
    )
