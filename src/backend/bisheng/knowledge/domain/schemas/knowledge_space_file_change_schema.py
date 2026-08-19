from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bisheng.common.schemas.api import PageData, PageInfiniteCursorData


class FileChangePolicyScope(StrEnum):
    ALL_SPACES = "all_spaces"
    PER_SPACE = "per_space"


class FileChangeAction(StrEnum):
    UPLOAD = "upload"
    RENAME = "rename"
    MOVE = "move"
    DELETE = "delete"


class FileChangeResourceType(StrEnum):
    STAGED_UPLOAD = "staged_upload"
    FILE = "file"
    FOLDER = "folder"


class FileChangeDecision(StrEnum):
    DIRECT = "direct"
    PENDING = "pending"
    INVALID = "invalid"


class FileChangeApprovalStatus(StrEnum):
    QUEUED = "queued"
    APPLYING = "applying"
    APPLIED = "applied"
    FAILED = "failed"
    COMPENSATING = "compensating"
    CLOSED = "closed"


class UploadStageState(StrEnum):
    UPLOADED = "uploaded"
    ATTACHING = "attaching"
    ATTACHED = "attached"
    CONSUMED = "consumed"
    CLEANUP_PENDING = "cleanup_pending"
    CLEANED = "cleaned"


class BatchApprovalResult(StrEnum):
    APPROVED = "approved"
    INVALID = "invalid"
    FAILED = "failed"


class _FileChangeInput(BaseModel):
    """Base for public input DTOs; caller-controlled tenant or storage fields are rejected."""

    model_config = ConfigDict(extra="forbid")


class _FileChangeOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class KnowledgeSpaceFileChangePolicyUpdateReq(_FileChangeInput):
    enabled: bool
    scope: FileChangePolicyScope


class KnowledgeSpaceFileChangePolicyResp(_FileChangeOutput):
    enabled: bool
    scope: FileChangePolicyScope


class KnowledgeSpaceFileChangeSettingUpdateReq(_FileChangeInput):
    approval_required: bool


class KnowledgeSpaceFileChangeSettingBulkItem(KnowledgeSpaceFileChangeSettingUpdateReq):
    space_id: int = Field(gt=0)


class KnowledgeSpaceFileChangeConfigurationUpdateReq(_FileChangeInput):
    policy: KnowledgeSpaceFileChangePolicyUpdateReq | None = None
    settings: list[KnowledgeSpaceFileChangeSettingBulkItem] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_changes(self):
        if self.policy is None and not self.settings:
            raise ValueError("at least one file change configuration update is required")
        space_ids = [item.space_id for item in self.settings]
        if len(space_ids) != len(set(space_ids)):
            raise ValueError("file change setting space ids must be unique")
        return self


class KnowledgeSpaceFileChangeSettingResp(_FileChangeOutput):
    space_id: int
    name: str
    auth_type: str
    space_kind: Literal["normal", "department"]
    approval_required: bool
    effective_required: bool


class KnowledgeSpaceFileChangeSettingsResp(PageData[KnowledgeSpaceFileChangeSettingResp]):
    pass


class KnowledgeSpaceFileChangeConfigurationResp(_FileChangeOutput):
    policy: KnowledgeSpaceFileChangePolicyResp
    settings: list[KnowledgeSpaceFileChangeSettingResp]


class KnowledgeSpaceUploadStageResp(_FileChangeOutput):
    upload_id: str
    space_id: int
    file_name: str
    file_size: int = Field(ge=0)
    content_hash: str | None = None
    state: UploadStageState
    expire_at: datetime
    create_time: datetime | None = None


class KnowledgeSpaceUploadIdsReq(_FileChangeInput):
    upload_ids: list[str] = Field(min_length=1)
    parent_id: int | None = None


class KnowledgeSpaceFolderUploadStageItem(_FileChangeInput):
    upload_id: str
    relative_path: str = Field(min_length=1, max_length=2048)


class KnowledgeSpaceFolderUploadStageReq(_FileChangeInput):
    parent_id: int | None = None
    items: list[KnowledgeSpaceFolderUploadStageItem] = Field(min_length=1)


class FileBatchRenameItem(_FileChangeInput):
    id: int = Field(gt=0)
    type: Literal[FileChangeResourceType.FILE, FileChangeResourceType.FOLDER]
    name: str = Field(min_length=1, max_length=500)


class FileBatchRenameReq(_FileChangeInput):
    items: list[FileBatchRenameItem] = Field(min_length=1, max_length=100)


class FileMutationResult(_FileChangeOutput):
    decision: Literal[FileChangeDecision.DIRECT, FileChangeDecision.PENDING]
    approval_instance_id: int | None = None
    change_request_id: int | None = None
    resource: dict[str, Any] | None = None


class FileMutationItemResult(_FileChangeOutput):
    input_id: str
    resource_type: Literal[FileChangeResourceType.FILE, FileChangeResourceType.FOLDER]
    decision: FileChangeDecision
    resource: dict[str, Any] | None = None
    approval_instance_id: int | None = None
    change_request_id: int | None = None
    error_code: int | None = None
    error_message: str | None = None


