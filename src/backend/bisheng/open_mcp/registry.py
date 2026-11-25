"""Explicit F067 MCP tool allowlist and discovery filtering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from mcp import types
from pydantic import BaseModel

from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_mcp import contracts

IdentityMode = Literal["S", "D"]


@dataclass(frozen=True, slots=True)
class McpToolDefinition:
    name: str
    title: str
    description: str
    source_method: str
    source_route: str
    scope: str
    modes: frozenset[IdentityMode]
    allow_pat: bool
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    annotations: types.ToolAnnotations

    def visible_to(self, principal: OpenApiPrincipal) -> bool:
        if not principal.has_scope(self.scope) or principal.mode not in self.modes:
            return False
        return principal.actor_kind != "natural_person" or self.allow_pat

    def to_mcp_tool(self) -> types.Tool:
        return types.Tool(
            name=self.name,
            title=self.title,
            description=self.description,
            inputSchema=self.input_model.model_json_schema(by_alias=True),
            outputSchema=self.output_model.model_json_schema(by_alias=True),
            annotations=self.annotations,
        )


def _annotations(*, read_only: bool, destructive: bool, idempotent: bool, open_world: bool = False):
    return types.ToolAnnotations(
        readOnlyHint=read_only,
        destructiveHint=destructive,
        idempotentHint=idempotent,
        openWorldHint=open_world,
    )


TOOL_DEFINITIONS = (
    McpToolDefinition(
        "bisheng_knowledge_list",
        "查询知识资源列表",
        "按类型分页查询当前身份可见的知识库、问答库或知识空间。",
        "GET",
        "/api/v2/filelib/",
        "knowledge:read",
        frozenset({"S", "D"}),
        True,
        contracts.KnowledgeListInput,
        contracts.ResourceListData,
        _annotations(read_only=True, destructive=False, idempotent=True),
    ),
    McpToolDefinition(
        "bisheng_knowledge_create",
        "创建知识资源",
        "创建知识库、问答库或知识空间。",
        "POST",
        "/api/v2/filelib/",
        "knowledge:write",
        frozenset({"S", "D"}),
        False,
        contracts.KnowledgeCreateInput,
        contracts.KnowledgeResource,
        _annotations(read_only=False, destructive=False, idempotent=False),
    ),
    McpToolDefinition(
        "bisheng_knowledge_update",
        "更新知识资源",
        "更新知识资源名称和描述。",
        "PUT",
        "/api/v2/filelib/",
        "knowledge:write",
        frozenset({"S", "D"}),
        False,
        contracts.KnowledgeUpdateInput,
        contracts.KnowledgeResource,
        _annotations(read_only=False, destructive=False, idempotent=True),
    ),
    McpToolDefinition(
        "bisheng_knowledge_delete",
        "删除知识资源",
        "删除知识资源及其既有级联内容。",
        "DELETE",
        "/api/v2/filelib/{knowledge_id}",
        "knowledge:write",
        frozenset({"S", "D"}),
        False,
        contracts.KnowledgeIdInput,
        contracts.OperationResult,
        _annotations(read_only=False, destructive=True, idempotent=True),
    ),
    McpToolDefinition(
        "bisheng_knowledge_clear",
        "清空知识资源",
        "清空知识资源内容但保留资源本身。",
        "DELETE",
        "/api/v2/filelib/clear/{knowledge_id}",
        "knowledge:write",
        frozenset({"S", "D"}),
        False,
        contracts.KnowledgeIdInput,
        contracts.OperationResult,
        _annotations(read_only=False, destructive=True, idempotent=True),
    ),
    McpToolDefinition(
        "bisheng_knowledge_retrieve",
        "检索知识资源分段",
        "在一个或多个知识资源中检索相关分段, 不生成回答。",
        "POST",
        "/api/v2/filelib/retrieve",
        "knowledge:read",
        frozenset({"S", "D"}),
        True,
        contracts.KnowledgeRetrieveInput,
        contracts.RetrieveData,
        _annotations(read_only=True, destructive=False, idempotent=True),
    ),
    McpToolDefinition(
        "bisheng_knowledge_file_upload",
        "上传知识文件",
        "通过严格 base64 或受控 URL 上传文件到知识资源。",
        "POST",
        "/api/v2/filelib/file/{knowledge_id}",
        "knowledge:write",
        frozenset({"S", "D"}),
        False,
        contracts.KnowledgeFileUploadInput,
        contracts.FileRecord,
        _annotations(read_only=False, destructive=False, idempotent=False, open_world=True),
    ),
    McpToolDefinition(
        "bisheng_knowledge_file_list",
        "查询知识文件列表",
        "分页查询知识资源中的文件和文件夹。",
        "GET",
        "/api/v2/filelib/file/list",
        "knowledge:read",
        frozenset({"S", "D"}),
        True,
        contracts.KnowledgeFileListInput,
        contracts.FileListData,
        _annotations(read_only=True, destructive=False, idempotent=True),
    ),
    McpToolDefinition(
        "bisheng_knowledge_file_delete",
        "删除知识文件",
        "删除一个知识文件。",
        "DELETE",
        "/api/v2/filelib/file/{file_id}",
        "knowledge:write",
        frozenset({"S", "D"}),
        False,
        contracts.KnowledgeFileDeleteInput,
        contracts.OperationResult,
        _annotations(read_only=False, destructive=True, idempotent=True),
    ),
    McpToolDefinition(
        "bisheng_knowledge_files_delete",
        "批量删除知识文件",
        "批量删除知识文件。",
        "POST",
        "/api/v2/filelib/delete_file",
        "knowledge:write",
        frozenset({"S", "D"}),
        False,
        contracts.KnowledgeFilesDeleteInput,
        contracts.OperationResult,
        _annotations(read_only=False, destructive=True, idempotent=True),
    ),
    McpToolDefinition(
        "bisheng_knowledge_qa_query",
        "查询问答条目",
        "按创建时间范围查询当前身份可见的问答库条目。",
        "POST",
        "/api/v2/filelib/query_qa",
        "knowledge:read",
        frozenset({"S", "D"}),
        True,
        contracts.QaQueryInput,
        contracts.QaListData,
        _annotations(read_only=True, destructive=False, idempotent=True),
    ),
    McpToolDefinition(
        "bisheng_knowledge_qa_detail",
        "查询问答条目详情",
        "按 ID 查询一条问答条目。",
        "GET",
        "/api/v2/filelib/detail_qa",
        "knowledge:read",
        frozenset({"S", "D"}),
        True,
        contracts.QaDetailInput,
        contracts.QaItem,
        _annotations(read_only=True, destructive=False, idempotent=True),
    ),
    McpToolDefinition(
        "bisheng_knowledge_qa_add",
        "新增问答条目",
        "向问答知识库批量新增问答条目。",
        "POST",
        "/api/v2/filelib/add_qa",
        "knowledge:write",
        frozenset({"S", "D"}),
        False,
        contracts.QaAddInput,
        contracts.QaListData,
        _annotations(read_only=False, destructive=False, idempotent=False),
    ),
    McpToolDefinition(
        "bisheng_knowledge_qa_add_relative",
        "追加相似问",
        "给已有问答条目追加相似问。",
        "POST",
        "/api/v2/filelib/add_relative_qa",
        "knowledge:write",
        frozenset({"S", "D"}),
        False,
        contracts.QaAddRelativeInput,
        contracts.QaItem,
        _annotations(read_only=False, destructive=False, idempotent=True),
    ),
    McpToolDefinition(
        "bisheng_knowledge_qa_update",
        "更新问答条目",
        "更新问答条目的问题或答案。",
        "POST",
        "/api/v2/filelib/update_qa",
        "knowledge:write",
        frozenset({"S", "D"}),
        False,
        contracts.QaUpdateInput,
        contracts.OperationResult,
        _annotations(read_only=False, destructive=False, idempotent=True),
    ),
    McpToolDefinition(
        "bisheng_knowledge_qa_delete",
        "删除问答条目",
        "删除整个问答条目, 或只删除其中一条相似问。",
        "DELETE",
        "/api/v2/filelib/qa/{qa_id}",
        "knowledge:write",
        frozenset({"S", "D"}),
        False,
        contracts.QaDeleteInput,
        contracts.OperationResult,
        _annotations(read_only=False, destructive=True, idempotent=True),
    ),
    McpToolDefinition(
        "bisheng_knowledge_metadata_fields_add",
        "新增元数据字段",
        "给知识库新增文件自定义元数据字段。",
        "POST",
        "/api/v2/knowledge/add_metadata_fields",
        "knowledge:write",
        frozenset({"S", "D"}),
        False,
        contracts.MetadataFieldsAddInput,
        contracts.OperationResult,
        _annotations(read_only=False, destructive=False, idempotent=True),
    ),
    McpToolDefinition(
        "bisheng_knowledge_metadata_fields_rename",
        "重命名元数据字段",
        "修改知识库已有元数据字段的名称。",
        "PUT",
        "/api/v2/knowledge/modify_metadata_fields",
        "knowledge:write",
        frozenset({"S", "D"}),
        False,
        contracts.MetadataFieldsRenameInput,
        contracts.OperationResult,
        _annotations(read_only=False, destructive=False, idempotent=True),
    ),
    McpToolDefinition(
        "bisheng_knowledge_metadata_fields_delete",
        "删除元数据字段",
        "删除知识库的元数据字段。",
        "DELETE",
        "/api/v2/knowledge/delete_metadata_fields",
        "knowledge:write",
        frozenset({"S", "D"}),
        False,
        contracts.MetadataFieldsDeleteInput,
        contracts.OperationResult,
        _annotations(read_only=False, destructive=True, idempotent=True),
    ),
    McpToolDefinition(
        "bisheng_knowledge_metadata_fields_get",
        "查询元数据字段",
        "查询知识库定义的元数据字段。",
        "GET",
        "/api/v2/knowledge/get_metadata_fields/{knowledge_id}",
        "knowledge:write",
        frozenset({"S", "D"}),
        False,
        contracts.MetadataFieldsGetInput,
        contracts.MetadataFieldsData,
        _annotations(read_only=True, destructive=False, idempotent=True),
    ),
    McpToolDefinition(
        "bisheng_knowledge_file_metadata_add",
        "新增文件元数据",
        "给知识库里的文件新增自定义元数据值。",
        "POST",
        "/api/v2/knowledge/file/add_user_metadata",
        "knowledge:write",
        frozenset({"S", "D"}),
        False,
        contracts.FileMetadataWriteInput,
        contracts.OperationResult,
        _annotations(read_only=False, destructive=False, idempotent=True),
    ),
    McpToolDefinition(
        "bisheng_knowledge_file_metadata_modify",
        "修改文件元数据",
        "修改知识库里文件的自定义元数据值。",
        "PUT",
        "/api/v2/knowledge/file/modify_user_metadata",
        "knowledge:write",
        frozenset({"S", "D"}),
        False,
        contracts.FileMetadataWriteInput,
        contracts.OperationResult,
        _annotations(read_only=False, destructive=False, idempotent=True),
    ),
    McpToolDefinition(
        "bisheng_knowledge_file_metadata_delete",
        "删除文件元数据",
        "删除知识库里文件的自定义元数据字段值。",
        "DELETE",
        "/api/v2/knowledge/file/delete_user_metadata",
        "knowledge:write",
        frozenset({"S", "D"}),
        False,
        contracts.FileMetadataDeleteInput,
        contracts.OperationResult,
        _annotations(read_only=False, destructive=True, idempotent=True),
    ),
    McpToolDefinition(
        "bisheng_knowledge_file_metadata_list",
        "查询文件元数据",
        "查询知识库里文件的自定义元数据值。",
        "POST",
        "/api/v2/knowledge/file/list_user_metadata",
        "knowledge:write",
        frozenset({"S", "D"}),
        False,
        contracts.FileMetadataListInput,
        contracts.FileMetadataListData,
        _annotations(read_only=True, destructive=False, idempotent=True),
    ),
    McpToolDefinition(
        "bisheng_knowledge_answer",
        "服务端检索并作答",
        "在知识空间中检索并由服务端模型生成答案和参考文件, 仅支持知识空间; 需要核对原文或跨文档综合时改用检索工具。",
        "POST",
        "/api/v2/filelib/answer",
        "knowledge:read",
        frozenset({"S", "D"}),
        True,
        contracts.KnowledgeAnswerInput,
        contracts.KnowledgeAnswerData,
        _annotations(read_only=True, destructive=False, idempotent=False, open_world=True),
    ),
    McpToolDefinition(
        "bisheng_knowledge_chunks_upload",
        "同步导入文件分段",
        "上传文件到文档知识库并等待解析完成, 返回解析后的文件记录。",
        "POST",
        "/api/v2/filelib/chunks",
        "knowledge:write",
        frozenset({"S", "D"}),
        False,
        contracts.KnowledgeChunksUploadInput,
        contracts.FileRecord,
        _annotations(read_only=False, destructive=False, idempotent=False, open_world=True),
    ),
    McpToolDefinition(
        "bisheng_knowledge_chunks_text",
        "导入文本分段",
        "把一组文本段作为一个文件导入文档知识库, 第一段的 source 决定文件名。",
        "POST",
        "/api/v2/filelib/chunks_string",
        "knowledge:write",
        frozenset({"S", "D"}),
        False,
        contracts.KnowledgeChunksTextInput,
        contracts.FileRecord,
        _annotations(read_only=False, destructive=False, idempotent=False, open_world=False),
    ),
)

TOOL_REGISTRY = {definition.name: definition for definition in TOOL_DEFINITIONS}
SOURCE_ALLOWLIST = frozenset((item.source_method, item.source_route) for item in TOOL_DEFINITIONS)


def list_tools_for(principal: OpenApiPrincipal) -> list[types.Tool]:
    return [item.to_mcp_tool() for item in TOOL_DEFINITIONS if item.visible_to(principal)]


__all__ = ["SOURCE_ALLOWLIST", "TOOL_DEFINITIONS", "TOOL_REGISTRY", "list_tools_for"]
