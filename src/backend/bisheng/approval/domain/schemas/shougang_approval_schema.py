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


class ShougangFilePublishTargetSpacesResp(BaseModel):
    data: list[ShougangFilePublishTargetSpace] = Field(default_factory=list)
    total: int = 0


class ShougangFilePublishSimilarCandidatesResp(BaseModel):
    data: list[SimilarCandidateEntry] = Field(default_factory=list)
    total: int = 0


class ShougangFilePublishDocumentSearchResp(BaseModel):
    data: list[ShougangFilePublishDocumentEntry] = Field(default_factory=list)
    total: int = 0


class ShougangFilePublishSubmitReq(BaseModel):
    source_space_id: int = Field(..., gt=0)
    source_file_id: int = Field(..., gt=0)
    target_space_id: int = Field(..., gt=0)
    target_folder_id: int | None = Field(default=None, gt=0)
    target_document_id: int | None = Field(default=None, gt=0)
    target_file_id: int | None = Field(default=None, gt=0)
    reason: str | None = Field(default=None, max_length=2000)
