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
    OpenApiAuthDependencyUnavailableError,
    OpenApiAuthError,
    OpenApiDelegationModeUnsupportedError,
    OpenApiEndpointUnregisteredError,
    OpenApiRemovedIdentityInputError,
    OpenApiScopeMissingError,
    PersonalTokenDisabledError,
)
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, current_tenant_id, visible_tenant_ids
from bisheng.open_api.domain.context import (
    OpenApiPrincipal,
    get_current_open_api_principal,
    reset_current_open_api_principal,
    set_current_open_api_principal,
)
from bisheng.open_api.domain.scopes import get_open_api_scope_marker
from bisheng.open_api.domain.services.credential_validator import validate_bearer
from bisheng.open_api.domain.services.identity_service import (
    assert_no_removed_identity_headers,
    resolve_request_identity,
)
from bisheng.open_api.domain.services.tenant_setting_service import TenantSettingService
from bisheng.permission.application.identity import (
    reset_current_permission_actor,
    set_current_permission_actor,
)
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.user.domain.services.auth import AuthJwt

WS_POLICY_VIOLATION = 1008
_SCOPE_PRINCIPAL_KEY = "open_api_principal"


async def verify_open_api_access(conn: HTTPConnection) -> AsyncIterator[OpenApiPrincipal]:
    """Authenticate a v2 connection and install its typed execution identity."""

    try:
        principal = await validate_bearer(conn.headers.get("Authorization"))
    except OpenApiAuthError as exc:
        _raise_for_connection(conn, exc)
        raise AssertionError("unreachable")

    tenant_token = current_tenant_id.set(principal.tenant_id)
    # A credential is always tenant-scoped. Root-owned shared rows remain
    # visible through the standard tenant filter, but administrator facts on a
    # natural-person PAT must never widen this set to another child tenant.
    visible_token = visible_tenant_ids.set(frozenset({DEFAULT_TENANT_ID, principal.tenant_id}))
    principal_token = None
    permission_token = None
    conn.scope[_SCOPE_PRINCIPAL_KEY] = principal
    try:
        if principal.actor_kind == "natural_person":
            if not settings.open_api.pat_enabled:
                raise PersonalTokenDisabledError()
            try:
                tenant_policy = await TenantSettingService.get_policy(principal.tenant_id)
            except OpenApiAuthError:
                raise
            except Exception as exc:
                raise OpenApiAuthDependencyUnavailableError() from exc
            if not tenant_policy.enabled:
                raise PersonalTokenDisabledError()

        marker = get_open_api_scope_marker(conn.scope.get("endpoint"))
        if marker is None:
            raise OpenApiEndpointUnregisteredError()
        if marker.scope is not None and not principal.has_scope(marker.scope):
            raise OpenApiScopeMissingError(required=marker.scope)

        assert_no_removed_identity_headers(conn.headers.items())
        await _assert_no_removed_identity_input(conn)
        principal = await resolve_request_identity(
            principal,
            on_behalf_of=conn.headers.get("X-On-Behalf-Of"),
            end_user=conn.headers.get("X-End-User"),
        )
        conn.scope[_SCOPE_PRINCIPAL_KEY] = principal
        if principal.mode not in marker.modes:
            raise OpenApiDelegationModeUnsupportedError()

        actor = PermissionActor(
            subject_type=principal.authorization_subject_type,
            subject_id=principal.authorization_subject_id,
            tenant_id=principal.tenant_id,
            super_admin=False,
            tenant_admin_tenant_ids=frozenset(),
        )
        principal_token = set_current_open_api_principal(principal)
        permission_token = set_current_permission_actor(actor)
        yield principal
    except OpenApiAuthError as exc:
        _raise_for_connection(conn, exc)
    finally:
        if permission_token is not None:
            reset_current_permission_actor(permission_token)
        if principal_token is not None:
            reset_current_open_api_principal(principal_token)
        visible_tenant_ids.reset(visible_token)
        current_tenant_id.reset(tenant_token)


def get_open_api_execution(conn: HTTPConnection) -> OpenApiPrincipal:
    """Return the principal installed by the router dependency."""

    principal = conn.scope.get(_SCOPE_PRINCIPAL_KEY) or get_current_open_api_principal()
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
    if "application/json" not in (conn.headers.get("content-type") or ""):
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
