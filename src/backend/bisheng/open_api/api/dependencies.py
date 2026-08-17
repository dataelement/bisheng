"""Router-level ``/api/v2`` access dependency + the management-face admin gate (F049 D2 / D3).

Two layers, deliberately not one (design D3):

1. **This dependency**, declared once on the ``/api/v2`` router
   (``dependencies=[Depends(verify_open_api_access)]``) — it validates the
   credential, seeds the tenant ContextVars and the acting identity, and then
   reads the *endpoint's own* scope marker off ``conn.scope["endpoint"]``.
2. **The marker** ``@open_api_scope("…")`` sitting next to each endpoint
   (``open_api/domain/scopes.py``) — a plain attribute, no FastAPI import, so a
   v2 endpoint file can carry it without importing another module's ``api/``
   layer (arch RULE-5).

The pairing is what makes "somebody added an endpoint and forgot the scope" a
**loud** failure: no marker → 26031 (HTTP 500). The alternative — a per-endpoint
``Depends(require_scope(...))`` — fails the other way: a forgotten line means an
endpoint that checks the credential but not the scope, and nothing says so.

HTTP and WebSocket share one function: the parameter is ``HTTPConnection``, the
common base of ``Request`` and ``WebSocket``, and FastAPI merges router-level
dependencies into ``APIWebSocketRoute`` as well. The WS branch must raise
``WebSocketException`` — raising an ``HTTPException`` there produces the HTTP-200
"denial response" that is exactly today's broken assistant-WS behaviour (pit 16).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import Depends, WebSocket, WebSocketException
from loguru import logger
from starlette.requests import HTTPConnection

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.llm_tenant import LLMModelSharedReadonlyError
from bisheng.common.errcode.open_api import (
    OpenApiAuthError,
    OpenApiDelegationNotEnabledError,
    OpenApiEndpointUnregisteredError,
    OpenApiScopeMissingError,
)
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.domain.scopes import (
    OpenApiScopeMarker,
    get_open_api_scope_marker,
    is_known_scope,
)
from bisheng.open_api.domain.services.credential_validator import (
    ValidatedCredential,
    validate_bearer,
)
from bisheng.user.domain.services.auth import AuthJwt

#: Identity-passing headers. Any of them present → 26004 until F050 ships
#: delegation (AC-33): silently ignoring one would make a caller believe it is
#: acting for somebody else while it is not.
IDENTITY_HEADERS: tuple[str, ...] = ("X-Bisheng-On-Behalf-Of", "X-Bisheng-End-User")

#: Where the validated credential is memoised for the duration of one request,
#: so a router-level dependency and an ``open_api_subject`` endpoint dependency
#: on the same route do not validate twice. ``scope`` is per-request by
#: construction — unlike a ContextVar, it cannot leak across requests.
_SCOPE_CACHE_KEY = "open_api_validated_credential"

#: WebSocket close code for a policy violation (RFC 6455 1008). Starlette closes
#: before ``accept()``, which uvicorn turns into a rejected handshake (AC-31).
WS_POLICY_VIOLATION = 1008


async def verify_open_api_access(conn: HTTPConnection) -> ValidatedCredential:
    """Validate the credential and enforce the endpoint's scope marker.

    Declared once per ``/api/v2`` router; never per endpoint. Returns the
    validated credential so an endpoint may depend on it directly, but its real
    product is the side effect: tenant ContextVars + ``current_open_api_principal``
    are installed by the time the endpoint body runs.
    """
    started = time.perf_counter()
    is_ws = isinstance(conn, WebSocket)
    marker: OpenApiScopeMarker | None = None
    validated: ValidatedCredential | None = None
    try:
        validated = await _authenticate(conn)
        marker = _read_marker(conn)
        _assert_scope(marker.scope, validated.principal)
        _assert_no_identity_headers(conn)
    except OpenApiAuthError as exc:
        _log_call(conn, validated, marker, outcome=exc.code, started=started)
        if is_ws:
            # pit 16 / AC-31: HTTPException here would be answered with an
            # HTTP-200 denial on a WebSocket scope. Close politely instead.
            raise WebSocketException(code=WS_POLICY_VIOLATION, reason=str(exc.code)) from exc
        raise

    _log_call(conn, validated, marker, outcome="ok", started=started)
    # ``last_used_at`` is stamped (throttled) inside ``validate_bearer`` — doing
    # it again here would double the write for no extra information.
    return validated


def open_api_subject(scope: str | None) -> Callable[..., Awaitable[UserPayload]]:
    """Build an endpoint dependency equivalent to "router dependency + this scope".

    For routers that F053 / F055 add outside the shared ``/api/v2`` router, where
    declaring the dependency once at router level is not available:
    ``login_user: UserPayload = Depends(open_api_subject("app:manage"))``.

    Unknown codes fail at import time — a typo must not degrade into "no scope
    required", which is precisely what the 26031 marker rule prevents on the
    router-level path.
    """
    if scope is not None and not is_known_scope(scope):
        raise ValueError(f"unknown open API scope {scope!r}; register it in OPEN_API_SCOPES first")

    async def _dependency(conn: HTTPConnection) -> UserPayload:
        started = time.perf_counter()
        is_ws = isinstance(conn, WebSocket)
        validated: ValidatedCredential | None = None
        try:
            validated = await _authenticate(conn)
            _assert_scope(scope, validated.principal)
            _assert_no_identity_headers(conn)
        except OpenApiAuthError as exc:
            _log_call(conn, validated, OpenApiScopeMarker(scope=scope), outcome=exc.code, started=started)
            if is_ws:
                raise WebSocketException(code=WS_POLICY_VIOLATION, reason=str(exc.code)) from exc
            raise
        _log_call(conn, validated, OpenApiScopeMarker(scope=scope), outcome="ok", started=started)
        return validated.user

    return _dependency


async def get_service_account_admin(auth_jwt: AuthJwt = Depends()) -> UserPayload:
    """Admit a super admin or the current tenant's admin to ``/api/v1/service-accounts/**``.

    ``UserPayload.get_tenant_admin_user`` is the platform's only existing
    "super admin or current-tenant admin" gate, so it is reused — but its rejection is
    ``LLMModelSharedReadonlyError`` (19801, copy: "Root-shared LLM
    server/model is read-only…"), which on this surface would show an unrelated
    LLM message. Re-raise as the generic 403 instead (AC-41 / AC-59; the
    front-end interceptor already handles envelope 403 globally).
    """
    try:
        return await UserPayload.get_tenant_admin_user(auth_jwt)
    except LLMModelSharedReadonlyError as exc:
        raise UnAuthorizedError() from exc


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


async def _authenticate(conn: HTTPConnection) -> ValidatedCredential:
    """Validate the presented credential once per request (memoised on ``conn.scope``)."""
    cached = conn.scope.get(_SCOPE_CACHE_KEY)
    if isinstance(cached, ValidatedCredential):
        return cached
    # The share-token branch for the two WS endpoints is added by T052; until
    # then every /api/v2 connection - HTTP or WS - carries a bs-sak- credential.
    validated = await validate_bearer(conn.headers.get("Authorization"))
    conn.scope[_SCOPE_CACHE_KEY] = validated
    return validated


def _read_marker(conn: HTTPConnection) -> OpenApiScopeMarker:
    """Read ``@open_api_scope`` off the matched route; missing marker → 26031."""
    marker = get_open_api_scope_marker(conn.scope.get("endpoint"))
    if marker is None:
        logger.bind(event="open_api.endpoint_unregistered").error(
            "open_api endpoint without @open_api_scope marker: {} {}",
            conn.scope.get("method", "WS"),
            conn.scope.get("path"),
        )
        raise OpenApiEndpointUnregisteredError()
    return marker


def _assert_scope(scope: str | None, principal: OpenApiPrincipal) -> None:
    """``scope=None`` means credential-only (``whoami``); otherwise the bit must be held."""
    if scope is None:
        return
    if not principal.has_scope(scope):
        raise OpenApiScopeMissingError(required=scope)


def _assert_no_identity_headers(conn: HTTPConnection) -> None:
    for header in IDENTITY_HEADERS:
        if conn.headers.get(header):
            raise OpenApiDelegationNotEnabledError()


def _log_call(
    conn: HTTPConnection,
    validated: ValidatedCredential | None,
    marker: OpenApiScopeMarker | None,
    *,
    outcome: int | str,
    started: float,
) -> None:
    """One structured ``open_api.call`` line per attempt — accepted or rejected (design D11).

    Never carries the plaintext (there is none to carry: only the credential id
    is known here). Rejections are the only signal an operator has for "an
    integration broke after a revoke", so they are logged at the same place and
    with the same fields as successes.
    """
    principal = validated.principal if validated else None
    logger.bind(event="open_api.call").info(
        "open_api.call credential_id={} subject_kind={} subject_user_id={} tenant_id={} "
        "path={} scope={} outcome={} latency_ms={}",
        principal.credential_id if principal else None,
        principal.subject_kind if principal else None,
        principal.subject_user_id if principal else None,
        validated.user.tenant_id if validated else None,
        conn.scope.get("path"),
        marker.scope if marker else None,
        outcome,
        round((time.perf_counter() - started) * 1000, 2),
    )


__all__ = [
    "IDENTITY_HEADERS",
    "get_service_account_admin",
    "open_api_subject",
    "verify_open_api_access",
]
