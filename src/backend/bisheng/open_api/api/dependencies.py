"""Fail-closed request dependency shared by every ``/api/v2`` route."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, Request, WebSocket, WebSocketException
from starlette.requests import HTTPConnection

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.llm_tenant import LLMModelSharedReadonlyError
from bisheng.common.errcode.open_api import (
    OpenApiAuthError,
    OpenApiEndpointUnregisteredError,
    OpenApiRemovedIdentityInputError,
)
from bisheng.common.services.config_service import settings
from bisheng.open_api.domain.context import (
    OpenApiPrincipal,
    get_current_open_api_principal,
)
from bisheng.open_api.domain.scopes import get_open_api_scope_marker
from bisheng.open_api.domain.services.access_context import (
    OPEN_API_PRINCIPAL_SCOPE_KEY,
    open_api_access_context,
)
from bisheng.open_api.domain.services.credential_validator import validate_bearer
from bisheng.open_api.domain.services.tenant_setting_service import TenantSettingService
from bisheng.user.domain.services.auth import AuthJwt

WS_POLICY_VIOLATION = 1008


async def verify_open_api_access(conn: HTTPConnection) -> AsyncIterator[OpenApiPrincipal]:
    """Authenticate a v2 connection and install its typed execution identity."""

    try:
        async with open_api_access_context(
            authorization=conn.headers.get("Authorization"),
            headers=conn.headers.items(),
            marker=get_open_api_scope_marker(conn.scope.get("endpoint")),
            on_behalf_of=conn.headers.get("X-On-Behalf-Of"),
            end_user=conn.headers.get("X-End-User"),
            connection_scope=conn.scope,
            before_identity_check=lambda: _assert_no_removed_identity_input(conn),
            credential_validator=validate_bearer,
            settings_obj=settings,
            tenant_setting_service=TenantSettingService,
        ) as principal:
            yield principal
    except OpenApiAuthError as exc:
        _raise_for_connection(conn, exc)


def get_open_api_execution(conn: HTTPConnection) -> OpenApiPrincipal:
    """Return the principal installed by the router dependency."""

    principal = conn.scope.get(OPEN_API_PRINCIPAL_SCOPE_KEY) or get_current_open_api_principal()
    if not isinstance(principal, OpenApiPrincipal):
        raise OpenApiEndpointUnregisteredError()
    return principal


async def get_service_account_admin(auth_jwt: AuthJwt = Depends()) -> UserPayload:
    """Admit a global super admin or the active tenant's administrator."""

    try:
        return await UserPayload.get_tenant_admin_user(auth_jwt)
    except LLMModelSharedReadonlyError as exc:
        raise UnAuthorizedError() from exc


@asynccontextmanager
async def watch_websocket_credential(
    websocket: WebSocket,
    *,
    interval_seconds: float = 3.0,
) -> AsyncIterator[None]:
    """Close a connected v2 socket when its credential becomes invalid."""

    expected = get_current_open_api_principal()

    async def monitor() -> None:
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                current = await validate_bearer(websocket.headers.get("Authorization"))
                if expected is None or current.credential_id != expected.credential_id:
                    raise OpenApiEndpointUnregisteredError()
            except OpenApiAuthError as exc:
                with suppress(RuntimeError):
                    await websocket.close(code=WS_POLICY_VIOLATION, reason=str(exc.code))
                return

    task = asyncio.create_task(monitor(), name="open-api-websocket-credential-watch")
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def _raise_for_connection(conn: HTTPConnection, exc: OpenApiAuthError) -> None:
    conn.scope["open_api_error_code"] = exc.code
    if isinstance(conn, WebSocket):
        raise WebSocketException(code=WS_POLICY_VIOLATION, reason=str(exc.code)) from exc
    raise exc


async def _assert_no_removed_identity_input(conn: HTTPConnection) -> None:
    if "user_id" in conn.query_params:
        raise OpenApiRemovedIdentityInputError()
    if not isinstance(conn, Request):
        return
    content_type = conn.headers.get("content-type") or ""
    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await conn.form()
        if "user_id" in form:
            raise OpenApiRemovedIdentityInputError()
        return
    if "application/json" not in content_type:
        return
    body = await conn.body()
    if not body:
        return
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return
    if isinstance(payload, dict) and "user_id" in payload:
        raise OpenApiRemovedIdentityInputError()


__all__ = [
    "WS_POLICY_VIOLATION",
    "get_open_api_execution",
    "get_service_account_admin",
    "verify_open_api_access",
    "watch_websocket_credential",
]
