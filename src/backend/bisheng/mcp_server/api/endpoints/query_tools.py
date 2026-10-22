from typing import Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import StrictBool

from bisheng.mcp_server.domain.schemas.browse import (
    Cursor,
    FileListRequest,
    FileSearchRequest,
    FolderId,
    FolderListRequest,
    FolderScope,
    Keyword,
    KnowledgeListRequest,
    McpPage,
    PageSize,
    ResourceId,
    SpaceIds,
    Statuses,
)
from bisheng.mcp_server.domain.schemas.identity import ExternalAccount
from bisheng.mcp_server.domain.services.tool_runtime import McpToolRuntime


def register_query_tools(server: FastMCP, runtime: McpToolRuntime) -> None:
    annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

    @server.tool(description="列出有权访问的知识空间,支持名称、可上传位置筛选和游标分页。", annotations=annotations)
    async def list_knowledge(
        external_id: ExternalAccount,
        ctx: Context,
        name: Keyword | None = None,
        writable_only: StrictBool = False,
        cursor: Cursor | None = None,
        page_size: PageSize = 20,
    ) -> McpPage:
        params = KnowledgeListRequest(
            external_id=external_id, name=name, writable_only=writable_only, cursor=cursor, page_size=page_size
        )
        return McpPage.model_validate(await runtime.invoke(ctx, "list_knowledge", params))

    @server.tool(
        description="列出知识空间指定目录下的直接子目录,返回安全路径、ID 和上传权限。", annotations=annotations
    )
    async def list_folders(
        external_id: ExternalAccount,
        knowledge_id: ResourceId,
        ctx: Context,
        folder_id: FolderId | None = None,
        cursor: Cursor | None = None,
        page_size: PageSize = 20,
    ) -> McpPage:
        params = FolderListRequest(
            external_id=external_id, knowledge_id=knowledge_id, folder_id=folder_id, cursor=cursor, page_size=page_size
        )
        return McpPage.model_validate(await runtime.invoke(ctx, "list_folders", params))

    @server.tool(
        description="分页浏览指定空间或目录的直接子文件,支持名称/更新时间排序和状态筛选。", annotations=annotations
    )
    async def list_files(
        external_id: ExternalAccount,
        knowledge_id: ResourceId,
        ctx: Context,
        folder_id: FolderId | None = None,
        statuses: Statuses | None = None,
        sort_by: Literal["file_name", "update_time"] = "update_time",
        order: Literal["asc", "desc"] = "desc",
        cursor: Cursor | None = None,
        page_size: PageSize = 20,
    ) -> McpPage:
        params = FileListRequest(
            external_id=external_id,
            knowledge_id=knowledge_id,
            folder_id=folder_id,
            statuses=statuses,
            sort_by=sort_by,
            order=order,
            cursor=cursor,
            page_size=page_size,
        )
        return McpPage.model_validate(await runtime.invoke(ctx, "list_files", params))

    @server.tool(
        description="按文件名或正文关键词搜索有权文件,可限定空间或目录子树,不生成模型答案。", annotations=annotations
    )
    async def search_files(
        external_id: ExternalAccount,
        keyword: Keyword,
        ctx: Context,
        knowledge_ids: SpaceIds | None = None,
        folder_scope: FolderScope | None = None,
        search_mode: Literal["name", "content", "all"] = "all",
        cursor: Cursor | None = None,
        page_size: PageSize = 20,
    ) -> McpPage:
        params = FileSearchRequest(
            external_id=external_id,
            keyword=keyword,
            knowledge_ids=knowledge_ids,
            folder_scope=folder_scope,
            search_mode=search_mode,
            cursor=cursor,
            page_size=page_size,
        )
        return McpPage.model_validate(await runtime.invoke(ctx, "search_files", params))
