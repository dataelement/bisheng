from typing import Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import StrictBool

from bisheng.mcp_server.domain.schemas.browse import Cursor, FolderId, ResourceId
from bisheng.mcp_server.domain.schemas.content import (
    FileDetailRequest,
    FileDetailResponse,
    FileSourceRequest,
    FileSourceResponse,
    FolderRetrieveRequest,
    MaxChars,
    McpRetrieveFilters,
)
from bisheng.mcp_server.domain.schemas.identity import ExternalAccount
from bisheng.mcp_server.domain.schemas.search import KnowledgeIds, MaxContent, McpSearchRequest, SearchQuery, TopK
from bisheng.mcp_server.domain.services.tool_runtime import McpToolRuntime
from bisheng.open_endpoints.domain.schemas.filelib import RetrieveResp


def register_content_tools(server: FastMCP, runtime: McpToolRuntime) -> None:
    annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

    @server.tool(
        description="按空间和文件 ID 获取有权文件的元数据、解析状态及当前版本正文,长正文使用游标续读。",
        annotations=annotations,
    )
    async def get_file_detail(
        external_id: ExternalAccount,
        knowledge_id: ResourceId,
        file_id: ResourceId,
        ctx: Context,
        include_content: StrictBool = True,
        content_format: Literal["text", "markdown"] = "text",
        max_chars: MaxChars = 20000,
        cursor: Cursor | None = None,
    ) -> FileDetailResponse:
        params = FileDetailRequest(
            external_id=external_id,
            knowledge_id=knowledge_id,
            file_id=file_id,
            include_content=include_content,
            content_format=content_format,
            max_chars=max_chars,
            cursor=cursor,
        )
        return FileDetailResponse.model_validate(await runtime.invoke(ctx, "get_file_detail", params))

    @server.tool(
        description="获取有权文件的预览来源;原件继续遵守下载、水印和分享策略,不绕过授权。", annotations=annotations
    )
    async def get_file_source(
        external_id: ExternalAccount,
        knowledge_id: ResourceId,
        file_id: ResourceId,
        ctx: Context,
        source_type: Literal["auto", "preview", "original"] = "auto",
    ) -> FileSourceResponse:
        params = FileSourceRequest(
            external_id=external_id, knowledge_id=knowledge_id, file_id=file_id, source_type=source_type
        )
        return FileSourceResponse.model_validate(await runtime.invoke(ctx, "get_file_source", params))

    @server.tool(
        description="根据问题检索有权知识空间的相关正文片段,返回内容及出处,不生成模型答案。", annotations=annotations
    )
    async def retrieve_chunks(
        external_id: ExternalAccount,
        query: SearchQuery,
        knowledge_base_ids: KnowledgeIds,
        ctx: Context,
        top_k: TopK = 5,
        max_content: MaxContent = 15000,
        filters: McpRetrieveFilters | None = None,
    ) -> RetrieveResp:
        params = McpSearchRequest(
            external_id=external_id,
            query=query,
            knowledge_base_ids=knowledge_base_ids,
            top_k=top_k,
            max_content=max_content,
            filters=filters,
        )
        return RetrieveResp.model_validate(await runtime.invoke(ctx, "retrieve_chunks", params))

    @server.tool(
        description="检索指定知识空间内单个文件夹的有权正文片段,默认包含子目录;recursive=false 仅检索当前层,不生成模型答案。",
        annotations=annotations,
    )
    async def retrieve_folder_chunks(
        external_id: ExternalAccount,
        query: SearchQuery,
        knowledge_id: ResourceId,
        folder_id: FolderId,
        ctx: Context,
        recursive: StrictBool = True,
        top_k: TopK = 5,
        max_content: MaxContent = 15000,
        filters: McpRetrieveFilters | None = None,
    ) -> RetrieveResp:
        params = FolderRetrieveRequest(
            external_id=external_id,
            query=query,
            knowledge_id=knowledge_id,
            folder_id=folder_id,
            recursive=recursive,
            top_k=top_k,
            max_content=max_content,
            filters=filters,
        )
        return RetrieveResp.model_validate(await runtime.invoke(ctx, "retrieve_folder_chunks", params))
