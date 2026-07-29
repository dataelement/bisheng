from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.schemas.knowledge_version_schema import (
    ShougangFilePublishDocumentEntry,
    SimilarCandidateEntry,
)


class ShougangKnowledgeSpaceCreateBase(BaseModel):
    name: str = Field(..., max_length=200)
    description: str | None = None
    icon: str | None = None
    auth_type: AuthTypeEnum = AuthTypeEnum.PUBLIC
    is_released: bool = False
    space_level: KnowledgeSpaceLevelEnum = KnowledgeSpaceLevelEnum.PERSONAL
    department_id: int | None = None
    user_group_id: int | None = None
    is_clinic: bool = Field(
        default=False,
        description=(
            "When true, a department-bound space is created as a team-level space "
            "(displayed under team/clinic spaces) and a department_knowledge_space "
            "binding is written. Only used when creating from the clinic context."
        ),
    )
    auto_tag_enabled: bool = False
    auto_tag_library_id: int | None = None
    auto_tag_library_ids: list[int] | None = None
    auto_tag_custom_tags: list[str] | None = None


class ShougangKnowledgeSpaceCreateValidateReq(ShougangKnowledgeSpaceCreateBase):
    pass


class ShougangKnowledgeSpaceCreateSubmitReq(ShougangKnowledgeSpaceCreateBase):
    reason: str | None = Field(default=None, max_length=2000)


class ShougangKnowledgeSpaceCreateValidateResp(BaseModel):
    approval_required: bool


class ShougangApprovalSubmitResp(BaseModel):
    decision: str
    created: bool = False
    instance_id: int | None = None
    task_ids: list[int] = Field(default_factory=list)
    space: dict[str, Any] | None = None


class ShougangFilePublishTargetSpace(BaseModel):
    id: int
    name: str
    space_level: KnowledgeSpaceLevelEnum
    owner_name: str | None = None
    can_browse_files: bool = False


class ShougangFilePublishTargetSpacesResp(BaseModel):
    data: list[ShougangFilePublishTargetSpace] = Field(default_factory=list)
    total: int = 0


class ShougangFilePublishTargetFolder(BaseModel):
    id: int
    name: str
    level: int


class ShougangFilePublishTargetFoldersResp(BaseModel):
    data: list[ShougangFilePublishTargetFolder] = Field(default_factory=list)
    total: int = 0


class ShougangFilePublishSimilarCandidatesResp(BaseModel):
    data: list[SimilarCandidateEntry] = Field(default_factory=list)
    total: int = 0


class ShougangFilePublishDocumentSearchResp(BaseModel):
    data: list[ShougangFilePublishDocumentEntry] = Field(default_factory=list)
    total: int = 0
    next_cursor: int | None = None
    has_more: bool = False


class ShougangFilePublishSubmitReq(BaseModel):
    source_space_id: int = Field(..., gt=0)
    source_file_id: int = Field(..., gt=0)
    target_space_id: int = Field(..., gt=0)
    target_folder_id: int | None = Field(default=None, gt=0)
    target_document_id: int | None = Field(default=None, gt=0)
    target_file_id: int | None = Field(default=None, gt=0)
    reason: str | None = Field(default=None, max_length=2000)


class ShougangFileShareTargetSpace(BaseModel):
    id: int
    name: str
    space_level: KnowledgeSpaceLevelEnum
    owner_name: str | None = None


class ShougangFileShareTargetSpacesResp(BaseModel):
    data: list[ShougangFileShareTargetSpace] = Field(default_factory=list)
    total: int = 0


class ShougangFileShareTargetFolder(BaseModel):
    id: int
    name: str
    level: int


class ShougangFileShareTargetFoldersResp(BaseModel):
    data: list[ShougangFileShareTargetFolder] = Field(default_factory=list)
    total: int = 0


class ShougangFileShareSubmitReq(BaseModel):
    source_space_id: int = Field(..., gt=0)
    source_file_id: int = Field(..., gt=0)
    target_space_id: int = Field(..., gt=0)
    target_folder_id: int | None = Field(default=None, gt=0)
    reason: str = Field(..., min_length=1, max_length=2000)
    allow_download: bool = False


class ShougangFileShareEntry(BaseModel):
    entry_id: int
    target_space_id: int
    target_space_name: str | None = None
    allow_download: bool
    entry_status: str
    create_time: str | None = None


class ShougangFileShareEntriesResp(BaseModel):
    data: list[ShougangFileShareEntry] = Field(default_factory=list)
    total: int = 0


class ShougangFileShareRevokeReq(BaseModel):
    source_file_id: int = Field(..., gt=0)
    share_entry_id: int = Field(..., gt=0)
