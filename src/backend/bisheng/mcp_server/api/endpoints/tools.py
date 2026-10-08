import asyncio
import logging
import time

from fastapi import HTTPException
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import ConfigDict

from bisheng.common.errcode import BaseErrorCode
from bisheng.core.logger import trace_id_var
from bisheng.mcp_server.domain.schemas.search import KnowledgeIds, MaxContent, McpSearchRequest, SearchQuery, TopK
from bisheng.mcp_server.domain.services.search_service import McpSearchService
from bisheng.open_endpoints.domain.schemas.filelib import RetrieveFilters, RetrieveResp

logger = logging.getLogger(__name__)


def register_tools(server: FastMCP, search_service: McpSearchService) -> None:
    @server.tool(
        description="检索有权访问的知识库, 返回文本片段和文档来源, 不生成模型答案。",
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
    )
    async def search_knowledge(
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
        started = time.monotonic()
        outcome = "failed"
        try:
            req = McpSearchRequest(
                query=query,
                knowledge_base_ids=knowledge_base_ids,
                top_k=top_k,
                max_content=max_content,
                filters=filters,
            )
            result = await search_service.search(request, principal, req)
            outcome = "success"
            return result
        except asyncio.TimeoutError as exc:
            raise ToolError("Knowledge retrieval timed out") from exc
        except (BaseErrorCode, HTTPException) as exc:
            raise ToolError("Knowledge retrieval denied or unavailable") from exc
        except Exception as exc:
            # Do not log exception text: it can include credentials, queries or signed URLs.
            logger.error("mcp retrieval failed exception_type=%s token_id=%s", type(exc).__name__, principal.token_id)
            raise ToolError("Knowledge retrieval failed") from exc
        finally:
            logger.info(
                "mcp tool=search_knowledge token_id=%s user_id=%s tenant_id=%s trace_id=%s outcome=%s elapsed=%.3f",
                principal.token_id,
                principal.user.user_id,
                principal.tenant_id,
                trace_id_var.get(),
                outcome,
                time.monotonic() - started,
            )

    # FastMCP's default argument model silently ignores extra fields.
    tool = server._tool_manager.get_tool("search_knowledge")
    tool.fn_metadata.arg_model.model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")
    tool.fn_metadata.arg_model.model_rebuild(force=True)
    tool.parameters = tool.fn_metadata.arg_model.model_json_schema()
