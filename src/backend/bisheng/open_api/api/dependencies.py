"""Fail-closed request dependency shared by every ``/api/v2`` route."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import Depends, Request, WebSocket, WebSocketException
from starlette.requests import HTTPConnection

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.llm_tenant import LLMModelSharedReadonlyError
from bisheng.common.errcode.open_api import (
    OpenApiAuthDependencyUnavailableError,
    OpenApiAuthError,
    OpenApiDelegateLocalDevRefusedError,
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
from bisheng.open_api.domain.scopes import (
    DELEGATE_SCOPE_CODE,
    LOCAL_DEV_TOOLKIT_SCOPE_CODES,
    get_open_api_scope_marker,
)
from bisheng.open_api.domain.services.credential_validator import validate_bearer
from bisheng.open_api.domain.services.credential_watcher import watch_websocket_credential
from bisheng.open_api.domain.services.identity_service import (
    assert_no_removed_identity_headers,
    resolve_request_identity,
)
from bisheng.open_api.domain.services.tenant_setting_service import TenantSettingService
from bisheng.permission.application.data_scope import DATA_SCOPE_ALL
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

    async with open_api_access_context(conn) as principal:
        yield principal


async def admit_open_api_principal(conn: HTTPConnection) -> tuple[OpenApiPrincipal, str]:
    """Authenticate the bearer and settle the personal-token data scope.

    The first half of ``open_api_access_context``, exported so a non-``APIRoute``
    entrance can reuse the *same code* rather than a second copy of it. The MCP
    face (F052) is one such entrance: it registers as a plain Starlette route, so
    neither the router-level dependency nor the ``@open_api_scope`` marker
    reaches it, and "the credential semantics are identical" has to be a fact
    about the call graph rather than a claim in a document.

    Nothing is installed in a ContextVar that outlives this call —
    ``open_api_execution_scope`` owns the execution identity.
    """

    try:
        principal = await validate_bearer(conn.headers.get("Authorization"))
    except OpenApiAuthError as exc:
        _raise_for_connection(conn, exc)
        raise AssertionError("unreachable")

    conn.scope[_SCOPE_PRINCIPAL_KEY] = principal
    if principal.actor_kind != "natural_person":
        return principal, DATA_SCOPE_ALL

    # ``get_policy`` takes the tenant id explicitly, but the DAO underneath it
    # still runs under the automatic tenant filter (C3) — so the tenant
    # ContextVars go in *before* the read, exactly as the unsplit version had
    # them. Reversing these two is the one way this refactor could go wrong
    # without any test noticing, which is why
    # ``test_pat_policy_read_happens_with_tenant_contextvar_installed`` pins it.
    tenant_token = current_tenant_id.set(principal.tenant_id)
    visible_token = visible_tenant_ids.set(frozenset({DEFAULT_TENANT_ID, principal.tenant_id}))
    try:
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
        # F066: reuse this policy read — no second lookup on the hot path.
        return principal, tenant_policy.data_scope
    except OpenApiAuthError as exc:
        _raise_for_connection(conn, exc)
        raise AssertionError("unreachable")
    finally:
        visible_tenant_ids.reset(visible_token)
        current_tenant_id.reset(tenant_token)


@asynccontextmanager
async def open_api_execution_scope(
    conn: HTTPConnection,
    principal: OpenApiPrincipal,
    *,
    data_scope: str,
    prepare: Callable[[OpenApiPrincipal], Awaitable[OpenApiPrincipal]] | None = None,
) -> AsyncIterator[OpenApiPrincipal]:
    """Install the four execution ContextVars for the duration of the request.

    ``prepare`` runs after the tenant ContextVars are up and before the
    permission actor is built — that is where ``/api/v2``'s marker, scope and
    identity-header admission lives, because ``resolve_request_identity`` reads
    the database under the tenant filter and because delegation can still change
    who the actor *is*. An entrance with no delegation to resolve (the MCP face)
    passes no ``prepare`` at all.
    """

    tenant_token = current_tenant_id.set(principal.tenant_id)
    # A credential is always tenant-scoped. Root-owned shared rows remain
    # visible through the standard tenant filter, but administrator facts on a
    # natural-person PAT must never widen this set to another child tenant.
    visible_token = visible_tenant_ids.set(frozenset({DEFAULT_TENANT_ID, principal.tenant_id}))
    principal_token = None
    permission_token = None
    try:
        if prepare is not None:
            principal = await prepare(principal)
            conn.scope[_SCOPE_PRINCIPAL_KEY] = principal

        super_admin = False
        tenant_admin_tenant_ids: frozenset[int] = frozenset()
        if principal.actor_kind == "natural_person":
            from bisheng.permission.application.relation_api import is_tenant_admin
            from bisheng.utils.http_middleware import _check_is_global_super

            try:
                super_admin = await _check_is_global_super(principal.actor_id)
                if not super_admin and await is_tenant_admin(principal.actor_id, principal.tenant_id):
                    tenant_admin_tenant_ids = frozenset({principal.tenant_id})
            except OpenApiAuthError:
                raise
            except Exception as exc:
                raise OpenApiAuthDependencyUnavailableError() from exc

        actor = PermissionActor(
            subject_type=principal.authorization_subject_type,
            subject_id=principal.authorization_subject_id,
            tenant_id=principal.tenant_id,
            super_admin=super_admin,
            tenant_admin_tenant_ids=tenant_admin_tenant_ids,
            data_scope=data_scope,
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


@asynccontextmanager
async def open_api_access_context(
    conn: HTTPConnection, *, inspect_body: bool = True
) -> AsyncIterator[OpenApiPrincipal]:
    """Share admission checks with failures raised before dependency execution."""

    principal, pat_data_scope = await admit_open_api_principal(conn)

    async def admit_request(principal: OpenApiPrincipal) -> OpenApiPrincipal:
        marker = get_open_api_scope_marker(conn.scope.get("endpoint"))
        if marker is None:
            raise OpenApiEndpointUnregisteredError()
        # INV-31 runtime half: the local development toolkit faces execute as
        # the service account itself and never carry delegation, so a delegated
        # key is refused here rather than further down. Both neighbours are
        # wrong answers for it, which is why this sits between them: the
        # missing-scope check below would answer 26003 and send the developer to
        # an administrator who cannot tick the box (26050 refuses the
        # combination at issue time), and resolve_request_identity would answer
        # 26016 "send X-On-Behalf-Of" to a CLI that never sends identity
        # headers. Ordering before the scope check is deliberate: whether the
        # key also carries ``app:manage`` changes nothing about the verdict.
        if marker.scope in LOCAL_DEV_TOOLKIT_SCOPE_CODES and principal.has_scope(DELEGATE_SCOPE_CODE):
            raise OpenApiDelegateLocalDevRefusedError()
        if marker.scope is not None and not principal.has_scope(marker.scope):
            raise OpenApiScopeMissingError(required=marker.scope)

        assert_no_removed_identity_headers(conn.headers.items())
        await _assert_no_removed_identity_input(conn, inspect_body=inspect_body)
        principal = await resolve_request_identity(
            principal,
            on_behalf_of=conn.headers.get("X-On-Behalf-Of"),
            end_user=conn.headers.get("X-End-User"),
        )
        # Published before the mode check on purpose: a request refused for
        # "this endpoint does not accept delegation" must still be audited as
        # the delegated identity it actually carried.
        conn.scope[_SCOPE_PRINCIPAL_KEY] = principal
        if principal.mode not in marker.modes:
            raise OpenApiDelegationModeUnsupportedError()
        return principal

    async with open_api_execution_scope(conn, principal, data_scope=pat_data_scope, prepare=admit_request) as resolved:
        yield resolved


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
    "admit_open_api_principal",
    "get_open_api_execution",
    "get_service_account_admin",
    "open_api_execution_scope",
    "verify_open_api_access",
    "watch_websocket_credential",
]
