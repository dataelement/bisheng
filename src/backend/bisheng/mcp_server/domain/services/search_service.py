import asyncio
from collections.abc import Callable
from typing import Any

from bisheng.developer_token.domain.schemas import DeveloperTokenPrincipal
from bisheng.mcp_server.domain.schemas.search import McpSearchRequest
from bisheng.mcp_server.domain.services.auth_service import McpAuthService
from bisheng.open_endpoints.domain.schemas.filelib import RetrieveReq, RetrieveResp


class McpSearchService:
    def __init__(self, factory: Callable[..., Any]) -> None:
        self.factory = factory

    async def search(self, request: Any, principal: DeveloperTokenPrincipal, req: McpSearchRequest) -> RetrieveResp:
        with McpAuthService.use_identity(principal):
            async with self.factory(request, principal.user) as service:
                return await asyncio.wait_for(
                    service.retrieve(RetrieveReq(**req.model_dump())),
                    timeout=service.timeout_seconds,
                )
