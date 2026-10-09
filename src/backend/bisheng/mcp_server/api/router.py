import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.datastructures import MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from bisheng.common.errcode import BaseErrorCode
from bisheng.common.services.config_service import settings
from bisheng.core.config.settings import McpServerConf
from bisheng.mcp_server.api.endpoints.tools import register_tools
from bisheng.mcp_server.domain.services.auth_service import McpAuthService
from bisheng.mcp_server.domain.services.factory import build_search_service
from bisheng.mcp_server.domain.services.search_service import McpSearchService
from bisheng.utils import get_request_ip

logger = logging.getLogger(__name__)
AUTH_STATUS = {19801: 401, 19802: 401, 19803: 401, 19804: 403, 19812: 403, 19805: 429, 19806: 503}


async def get_config() -> McpServerConf:
    return (await settings.get_mcp_conf()).server


class McpServerApp:
    def __init__(
        self,
        config_provider: Callable[[], Awaitable[McpServerConf]] = get_config,
        search_factory: Callable[..., Any] = build_search_service,
    ) -> None:
        self.config_provider = config_provider
        self.search_service = McpSearchService(search_factory)
        self.server: FastMCP | None = None
        self.security: TransportSecuritySettings | None = None

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        conf = await self.config_provider()
        if not conf.enabled:
            yield
            return
        # MCP accepts any Host/Origin; token and resource checks remain mandatory.
        self.security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
        server = FastMCP("Bisheng", stateless_http=True, json_response=True, transport_security=self.security)
        register_tools(server, self.search_service)
        server.streamable_http_app()
        self.server = server
        try:
            yield
        finally:
            self.server = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        server = self.server
        if server is None:
            await Response(status_code=404)(scope, receive, send)
            return
        request = Request(scope, receive)
        try:
            principal = await McpAuthService.authenticate(
                request.headers.get("X-Developer-Token"),
                request_ip=get_request_ip(request),
                user_agent=request.headers.get("user-agent"),
                method=request.method,
            )
        except BaseErrorCode as exc:
            await JSONResponse(
                {"status_code": exc.code, "status_message": exc.message, "data": None},
                status_code=AUTH_STATUS.get(exc.code, 403),
            )(scope, receive, send)
            return
        except Exception as exc:
            logger.error("mcp authentication unavailable exception_type=%s", type(exc).__name__)
            await JSONResponse({"detail": "MCP authentication unavailable"}, status_code=503)(scope, receive, send)
            return
        if request.method != "POST":
            await Response(status_code=405, headers={"Allow": "POST"})(scope, receive, send)
            return
        scope = dict(scope)
        scope["state"] = {**scope.get("state", {}), "mcp_principal": principal}
        # A request owns its SDK task group, so disconnect/cancellation closes tool resources.
        manager = StreamableHTTPSessionManager(
            app=server.session_manager.app,
            json_response=True,
            stateless=True,
            security_settings=self.security,
        )
        body_read = anyio.Event()

        async def receive_body() -> dict[str, Any]:
            message = await receive()
            if message["type"] == "http.request" and not message.get("more_body", False):
                body_read.set()
            return message

        async with manager.run(), anyio.create_task_group() as group:

            async def watch_disconnect() -> None:
                # Only read after the SDK consumed the complete body; avoid competing consumers.
                await body_read.wait()
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        group.cancel_scope.cancel()
                        return

            group.start_soon(watch_disconnect)
            try:
                await manager.handle_request(scope, receive_body, send)
            finally:
                group.cancel_scope.cancel()


def mcp_routes(runtime: McpServerApp) -> list[Route]:
    return [Route("/mcp", endpoint=runtime), Route("/mcp/", endpoint=runtime)]


class McpCorsMiddleware:
    """Allow header-authenticated MCP requests without changing REST CORS."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.cors = CORSMiddleware(
            app,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=False,
            expose_headers=["MCP-Protocol-Version", "X-Trace-ID"],
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "").removeprefix(scope.get("root_path", ""))
        if scope["type"] != "http" or path not in {"/mcp", "/mcp/"}:
            await self.app(scope, receive, send)
            return

        async def send_mcp(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                # Inner REST CORS can add cookie credentials or a specific origin.
                # MCP uses its developer-token header and always returns a wildcard origin.
                if "Access-Control-Allow-Origin" in headers:
                    headers["Access-Control-Allow-Origin"] = "*"
                if "Access-Control-Allow-Credentials" in headers:
                    del headers["Access-Control-Allow-Credentials"]
            await send(message)

        await self.cors(scope, receive, send_mcp)
