"""Fail-closed request dependency shared by every ``/api/v2`` route."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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
)
from bisheng.open_api.domain.services.access_context import (
    open_api_access_context as shared_open_api_access_context,
)
from bisheng.open_api.domain.services.credential_validator import validate_bearer
from bisheng.open_api.domain.services.credential_watcher import watch_websocket_credential
from bisheng.open_api.domain.services.tenant_setting_service import TenantSettingService
from bisheng.user.domain.services.auth import AuthJwt

WS_POLICY_VIOLATION = 1008


async def verify_open_api_access(conn: HTTPConnection) -> AsyncIterator[OpenApiPrincipal]:
    """Authenticate a v2 connection and install its typed execution identity."""

    async with open_api_access_context(conn) as principal:
        yield principal


@asynccontextmanager
async def open_api_access_context(
    conn: HTTPConnection, *, inspect_body: bool = True
) -> AsyncIterator[OpenApiPrincipal]:
    """Share admission checks with failures raised before dependency execution."""

    try:
        async with shared_open_api_access_context(
            authorization=conn.headers.get("Authorization"),
            headers=conn.headers.items(),
            marker=get_open_api_scope_marker(conn.scope.get("endpoint")),
            on_behalf_of=conn.headers.get("X-On-Behalf-Of"),
            end_user=conn.headers.get("X-End-User"),
            connection_scope=conn.scope,
            before_identity_check=lambda: _assert_no_removed_identity_input(conn, inspect_body=inspect_body),
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


def _raise_for_connection(conn: HTTPConnection, exc: OpenApiAuthError) -> None:
    conn.scope["open_api_error_code"] = exc.code
    if isinstance(conn, WebSocket):
        raise WebSocketException(code=WS_POLICY_VIOLATION, reason=str(exc.code)) from exc
    raise exc


async def _assert_no_removed_identity_input(conn: HTTPConnection, *, inspect_body: bool = True) -> None:
    if "user_id" in conn.query_params:
        raise OpenApiRemovedIdentityInputError()
    if not isinstance(conn, Request) or not inspect_body:
        return
    content_type = (conn.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await conn.form()
        if "user_id" in form:
            raise OpenApiRemovedIdentityInputError()
        return
    if (
        content_type
        and content_type != "application/json"
        and not (content_type.startswith("application/") and content_type.endswith("+json"))
    ):
        return
    body = await conn.body()
    if not body:
        return
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError):
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
