from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from bisheng.common.models.space_channel_member import UserRoleEnum
from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum, KnowledgeBase
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileRead


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
    auto_tag_enabled: bool = Field(default=False, description="Whether uploaded files participate in auto tagging")
    auto_tag_library_id: int | None = Field(default=None, description="Bound knowledge-space tag library ID")
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
    is_pinned: bool = Field(default=False, description="Knowledge Space pinned by current user or not")
    user_name: str = Field(default="", description="Knowledge Space creator name")
    permission_ids: list[str] | None = Field(
        default=None, description="Effective permission ids the current identity holds on this space"
    )
    avatar: str | None = Field(default=None, description="Knowledge Space creator avatar")
    follower_num: int = Field(1, description="Follower Number")
    file_num: int = Field(1, description="Total File Number")
    is_followed: bool = Field(default=False, description="Knowledge Space followed by current user or not")
    is_pending: bool = Field(default=False, description="Knowledge Space pending or not")
    subscription_status: SpaceSubscriptionStatusEnum = Field(
        default=SpaceSubscriptionStatusEnum.NOT_SUBSCRIBED,
        description="Current user subscription status",
    )
    user_role: UserRoleEnum | None = Field(default=None, description="Knowledge Space user role")
    space_kind: Literal["normal", "department"] = Field(default="normal", description="Knowledge space kind")
    department_id: int | None = Field(default=None, description="Bound department id for department spaces")
    department_name: str | None = Field(default=None, description="Bound department name for department spaces")
    approval_enabled: bool | None = Field(default=None, description="Whether department-space uploads require approval")
    sensitive_check_enabled: bool | None = Field(
        default=None,
        description="Whether department-space uploads require content safety check",
    )
    is_hidden: bool | None = Field(
        default=None,
        description="Whether the department space is hidden from the management list (data preserved)",
    )
    auto_tag_mode: Literal["library", "custom"] = Field(
        default="library",
        description="Discriminator: 'library' for an admin-managed tag library, 'custom' for a private library backed by user-entered tags.",
    )
    auto_tag_custom_tags: list[str] | None = Field(
        default=None,
        description="Populated only when auto_tag_mode == 'custom'; mirrors the private library's tag list.",
    )


class KnowledgeSpaceUpdateReq(BaseModel):
    name: str | None = Field(None, max_length=200, description="Knowledge Space Name")
    description: str | None = Field(None, description="Knowledge Space Description")
    icon: str | None = Field(None, description="Icon Object Name")
    auth_type: AuthTypeEnum | None = Field(None, description="Authentication Type")
    is_released: bool = Field(default=False, description="Knowledge Space Status")
    auto_tag_enabled: bool | None = Field(
        default=None, description="Whether uploaded files participate in auto tagging"
    )
    auto_tag_library_id: int | None = Field(default=None, description="Bound knowledge-space tag library ID")
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


class DepartmentKnowledgeSpaceVisibilityReq(BaseModel):
    department_ids: list[int] = Field(
        default_factory=list,
        description="Department ids whose knowledge space visibility is toggled",
    )
    is_hidden: bool = Field(
        ...,
        description="True hides the department spaces from the management list; False restores them",
    )


class FolderCreateReq(BaseModel):
    name: str = Field(..., description="Folder Name")
    parent_id: int | None = Field(None, description="Parent Folder ID")


class FolderRenameReq(BaseModel):
    name: str = Field(..., description="New Folder Name")


class FileCreateReq(BaseModel):
    file_path: list[str] = Field(..., description="File Path")
    parent_id: int | None = Field(None, description="Parent Folder ID")


class FileRenameReq(BaseModel):
    name: str = Field(..., description="New File Name")


class FolderUploadItem(BaseModel):
    """F034 §5.5 folder upload: one already-uploaded file body + its relative path."""

    file_path: str = Field(..., description="MinIO path returned by the upload endpoint")
    relative_path: str = Field(..., description="Path relative to the drop point, e.g. 'Top/Sub/a.pdf'")
    # Client-reported size, used only for the batch-level capacity pre-check
    # (all-or-nothing UX). The authoritative per-file quota check still runs
    # during registration (add_file).
    size: int = Field(0, ge=0, description="File size in bytes")


class FolderUploadReq(BaseModel):
    parent_id: int | None = Field(None, description="Target folder id; None = space root")
    items: list[FolderUploadItem] = Field(..., min_length=1, description="Files with relative paths")


class MoveItem(BaseModel):
    id: int = Field(..., description="File or folder id")
    type: str = Field(..., description="'file' or 'folder'")


class FileMoveReq(BaseModel):
    """F034 move request. target_space_id == path space_id ⇒ same-space move."""

    items: list[MoveItem] = Field(..., description="Files/folders to move")
    target_space_id: int = Field(..., description="Destination space id")
    target_folder_id: int | None = Field(None, description="Destination folder id; None = space root")
    skip_invalid: bool = Field(False, description="Move the valid items and report the rest instead of rejecting all")


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


class KnowledgeSpaceFileResponse(KnowledgeFileRead):
    """Knowledge Space File Response"""

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
