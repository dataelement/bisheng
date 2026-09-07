"""ASGI audit middleware restricted to the authenticated v2 surface."""

from __future__ import annotations

import time
from typing import Any

from bisheng.core.logger import trace_id_var
from bisheng.database.models.audit_log import AuditLog
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.domain.scopes import get_open_api_scope_marker
from bisheng.open_api.domain.services.call_audit_service import open_api_call_audit_service

OPEN_API_V2_PREFIX = "/api/v2"


class OpenApiAuditMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        if scope.get("type") not in {"http", "websocket"} or not str(
            scope.get("path", "")
        ).startswith(OPEN_API_V2_PREFIX):
            await self.app(scope, receive, send)
            return

        started_at = time.perf_counter()
        result_status = 500
        response_finished = False

        async def audit_send(message: dict[str, Any]) -> None:
            nonlocal response_finished, result_status
            message_type = message.get("type")
            if message_type == "http.response.start":
                result_status = int(message.get("status", 500))
            elif message_type == "http.response.body" and not message.get("more_body", False):
                response_finished = True
            elif message_type == "websocket.accept":
                result_status = 101
            elif message_type == "websocket.close":
                response_finished = True
                if result_status != 101:
                    result_status = int(message.get("code", 1000))
            await send(message)

        try:
            await self.app(scope, receive, audit_send)
        finally:
            if scope.get("type") == "websocket" or response_finished:
                self._enqueue(scope, result_status, started_at)
            else:
                self._enqueue(scope, 500, started_at)

    @staticmethod
    def _enqueue(scope: dict[str, Any], result_status: int, started_at: float) -> None:
        principal = scope.get("open_api_principal")
        if not isinstance(principal, OpenApiPrincipal):
            principal = None
        route = scope.get("route")
        route_path = getattr(route, "path", None) or scope.get("path") or ""
        method = scope.get("method") or ("WS" if scope.get("type") == "websocket" else "")
        target_id = f"{method} {route_path}".strip()
        marker = get_open_api_scope_marker(scope.get("endpoint"))
        client = scope.get("client")
        ip_address = client[0] if isinstance(client, (tuple, list)) and client else None
        latency_ms = max(0, round((time.perf_counter() - started_at) * 1000))
        error_code = scope.get("open_api_error_code")
        if error_code is None and result_status >= 400:
            error_code = result_status

        metadata = {
            "credential_id": principal.credential_id if principal else None,
            "actor_kind": principal.actor_kind if principal else None,
            "actor_id": principal.actor_id if principal else None,
            "identity_mode": principal.mode if principal else None,
            "authorization_subject_type": (
                principal.authorization_subject_type if principal else None
            ),
            "authorization_subject_id": (
                principal.authorization_subject_id if principal else None
            ),
            "on_behalf_of_user_id": principal.on_behalf_of_user_id if principal else None,
            "end_user_id": principal.end_user_id if principal else None,
            "scope": marker.scope if marker else None,
            "http_status": result_status,
            "error_code": error_code,
            "latency_ms": latency_ms,
            "trace_id": str(trace_id_var.get() or ""),
        }
        tenant_id = principal.tenant_id if principal else None
        operator_id = (
            principal.actor_id
            if principal is not None and principal.actor_kind == "natural_person"
            else 0
        )
        operator_name = (
            principal.actor_name
            if principal is not None and principal.actor_kind == "service_account"
            else None
        )
        open_api_call_audit_service.enqueue(
            AuditLog(
                tenant_id=tenant_id,
                operator_id=operator_id,
                operator_name=operator_name,
                operator_tenant_id=tenant_id,
                action="open_api.call",
                target_type="api_endpoint",
                target_id=target_id,
                ip_address=ip_address,
                audit_metadata=metadata,
            )
        )


__all__ = ["OPEN_API_V2_PREFIX", "OpenApiAuditMiddleware"]
