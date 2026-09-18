"""Stable MCP input and successful-output contracts for F067."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator

from bisheng.common.services.config_service import settings


class McpContract(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class KnowledgeListInput(McpContract):
    resource_type: Literal[0, 1, 3] = Field(default=0, alias="type")
    name: str | None = None
    sort_by: Literal["update_time", "create_time", "name"] = "update_time"
    page_size: int = Field(default=10, ge=1, le=200)
    cursor: str | None = None


class KnowledgeCreateInput(McpContract):
    name: str = Field(min_length=1, max_length=200)
    resource_type: Literal[0, 1, 3] = Field(default=0, alias="type")
    description: str | None = None
    model: str | None = None
    auth_type: Literal["public", "private", "approval"] = "public"
    is_released: bool = False

    @model_validator(mode="after")
    def require_knowledge_model(self):
        if self.resource_type in {0, 1} and not self.model:
            raise ValueError("model is required when type is 0 or 1")
        return self


class KnowledgeUpdateInput(McpContract):
    knowledge_id: int = Field(gt=0)
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None


class KnowledgeIdInput(McpContract):
    knowledge_id: int = Field(gt=0)


class KnowledgeBaseFilter(McpContract):
    knowledge_base_id: int = Field(gt=0)
    tags: list[str] = Field(default_factory=list)
    tag_match_mode: Literal["ANY", "ALL"] = "ANY"


class RetrieveFilters(McpContract):
    knowledge_base_filters: list[KnowledgeBaseFilter] = Field(default_factory=list)


class KnowledgeRetrieveInput(McpContract):
    query: str = Field(min_length=1)
    knowledge_base_ids: list[int] = Field(min_length=1)
    filters: RetrieveFilters | None = None
    top_k: int = Field(default=10, ge=1, le=200)
    max_content: int = Field(default=15000, ge=1)


class KnowledgeFileUploadInput(McpContract):
    knowledge_id: int = Field(gt=0)
    file_name: str | None = Field(default=None, min_length=1, max_length=255)
    mime_type: str | None = None
    content_base64: str | None = Field(
        default=None,
        max_length=settings.open_mcp.max_base64_characters,
    )
    file_url: AnyHttpUrl | None = None
    parent_id: int | None = None
    split_mode: Literal["auto", "custom", "hierarchical"] = "auto"
    separator: list[str] | None = None
    separator_rule: list[str] | None = None
    chunk_size: int | None = Field(default=None, ge=1)
    chunk_overlap: int | None = Field(default=None, ge=0)
    retain_images: Literal[0, 1] = 1
    force_ocr: Literal[0, 1] = 0
    enable_formula: Literal[0, 1] = 1
    filter_page_header_footer: Literal[0, 1] = 0
    @model_validator(mode="after")
    def validate_file_source(self):
        has_inline = self.content_base64 is not None
        has_url = self.file_url is not None
        if has_inline == has_url:
            raise ValueError("exactly one of content_base64 or file_url is required")
        if has_inline and not self.file_name:
            raise ValueError("file_name is required with content_base64")
        return self


class KnowledgeFileListInput(McpContract):
    knowledge_id: int = Field(gt=0)
    parent_id: int | None = None
    keyword: str | None = None
    status: list[Literal[1, 2, 3, 4, 5, 6, 7]] | None = None
    page_size: int = Field(default=10, ge=1, le=200)
    cursor: str | None = None


class KnowledgeFileDeleteInput(McpContract):
    file_id: int = Field(gt=0)


class KnowledgeFilesDeleteInput(McpContract):
    file_ids: list[int] = Field(min_length=1)


class OperationResult(McpContract):
    success: Literal[True] = True


class MetadataField(McpContract):
    field_name: str = Field(max_length=255, pattern=r"^[a-z][a-z0-9_]*$")
    field_type: Literal["string", "number", "time"]
    updated_at: int


class KnowledgeResource(McpContract):
    id: int
    name: str
    resource_type: Literal[0, 1, 3] = Field(alias="type")
    user_id: int | None = None
    tenant_id: int | None = None
    description: str | None = None
    model: str | None = None
    collection_name: str | None = None
    index_name: str | None = None
    state: int | None = None
    auth_type: Literal["public", "private", "approval"]
    is_released: bool
    is_shared: bool
    auto_tag_enabled: bool
    auto_tag_library_id: int | None = None
    metadata_fields: list[MetadataField] | None = None
    create_time: datetime | None = None
    update_time: datetime | None = None
    user_name: str | None = None
    copiable: bool | None = None
    is_pinned: bool | None = None
    actions: list[str] | None = None
    is_followed: bool | None = None
    subscription_status: Literal["subscribed", "pending", "rejected", "not_subscribed"] | None = None
    user_role: Literal["creator", "admin", "member"] | None = None
    creation_request_id: str | None = None
    creation_payload_hash: str | None = None


class ResourceListData(McpContract):
    data: list[KnowledgeResource]
    page_size: int
    has_more: bool
    next_cursor: str | None = None


class RetrieveChunk(McpContract):
    content: str
    knowledge_id: int
    document_id: int
    document_name: str
    document_update_time: str = ""
    chunk_index: int


class RetrieveData(McpContract):
    chunks: list[RetrieveChunk]
    total: int


class TagItem(McpContract):
    id: int | None = None
    name: str | None = None
    business_type: str | None = None
    business_id: str | None = None
    user_id: int | None = None
    tenant_id: int | None = None
    create_time: datetime | None = None
    update_time: datetime | None = None


class FileRecord(McpContract):
    id: int
    knowledge_id: int
    file_name: str
    file_type: Literal[0, 1]
    user_id: int | None = None
    user_name: str | None = None
    tenant_id: int | None = None
    thumbnails: str | None = None
    file_source: str | None = None
    level: int | None = None
    file_level_path: str | None = None
    abstract: str | None = None
    file_size: int | None = None
    md5: str | None = None
    parse_type: str | None = None
    split_rule: str | None = None
    preview_file_object_name: str | None = None
    bbox_object_name: str | None = None
    status: Literal[1, 2, 3, 4, 5, 6, 7] | None = None
    object_name: str | None = None
    user_metadata: dict[str, Any] | None = None
    remark: str | None = None
    file_encoding: str | None = None
    simhash: str | None = None
    similar_status: int | None = None
    updater_id: int | None = None
    updater_name: str | None = None
    create_time: datetime | None = None
    update_time: datetime | None = None
    old_file_level_path: str | None = None
    approval_request_id: int | None = None
    approval_status: str | None = None
    approval_reason: str | None = None
    is_pending_approval: bool | None = None
    version_no: int | None = None
    is_multi_version: bool | None = None
    has_similar: bool | None = None


class FileItem(FileRecord):
    title: str | None = None
    tags: list[TagItem] | None = None
    has_failed_files: bool | None = None
    has_abnormal_files: bool | None = None
    success_file_num: int | None = None
    processing_file_num: int | None = None


class FileListData(McpContract):
    data: list[FileItem]
    page_size: int
    has_more: bool
    next_cursor: str | None = None
    writeable: bool


MCP_INPUT_MODELS = {
    "bisheng_knowledge_list": KnowledgeListInput,
    "bisheng_knowledge_create": KnowledgeCreateInput,
    "bisheng_knowledge_update": KnowledgeUpdateInput,
    "bisheng_knowledge_delete": KnowledgeIdInput,
    "bisheng_knowledge_clear": KnowledgeIdInput,
    "bisheng_knowledge_retrieve": KnowledgeRetrieveInput,
    "bisheng_knowledge_file_upload": KnowledgeFileUploadInput,
    "bisheng_knowledge_file_list": KnowledgeFileListInput,
    "bisheng_knowledge_file_delete": KnowledgeFileDeleteInput,
    "bisheng_knowledge_files_delete": KnowledgeFilesDeleteInput,
}


__all__ = [
    "MCP_INPUT_MODELS",
    "FileItem",
    "FileListData",
    "FileRecord",
    "KnowledgeResource",
    "OperationResult",
    "ResourceListData",
    "RetrieveData",
]
