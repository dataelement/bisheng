"""Stateless Streamable HTTP MCP server and exact-path dispatcher."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException
from loguru import logger
from mcp import types
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import ValidationError

from bisheng.common.errcode import BaseErrorCode
from bisheng.common.services.config_service import settings
from bisheng.core.logger import trace_id_var
from bisheng.database.models.audit_log import AuditLog
from bisheng.open_api.domain.context import get_current_open_api_principal
from bisheng.open_api.domain.services.call_audit_service import open_api_call_audit_service
from bisheng.open_mcp.auth import MCP_PATH, OpenMcpTransportAuth, get_current_mcp_scope
from bisheng.open_mcp.registry import TOOL_REGISTRY, list_tools_for
from bisheng.open_mcp.result import error_result, error_result_from_exception, success_result
from bisheng.open_mcp.tools import execute_tool
from bisheng.open_mcp.upload import McpUploadError


class _StreamableHttpApp:
    def __init__(self, manager: StreamableHTTPSessionManager) -> None:
        self.manager = manager

    async def __call__(self, scope, receive, send) -> None:
        await self.manager.handle_request(scope, receive, send)


class OpenMcpDispatchMiddleware:
    """Route only the fixed MCP path without changing the existing v2 router."""

    def __init__(self, app, *, mcp_app) -> None:
        self.app = app
        self.mcp_app = mcp_app

    async def __call__(self, scope, receive, send) -> None:
        path = str(scope.get("path") or "").rstrip("/")
        if scope.get("type") == "http" and path == MCP_PATH:
            await self.mcp_app(scope, receive, send)
            return
        await self.app(scope, receive, send)


@dataclass(slots=True)
class OpenMcpRuntime:
    app: Any
    manager: StreamableHTTPSessionManager

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        async with self.manager.run():
            yield


def create_open_mcp_runtime() -> OpenMcpRuntime:
    server = Server("bisheng-open-mcp")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        principal = get_current_open_api_principal()
        if principal is None:
            return []
        return list_tools_for(principal)

    async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult | types.ErrorData:
        started_at = time.perf_counter()
        definition = TOOL_REGISTRY.get(name)
        principal = get_current_open_api_principal()
        result_code: int | str | None = None
        result_name = "failed"
        try:
            if definition is None:
                result_code = types.INVALID_PARAMS
                return types.ErrorData(code=types.INVALID_PARAMS, message="Unknown tool")
            if principal is None:
                result_code = "UNAUTHENTICATED"
                return error_result(result_code, "MCP execution identity is missing")
            if not definition.visible_to(principal):
                result_code = "PERMISSION_DENIED"
                return error_result(result_code, "Credential is not allowed to call this tool")

            try:
                definition.input_model.model_validate(arguments)
            except ValidationError as exc:
                tool_result = error_result_from_exception(exc)
                result_code = _tool_error_code(tool_result)
                return tool_result

            result = await execute_tool(name, arguments)
            result_name = "success"
            return success_result(result)
        except (BaseErrorCode, HTTPException, McpUploadError) as exc:
            tool_result = error_result_from_exception(exc)
            result_code = _tool_error_code(tool_result)
            return tool_result
        except Exception:
            result_code = types.INTERNAL_ERROR
            logger.exception("open_mcp.tool_call internal error tool={}", name)
            return types.ErrorData(code=types.INTERNAL_ERROR, message="Internal error")
        finally:
            if definition is not None:
                _audit_tool_call(
                    name=name,
                    scope_code=definition.scope,
                    result=result_name,
                    error_code=result_code,
                    started_at=started_at,
                )

    async def handle_call_tool(request: types.CallToolRequest):
        result = await call_tool(request.params.name, request.params.arguments or {})
        if isinstance(result, types.ErrorData):
            return result
        return types.ServerResult(result)

    # Register directly instead of using ``Server.call_tool``. The SDK decorator
    # intentionally converts every exception into a tool result, while F067 must
    # preserve the MCP distinction between expected tool failures and JSON-RPC
    # protocol/internal errors.
    server.request_handlers[types.CallToolRequest] = handle_call_tool

    manager = StreamableHTTPSessionManager(
        app=server,
        json_response=True,
        stateless=True,
        max_request_body_size=settings.open_mcp.max_request_body_bytes,
        security_settings=_transport_security_settings(),
    )
    return OpenMcpRuntime(
        app=OpenMcpTransportAuth(_StreamableHttpApp(manager)),
        manager=manager,
    )


def _transport_security_settings() -> TransportSecuritySettings:
    allowed_hosts = list(settings.open_mcp.transport_allowed_hosts)
    allowed_origins = list(settings.open_mcp.transport_allowed_origins)
    if settings.open_api.public_base_url:
        parsed = urlsplit(settings.open_api.public_base_url)
        if parsed.netloc and parsed.netloc not in allowed_hosts:
            allowed_hosts.append(parsed.netloc)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if parsed.scheme and parsed.netloc and origin not in allowed_origins:
            allowed_origins.append(origin)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=settings.open_mcp.enable_dns_rebinding_protection,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


def _tool_error_code(result: types.CallToolResult) -> int | str | None:
    if not result.content or not isinstance(result.content[0], types.TextContent):
        return None
    import json

    try:
        return json.loads(result.content[0].text)["error"]["code"]
    except (KeyError, TypeError, json.JSONDecodeError):
        return None


def _audit_tool_call(
    *,
    name: str,
    scope_code: str | None,
    result: str,
    error_code: int | str | None,
    started_at: float,
) -> None:
    principal = get_current_open_api_principal()
    scope = get_current_mcp_scope() or {}
    client = scope.get("client")
    ip_address = client[0] if isinstance(client, (tuple, list)) and client else None
    tenant_id = principal.tenant_id if principal else None
    metadata = {
        "channel": "mcp",
        "credential_id": principal.credential_id if principal else None,
        "actor_kind": principal.actor_kind if principal else None,
        "actor_id": principal.actor_id if principal else None,
        "identity_mode": principal.mode if principal else None,
        "authorization_subject_type": principal.authorization_subject_type if principal else None,
        "authorization_subject_id": principal.authorization_subject_id if principal else None,
        "scope": scope_code,
        "result": result,
        "error_code": error_code,
        "latency_ms": max(0, round((time.perf_counter() - started_at) * 1000)),
        "trace_id": str(trace_id_var.get() or ""),
    }
    open_api_call_audit_service.enqueue(
        AuditLog(
            tenant_id=tenant_id,
            operator_id=(principal.actor_id if principal and principal.actor_kind == "natural_person" else 0),
            operator_name=(principal.actor_name if principal and principal.actor_kind == "service_account" else None),
            operator_tenant_id=tenant_id,
            action="open_api.call",
            target_type="mcp_tool",
            target_id=name,
            ip_address=ip_address,
            audit_metadata=metadata,
        )
    )


__all__ = ["MCP_PATH", "OpenMcpDispatchMiddleware", "OpenMcpRuntime", "create_open_mcp_runtime"]
