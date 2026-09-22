"""Stable MCP input and successful-output contracts for F067."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator

from bisheng.common.services.config_service import settings


class McpContract(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class KnowledgeListInput(McpContract):
    resource_type: Literal[0, 1, 3] = Field(
        default=0,
        alias="type",
        description="资源类型: 0=文档知识库, 1=问答知识库, 3=知识空间。",
    )
    name: str | None = None
    sort_by: Literal["update_time", "create_time", "name"] = "update_time"
    page_size: int = Field(default=10, ge=1, le=200)
    cursor: str | None = None


class KnowledgeCreateInput(McpContract):
    name: str = Field(min_length=1, max_length=200)
    resource_type: Literal[0, 1, 3] = Field(
        default=0,
        alias="type",
        description="资源类型: 0=文档知识库, 1=问答知识库, 3=知识空间。",
    )
    description: str | None = None
    model: str | None = Field(
        default=None,
        description="知识库使用的模型标识; type=0/1 时必填, type=3 时不使用。",
    )
    auth_type: Literal["public", "private", "approval"] = Field(
        default="public",
        description="知识空间访问方式; 仅 type=3 有业务意义, type=0/1 固定按 public 处理。",
    )
    is_released: bool = Field(
        default=False,
        description="是否把知识空间发布到知识广场; 仅 type=3 有业务意义, type=0/1 固定按 false 处理。",
    )

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
    success: Literal[True] = Field(
        default=True,
        description="固定为 true, 表示操作已成功完成; 失败通过 MCP tool error 返回。",
    )


class MetadataField(McpContract):
    field_name: str = Field(
        max_length=255,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="文件自定义元数据字段名。",
    )
    field_type: Literal["string", "number", "time"] = Field(
        description="元数据值类型: string=字符串, number=数字, time=时间。",
    )
    updated_at: int = Field(description="字段配置最后更新时间的 Unix 秒级时间戳。")


class KnowledgeResource(McpContract):
    id: int = Field(description="知识资源唯一 ID; 可作为 knowledge_id 传给其他工具。")
    name: str = Field(description="知识资源名称。")
    resource_type: Literal[0, 1, 3] = Field(
        alias="type",
        description="资源类型: 0=文档知识库, 1=问答知识库, 3=知识空间。",
    )
    user_id: int | None = Field(default=None, description="资源创建者的 BISHENG 用户 ID。")
    tenant_id: int | None = Field(default=None, description="资源所属租户 ID。")
    description: str | None = Field(default=None, description="资源描述。")
    model: str | None = Field(
        default=None,
        description="type=0/1 使用的模型标识; type=3 不使用, 通常为 null。",
    )
    collection_name: str | None = Field(
        default=None,
        description="知识库对应的向量集合标识; 主要用于 type=0/1, type=3 不使用。",
    )
    index_name: str | None = Field(
        default=None,
        description="知识库对应的检索索引标识; 主要用于 type=0/1, type=3 不使用。",
    )
    state: int | None = Field(
        default=None,
        description="知识库处理状态: 0=未发布, 1=已发布/可用, 2=复制中, 3=重建中, 4=重建失败; type=3 不使用该状态。",
    )
    auth_type: Literal["public", "private", "approval"] = Field(
        description="知识空间访问方式; 仅 type=3 有业务意义, type=0/1 不使用且调用方应忽略。",
    )
    is_released: bool = Field(
        description="知识空间是否已发布到知识广场; 仅 type=3 有业务意义, type=0/1 不使用且调用方应忽略。",
    )
    is_shared: bool = Field(description="资源根节点是否启用向下共享。")
    auto_tag_enabled: bool = Field(description="上传文件时是否启用自动标签。")
    auto_tag_library_id: int | None = Field(
        default=None,
        description="绑定的自动标签库 ID; 未启用或未绑定时为 null。",
    )
    metadata_fields: list[MetadataField] | None = Field(
        default=None,
        description="资源定义的文件自定义元数据字段; 未配置时为 null。",
    )
    create_time: datetime | None = Field(default=None, description="资源创建时间。")
    update_time: datetime | None = Field(default=None, description="资源最后更新时间。")
    user_name: str | None = Field(default=None, description="资源创建者显示名称。")
    copiable: bool | None = Field(
        default=None,
        description="当前身份是否可复制该知识库; 知识空间通常不返回该装饰字段。",
    )
    is_pinned: bool | None = Field(
        default=None,
        description="当前身份是否已置顶该知识空间; type=0/1 不使用且调用方应忽略。",
    )
    actions: list[str] | None = Field(
        default=None,
        description="当前身份对该资源拥有的有效业务动作代码; 不是 permission_ids。",
    )
    is_followed: bool | None = Field(
        default=None,
        description="当前身份是否已关注该知识空间; type=0/1 不使用且调用方应忽略。",
    )
    subscription_status: Literal["subscribed", "pending", "rejected", "not_subscribed"] | None = Field(
        default=None,
        description=(
            "当前身份对知识空间的订阅状态: subscribed=已加入, pending=待审批, "
            "rejected=已拒绝, not_subscribed=未加入; 仅 type=3 使用。"
        ),
    )
    user_role: Literal["creator", "admin", "member"] | None = Field(
        default=None,
        description="当前身份在知识空间中的角色; 仅 type=3 且已建立成员关系时返回。",
    )
    creation_request_id: str | None = Field(
        default=None,
        description="业务侧创建幂等请求 ID; MCP 创建工具当前不接收该字段, 通常为 null。",
    )
    creation_payload_hash: str | None = Field(
        default=None,
        description="与 creation_request_id 配套的创建载荷摘要; 通常为 null。",
    )


class ResourceListData(McpContract):
    data: list[KnowledgeResource] = Field(description="当前页知识资源列表。")
    page_size: int = Field(description="本次请求的分页大小。")
    has_more: bool = Field(description="是否还有下一页。")
    next_cursor: str | None = Field(
        default=None,
        description="下一页游标; has_more=false 时为 null。",
    )


class RetrieveChunk(McpContract):
    content: str = Field(description="命中的原始文本分段内容。")
    knowledge_id: int = Field(description="该分段所属知识资源 ID。")
    document_id: int = Field(description="该分段所属文件/文档 ID。")
    document_name: str = Field(description="该分段所属文件/文档名称。")
    document_update_time: str = Field(
        default="",
        description="源文档最后更新时间, 格式为 YYYY-MM-DD HH:mm:ss; 不可用时为空字符串。",
    )
    chunk_index: int = Field(description="分段在源文档中的序号。")


class RetrieveData(McpContract):
    chunks: list[RetrieveChunk] = Field(description="按相关性返回的检索分段。")
    total: int = Field(description="本次实际返回的分段数量。")


class TagItem(McpContract):
    id: int | None = Field(default=None, description="标签 ID。")
    name: str | None = Field(default=None, description="标签名称。")
    business_type: str | None = Field(
        default=None,
        description="标签所属业务类型, 例如 knowledge_space、knowledge 或 application。",
    )
    business_id: str | None = Field(default=None, description="标签所属业务对象 ID。")
    user_id: int | None = Field(default=None, description="标签创建者的 BISHENG 用户 ID。")
    tenant_id: int | None = Field(default=None, description="标签所属租户 ID。")
    create_time: datetime | None = Field(default=None, description="标签创建时间。")
    update_time: datetime | None = Field(default=None, description="标签最后更新时间。")


class FileRecord(McpContract):
    id: int = Field(description="文件或文件夹唯一 ID; 删除文件时作为 file_id 使用。")
    knowledge_id: int = Field(description="所属知识资源 ID。")
    file_name: str = Field(description="文件或文件夹名称。")
    file_type: Literal[0, 1] = Field(description="条目类型: 0=文件夹, 1=文件。")
    user_id: int | None = Field(default=None, description="上传者/创建者的 BISHENG 用户 ID。")
    user_name: str | None = Field(default=None, description="上传者/创建者显示名称。")
    tenant_id: int | None = Field(default=None, description="文件所属租户 ID。")
    thumbnails: str | None = Field(
        default=None,
        description="缩略图对象名或业务层生成的可访问地址; 没有缩略图时为 null。",
    )
    file_source: str | None = Field(
        default=None,
        description=(
            "文件来源; 当前常见值为 upload、channel、space_upload、audio_transcript、video_transcript、web_link。"
        ),
    )
    level: int | None = Field(default=None, description="条目在资源目录树中的层级。")
    file_level_path: str | None = Field(
        default=None,
        description="由祖先文件夹 ID 组成的内部层级路径; 不是显示名称路径。",
    )
    abstract: str | None = Field(default=None, description="解析生成或人工维护的文件摘要。")
    file_size: int | None = Field(default=None, description="文件大小, 单位为字节; 文件夹通常为 null。")
    md5: str | None = Field(default=None, description="文件内容 MD5; 文件夹通常为 null。")
    parse_type: str | None = Field(
        default=None,
        description="文件解析方式, 例如 local、uns、etl4lm、un_etl4lm、mineru、paddle_ocr。",
    )
    split_rule: str | None = Field(default=None, description="文件解析时使用的分段规则序列化值。")
    preview_file_object_name: str | None = Field(
        default=None,
        description="预览文件在对象存储中的对象名。",
    )
    bbox_object_name: str | None = Field(
        default=None,
        description="版面坐标数据在对象存储中的对象名。",
    )
    status: Literal[1, 2, 3, 4, 5, 6, 7] | None = Field(
        default=None,
        description="处理状态: 1=处理中, 2=成功, 3=失败, 4=重建中, 5=排队中, 6=超时, 7=内容安全违规。",
    )
    object_name: str | None = Field(default=None, description="原始文件在对象存储中的对象名。")
    user_metadata: dict[str, Any] | None = Field(
        default=None,
        description="文件自定义元数据; 键与资源的 metadata_fields 定义对应。",
    )
    remark: str | None = Field(default=None, description="文件备注或处理说明。")
    file_encoding: str | None = Field(default=None, description="外部部署生成的文件编码; 未启用时为 null。")
    simhash: str | None = Field(
        default=None,
        description="解析后计算的 64 位 SimHash 十六进制值; 尚未计算时为 null。",
    )
    similar_status: int | None = Field(
        default=None,
        description="相似文件状态: 0=无相似, 1=发现相似且待处理, 2=已关联或已忽略。",
    )
    updater_id: int | None = Field(default=None, description="最后更新者的 BISHENG 用户 ID。")
    updater_name: str | None = Field(default=None, description="最后更新者显示名称。")
    create_time: datetime | None = Field(default=None, description="条目创建时间。")
    update_time: datetime | None = Field(default=None, description="条目最后更新时间。")
    old_file_level_path: str | None = Field(
        default=None,
        description="知识空间文件变更前的显示路径; 仅相关变更/失败场景返回。",
    )
    approval_request_id: int | None = Field(
        default=None,
        description="部门知识空间上传审批请求 ID; 无需审批时为 null。",
    )
    approval_status: str | None = Field(
        default=None,
        description=(
            "部门知识空间上传审批状态, 例如 pending_review、sensitive_rejected、approved、"
            "rejected、finalized、finalize_failed; 无需审批时为 null。"
        ),
    )
    approval_reason: str | None = Field(default=None, description="审批或内容安全拒绝原因。")
    is_pending_approval: bool | None = Field(
        default=None,
        description="文件是否仍在等待上传审批; 仅启用上传审批的知识空间使用。",
    )
    version_no: int | None = Field(
        default=None,
        description="逻辑文档当前主版本号; 未启用多版本或文件夹条目时为 null。",
    )
    is_multi_version: bool | None = Field(
        default=None,
        description="该逻辑文档是否拥有多个版本; 文件夹条目不适用。",
    )
    has_similar: bool | None = Field(
        default=None,
        description="是否存在尚未处理的相似文件候选; 文件夹条目不适用。",
    )


class FileItem(FileRecord):
    title: str | None = Field(
        default=None,
        description="解析后从检索索引读取的文档标题/摘要; 文件夹条目不适用。",
    )
    tags: list[TagItem] | None = Field(
        default=None,
        description="文件关联的结构化标签; 文件夹或未加载标签时为 null。",
    )
    has_failed_files: bool | None = Field(
        default=None,
        description="文件夹后代中是否存在失败、超时或内容安全违规文件; 仅文件夹条目使用。",
    )
    has_abnormal_files: bool | None = Field(
        default=None,
        description="知识空间创建者可见的文件夹异常提示; 非创建者可能返回 false, 文件条目不适用。",
    )
    success_file_num: int | None = Field(
        default=None,
        description="文件夹后代中处理成功的文件数; 仅源业务返回该聚合值时提供。",
    )
    processing_file_num: int | None = Field(
        default=None,
        description="文件夹后代中正在处理的文件数; 仅源业务返回该聚合值时提供。",
    )


class FileListData(McpContract):
    data: list[FileItem] = Field(description="当前目录或搜索条件下的文件/文件夹列表。")
    page_size: int = Field(description="本次请求的分页大小。")
    has_more: bool = Field(description="是否还有下一页。")
    next_cursor: str | None = Field(
        default=None,
        description="下一页游标; has_more=false 时为 null。",
    )
    writeable: bool = Field(description="当前身份是否可向本次查询的目录上传文件。")


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
