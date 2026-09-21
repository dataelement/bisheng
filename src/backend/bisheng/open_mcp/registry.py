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
)

TOOL_REGISTRY = {definition.name: definition for definition in TOOL_DEFINITIONS}
SOURCE_ALLOWLIST = frozenset((item.source_method, item.source_route) for item in TOOL_DEFINITIONS)


def list_tools_for(principal: OpenApiPrincipal) -> list[types.Tool]:
    return [item.to_mcp_tool() for item in TOOL_DEFINITIONS if item.visible_to(principal)]


__all__ = ["SOURCE_ALLOWLIST", "TOOL_DEFINITIONS", "TOOL_REGISTRY", "list_tools_for"]
