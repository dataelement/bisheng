import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import anyio
from mcp.server.fastmcp.exceptions import ToolError

from bisheng.common.errcode import BaseErrorCode
from bisheng.developer_token.domain.schemas import DeveloperTokenPrincipal
from bisheng.mcp_server.domain.schemas.identity import McpExecutionIdentity
from bisheng.mcp_server.domain.schemas.search import McpSearchRequest
from bisheng.mcp_server.domain.services.auth_service import McpAuthService
from bisheng.mcp_server.domain.services.tool_runtime import audit_execution
from bisheng.mcp_server.domain.services.user_context_service import IDENTITY_DENIED_MESSAGE, IDENTITY_TIMEOUT_SECONDS
from bisheng.open_endpoints.domain.schemas.filelib import RetrieveReq, RetrieveResp

logger = logging.getLogger(__name__)


class McpSearchService:
    def __init__(
        self, factory: Callable[..., Any], identity_resolver: Callable[..., Awaitable[McpExecutionIdentity]]
    ) -> None:
        self.factory = factory
        self.identity_resolver = identity_resolver

    async def search(self, request: Any, principal: DeveloperTokenPrincipal, req: McpSearchRequest) -> RetrieveResp:
        started = time.monotonic()
        identity = None
        outcome = "failed"
        try:
            with anyio.fail_after(IDENTITY_TIMEOUT_SECONDS):
                identity = await self.identity_resolver(principal, req.external_id)
            with McpAuthService.use_identity(identity):
                async with self.factory(request, identity.user) as service:
                    result = await asyncio.wait_for(
                        service.retrieve(RetrieveReq(**req.model_dump(exclude={"external_id"}))),
                        timeout=service.timeout_seconds,
                    )
                    outcome = "success"
                    return result
        except (TimeoutError, asyncio.TimeoutError) as exc:
            raise ToolError("Knowledge retrieval timed out") from exc
        except BaseErrorCode as exc:
            message = (
                IDENTITY_DENIED_MESSAGE
                if exc.kwargs.get("mcp_identity_denied")
                else "Knowledge retrieval denied or unavailable"
            )
            raise ToolError(message) from exc
        except Exception as exc:
            # 仅记录类型。避免异常文本包含账号、连接信息或签名地址。
            logger.error("mcp retrieval failed exception_type=%s token_id=%s", type(exc).__name__, principal.token_id)
            raise ToolError("Knowledge retrieval failed") from exc
        finally:
            audit_execution("search_knowledge", principal, identity, outcome, started)
