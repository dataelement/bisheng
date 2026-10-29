"""Streamable HTTP transport for user-authorized Desktop Work capabilities."""

import json
from contextvars import ContextVar
from urllib.parse import urlsplit

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from loguru import logger
from mcp import types
from mcp.server import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import ValidationError
from starlette.responses import Response

from bisheng.common.errcode import BaseErrorCode
from bisheng.core.config.dsh import normalize_dsh_origin
from bisheng.dsh.domain.services.work_capabilities import WorkCapabilitiesService

current_work_service: ContextVar[WorkCapabilitiesService] = ContextVar("current_work_service")


def work_transport_security(public_url: str) -> TransportSecuritySettings:
    public_origin = normalize_dsh_origin(public_url)
    origin = urlsplit(public_origin)
    # Existing ingress installations may forward the hostname without its port.
    # Both entries derive from the single configured platform origin.
    hostname = f"[{origin.hostname}]" if ":" in origin.hostname else origin.hostname
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(dict.fromkeys([origin.netloc, hostname])),
        allowed_origins=[public_origin],
    )


def create_work_mcp_runtime(security_settings=None):
    server = Server("bisheng-enterprise-work")

    @server.list_tools()
    async def list_tools():
        return [types.Tool.model_validate(row) for row in await current_work_service.get().list_tools()]

    @server.call_tool()
    async def call_tool(name, arguments):
        try:
            result = jsonable_encoder(await current_work_service.get().call_tool(name, arguments))
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
                structuredContent={"result": result},
            )
        except (HTTPException, BaseErrorCode, ValidationError, TimeoutError) as exc:
            # Business failures remain MCP failures and keep credentials/upstream details private.
            code = getattr(exc, "status_code", getattr(exc, "code", "TOOL_FAILED"))
            return types.CallToolResult(
                isError=True,
                content=[
                    types.TextContent(
                        type="text", text=json.dumps({"code": code, "error": "Enterprise tool execution failed"})
                    )
                ],
            )
        except Exception:
            logger.error("Desktop MCP tool execution failed tool={}", name)
            return types.CallToolResult(
                isError=True, content=[types.TextContent(type="text", text="Enterprise tool execution failed")]
            )

    @server.list_resources()
    async def list_resources():
        return [
            types.Resource(
                uri=row["uri"],
                name=row["name"],
                title=row["title"],
                description=row["description"],
                mimeType="application/json",
            )
            for row in await current_work_service.get().list_skills()
        ]

    @server.read_resource()
    async def read_resource(uri):
        try:
            bundle = await current_work_service.get().read_skill(str(uri))
        except Exception:
            raise ValueError("Enterprise Skill is unavailable; refresh the catalog") from None
        return [ReadResourceContents(content=json.dumps(bundle, ensure_ascii=False), mime_type="application/json")]

    # Only the authenticated FastAPI route reaches this manager. Host and Origin
    # validation also apply to cookie-authenticated browser requests.
    if security_settings is None:
        from bisheng.common.services.config_service import settings

        security_settings = work_transport_security(settings.dsh.platform_public_url)

    return StreamableHTTPSessionManager(
        app=server,
        json_response=True,
        stateless=True,
        security_settings=security_settings,
    )


class WorkMcpResponse(Response):
    def __init__(self, manager, user):
        super().__init__()
        self.manager = manager
        self.user = user

    async def __call__(self, scope, receive, send):
        # Bound the ASGI body before the MCP SDK parses it, including chunked requests.
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > 256 * 1024:
                await Response(status_code=413)(scope, receive, send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        token = current_work_service.set(WorkCapabilitiesService(self.user))
        try:
            await self.manager.handle_request(scope, bounded_receive, send)
        finally:
            current_work_service.reset(token)
