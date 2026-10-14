"""ASGI authentication and request-size gate for the MCP transport."""

from __future__ import annotations

import time
from contextvars import ContextVar
from typing import Any

from fastapi.encoders import jsonable_encoder
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from bisheng.common.errcode.open_api import OpenApiAuthError
from bisheng.common.services.config_service import settings
from bisheng.core.logger import trace_id_var
from bisheng.database.models.audit_log import AuditLog
from bisheng.open_api.api.exception_handlers import open_api_http_status
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.domain.scopes import OpenApiScopeMarker
from bisheng.open_api.domain.services.access_context import (
    OPEN_API_PRINCIPAL_SCOPE_KEY,
    open_api_access_context,
)
from bisheng.open_api.domain.services.call_audit_service import open_api_call_audit_service

MCP_PATH = "/api/v2/mcp"
_MCP_MARKER = OpenApiScopeMarker(scope=None, modes=frozenset({"S", "D"}), session=False)
current_mcp_scope: ContextVar[dict[str, Any] | None] = ContextVar("current_mcp_scope", default=None)


class McpRequestTooLargeError(Exception):
    """Raised before MCP parses a request body that exceeds the configured cap."""


class OpenMcpTransportAuth:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        started_at = time.perf_counter()
        headers = Headers(scope=scope)
        try:
            async with open_api_access_context(
                authorization=headers.get("Authorization"),
                headers=headers.items(),
                marker=_MCP_MARKER,
                on_behalf_of=headers.get("X-On-Behalf-Of"),
                end_user=headers.get("X-End-User"),
                connection_scope=scope,
            ):
                declared = headers.get("content-length")
                if declared:
                    try:
                        declared_size = int(declared)
                    except ValueError:
                        _audit_transport_rejection(scope, "INVALID_CONTENT_LENGTH", started_at)
                        await _send_invalid_content_length(scope, receive, send)
                        return
                else:
                    declared_size = 0
                if declared_size > settings.open_mcp.max_request_body_bytes:
                    _audit_transport_rejection(scope, "REQUEST_TOO_LARGE", started_at)
                    await _send_body_too_large(scope, receive, send)
                    return
                scope_token = current_mcp_scope.set(scope)
                try:
                    await self.app(scope, _limited_receive(receive), send)
                finally:
                    current_mcp_scope.reset(scope_token)
        except OpenApiAuthError as exc:
            scope["open_api_error_code"] = exc.code
            _audit_transport_rejection(scope, exc.code, started_at)
            response = JSONResponse(
                status_code=open_api_http_status(exc),
                content=jsonable_encoder(exc.to_dict()),
            )
            await response(scope, receive, send)
        except McpRequestTooLargeError:
            _audit_transport_rejection(scope, "REQUEST_TOO_LARGE", started_at)
            await _send_body_too_large(scope, receive, send)


def _limited_receive(receive):
    consumed = 0

    async def limited():
        nonlocal consumed
        message = await receive()
        if message.get("type") == "http.request":
            consumed += len(message.get("body") or b"")
            if consumed > settings.open_mcp.max_request_body_bytes:
                raise McpRequestTooLargeError
        return message

    return limited


async def _send_body_too_large(scope, receive, send) -> None:
    response = JSONResponse(
        status_code=413,
        content={"error": {"code": "REQUEST_TOO_LARGE", "message": "MCP request body exceeds configured limit"}},
    )
    await response(scope, receive, send)


async def _send_invalid_content_length(scope, receive, send) -> None:
    response = JSONResponse(
        status_code=400,
        content={"error": {"code": "INVALID_REQUEST", "message": "Invalid Content-Length header"}},
    )
    await response(scope, receive, send)


def _audit_transport_rejection(
    scope: dict[str, Any],
    error_code: int | str,
    started_at: float,
) -> None:
    client = scope.get("client")
    ip_address = client[0] if isinstance(client, (tuple, list)) and client else None
    principal = scope.get(OPEN_API_PRINCIPAL_SCOPE_KEY)
    if not isinstance(principal, OpenApiPrincipal):
        principal = None
    tenant_id = principal.tenant_id if principal else None
    open_api_call_audit_service.enqueue(
        AuditLog(
            operator_id=(principal.actor_id if principal and principal.actor_kind == "natural_person" else 0),
            operator_name=(principal.actor_name if principal and principal.actor_kind == "service_account" else None),
            tenant_id=tenant_id,
            operator_tenant_id=tenant_id,
            action="open_api.call",
            target_type="mcp_transport",
            target_id=MCP_PATH,
            ip_address=ip_address,
            audit_metadata={
                "channel": "mcp",
                "credential_id": principal.credential_id if principal else None,
                "actor_kind": principal.actor_kind if principal else None,
                "actor_id": principal.actor_id if principal else None,
                "identity_mode": principal.mode if principal else None,
                "authorization_subject_type": principal.authorization_subject_type if principal else None,
                "authorization_subject_id": principal.authorization_subject_id if principal else None,
                "result": "failed",
                "error_code": error_code,
                "latency_ms": max(0, round((time.perf_counter() - started_at) * 1000)),
                "trace_id": str(trace_id_var.get() or ""),
            },
        )
    )


def get_current_mcp_scope() -> dict[str, Any] | None:
    return current_mcp_scope.get()


__all__ = ["MCP_PATH", "OpenMcpTransportAuth", "get_current_mcp_scope"]