class ResourceMutationItemResult(_FileChangeOutput):
    id: int
    type: Literal[FileChangeResourceType.FILE, FileChangeResourceType.FOLDER]
    approval_instance_id: int | None = None
    change_request_id: int | None = None
    resource: dict[str, Any] | None = None
    error_code: int | None = None
    error_message: str | None = None


class FileMoveMutationResp(_FileChangeOutput):
    moved: list[ResourceMutationItemResult] = Field(default_factory=list)
    pending: list[ResourceMutationItemResult] = Field(default_factory=list)
    invalid: list[ResourceMutationItemResult] = Field(default_factory=list)


class FileBatchDeleteMutationResp(_FileChangeOutput):
    deleted: list[ResourceMutationItemResult] = Field(default_factory=list)
    pending: list[ResourceMutationItemResult] = Field(default_factory=list)
    invalid: list[ResourceMutationItemResult] = Field(default_factory=list)


class FileBatchRenameMutationResp(_FileChangeOutput):
    renamed: list[ResourceMutationItemResult] = Field(default_factory=list)
    pending: list[ResourceMutationItemResult] = Field(default_factory=list)
    invalid: list[ResourceMutationItemResult] = Field(default_factory=list)


class FileChangeApprovalView(_FileChangeOutput):
    status: FileChangeApprovalStatus
    action: Literal[FileChangeAction.RENAME, FileChangeAction.MOVE, FileChangeAction.DELETE]
    instance_id: int
    request_id: int
    can_approve: bool
    inherited: bool = False
    root_resource_id: int


class FileChangeActionDetail(_FileChangeOutput):
    old_name: str | None = None
    new_name: str | None = None
    source_path: str | None = None
    target_path: str | None = None
    source_parent_id: int | None = None
    target_space_id: int | None = None
    target_parent_id: int | None = None
    relative_path: str | None = None


class KnowledgeSpaceFileChangeDetailResp(_FileChangeOutput):
    request_id: int
    space_id: int
    action: FileChangeAction
    resource_type: FileChangeResourceType
    resource_id: int | None = None
    upload_id: str | None = None
    resource_name: str
    file_size: int | None = None
    content_hash: str | None = None
    applicant_user_id: int
    applicant_user_name: str | None = None
    approval_instance_id: int | None = None
    status: FileChangeApprovalStatus
    approval_status: str | None = None
    action_detail: FileChangeActionDetail = Field(default_factory=FileChangeActionDetail)
    can_approve: bool = False
    can_cleanup: bool = False
    failure_reason: str | None = None
    create_time: datetime | None = None
    update_time: datetime | None = None

    @field_validator("resource_type", mode="before")
    @classmethod
    def map_internal_resource_type(cls, value: Any) -> Any:
        """Map the persistence vocabulary to the public API vocabulary explicitly."""
        if value == "knowledge_file":
            return FileChangeResourceType.FILE
        return value


class KnowledgeSpacePendingUploadItemResp(_FileChangeOutput):
    request_id: int
    approval_instance_id: int | None = None
    upload_id: str
    file_name: str
    file_size: int = Field(ge=0)
    content_hash: str | None = None
    parent_id: int | None = None
    applicant_user_id: int
    applicant_user_name: str | None = None
    status: FileChangeApprovalStatus
    approval_status: str | None = None
    can_approve: bool = False
    failure_reason: str | None = None
    create_time: datetime | None = None
    update_time: datetime | None = None


class KnowledgeSpacePendingUploadCursorResp(PageInfiniteCursorData[KnowledgeSpacePendingUploadItemResp]):
    pass


class KnowledgeSpaceFileChangeDecisionReq(_FileChangeInput):
    action: Literal["approve", "reject"]
    comment: str | None = Field(default=None, max_length=1000)


class BatchApprovalReq(_FileChangeInput):
    approval_instance_ids: list[int] | None = Field(default=None, max_length=100)
    change_request_ids: list[int] | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_id_source(self) -> BatchApprovalReq:
        has_instance_ids = bool(self.approval_instance_ids)
        has_request_ids = bool(self.change_request_ids)
        if has_instance_ids == has_request_ids:
            raise ValueError("Provide exactly one of approval_instance_ids or change_request_ids")
        selected_ids = self.approval_instance_ids or self.change_request_ids or []
        if len(selected_ids) != len(set(selected_ids)):
            raise ValueError("Approval identifiers must be unique")
        if any(int(item_id) <= 0 for item_id in selected_ids):
            raise ValueError("Approval identifiers must be positive")
        return self


class BatchApprovalItemResult(_FileChangeOutput):
    change_request_id: int = Field(serialization_alias="changeRequestId")
    approval_instance_id: int = Field(serialization_alias="approvalInstanceId")
    result: BatchApprovalResult
    latest_status: str = Field(serialization_alias="latestStatus")
    error_code: int | None = Field(default=None, serialization_alias="errorCode")
    error_message: str | None = Field(default=None, serialization_alias="errorMessage")
    retryable: bool = False


class BatchApprovalResp(_FileChangeOutput):
    success_count: int = Field(default=0, ge=0, serialization_alias="successCount")
    failure_count: int = Field(default=0, ge=0, serialization_alias="failureCount")
    items: list[BatchApprovalItemResult] = Field(default_factory=list)
