from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import ConfigDict

from bisheng.mcp_server.api.endpoints.content_tools import register_content_tools
from bisheng.mcp_server.api.endpoints.query_tools import register_query_tools
from bisheng.mcp_server.api.endpoints.write_tools import register_write_tools
from bisheng.mcp_server.domain.schemas.identity import ExternalAccount
from bisheng.mcp_server.domain.schemas.search import KnowledgeIds, MaxContent, McpSearchRequest, SearchQuery, TopK
from bisheng.mcp_server.domain.services.search_service import McpSearchService
from bisheng.mcp_server.domain.services.tool_runtime import McpToolRuntime
from bisheng.open_endpoints.domain.schemas.filelib import RetrieveFilters, RetrieveResp


def register_tools(server: FastMCP, search_service: McpSearchService, runtime: McpToolRuntime) -> None:
    @server.tool(
        description="检索有权访问的知识库, 返回文本片段和文档来源, 不生成模型答案。",
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
    )
    async def search_knowledge(
        external_id: ExternalAccount,
        query: SearchQuery,
        knowledge_base_ids: KnowledgeIds,
        ctx: Context,
        top_k: TopK = 5,
        max_content: MaxContent = 15000,
        filters: RetrieveFilters | None = None,
    ) -> RetrieveResp:
        """Retrieve authorized knowledge chunks and sources without answer generation."""
        request = ctx.request_context.request
        if request is None or "mcp_principal" not in request.scope.get("state", {}):
            raise ToolError("MCP authentication required")
        principal = request.scope["state"]["mcp_principal"]
        req = McpSearchRequest(
            external_id=external_id,
            query=query,
            knowledge_base_ids=knowledge_base_ids,
            top_k=top_k,
            max_content=max_content,
            filters=filters,
        )
        return await search_service.search(request, principal, req)

    register_query_tools(server, runtime)
    register_content_tools(server, runtime)
    register_write_tools(server, runtime)
    # Reject unknown fields and hide sensitive arguments in SDK validation errors.
    for tool in server._tool_manager.list_tools():
        tool.fn_metadata.arg_model.model_config = ConfigDict(
            arbitrary_types_allowed=True,
            extra="forbid",
            hide_input_in_errors=True,
        )
        tool.fn_metadata.arg_model.model_rebuild(force=True)
        tool.parameters = tool.fn_metadata.arg_model.model_json_schema()
