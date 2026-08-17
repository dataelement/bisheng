"""Dedicated ``/api/v2`` exception handlers (F049 design D2 / K4).

The platform flattens **every** error to HTTP 200 + envelope
(``main.handle_http_exception``). That is a deliberate front-end contract and it
stays untouched — but it makes ``/api/v2`` unusable as an open API: an SDK that
branches on ``response.status_code`` sees 200 for "no credential", and a retry
policy cannot tell "revoked key" from "authorization service down".

So the open face gets its own handlers, and only there:

* on ``/api/v2`` the real status travels in the HTTP status line
  (``OpenApiAuthError.http_status``: 401 / 403 / 404 / 500 / 503), while the
  **body keeps the platform envelope** — clients already parsing
  ``{status_code, status_message, data}`` keep working;
* on every other path the exception behaves exactly as before (HTTP 200 +
  envelope), because these same error classes also surface on the ``/api/v1``
  management endpoints, where the front end reads the envelope code (AC-59).

``PermissionServiceUnavailableError`` (19002) / ``PermissionBackendUnavailableError``
(19201) get the same treatment: on ``/api/v2`` an authorization-engine outage
must be a 503 and never a partially filtered result set (AC-34 / iron rule 3).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from loguru import logger

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.open_api import OpenApiAuthError
from bisheng.common.errcode.permission import PermissionServiceUnavailableError
from bisheng.common.errcode.tenant_fga import PermissionBackendUnavailableError

OPEN_API_PATH_PREFIX = "/api/v2"

#: Errors that mean "the authorization engine could not answer". They are raised
#: deep inside F048 and would otherwise reach the client as HTTP 200.
_SERVICE_UNAVAILABLE_HTTP_STATUS = 503


def _is_open_api_path(conn) -> bool:
    return str(conn.scope.get("path") or "").startswith(OPEN_API_PATH_PREFIX)


def _envelope(exc: BaseErrorCode, http_status: int) -> JSONResponse:
    return JSONResponse(status_code=http_status, content=jsonable_encoder(exc.to_dict()))


def open_api_auth_exception_handler(conn, exc: OpenApiAuthError) -> JSONResponse:
    """260xx family: real HTTP status on ``/api/v2``, platform envelope elsewhere."""
    if conn.scope.get("type") != "http":
        # WebSocket rejections are turned into ``WebSocketException(1008)`` by
        # the router dependency (pit 16); anything else on a WS scope is a bug
        # we must not hide behind a JSON response the client cannot receive.
        raise exc
    logger.error("{} {} {!s}", conn.scope.get("method"), conn.scope.get("path"), exc)
    if _is_open_api_path(conn):
        return _envelope(exc, exc.http_status)
    return _envelope(exc, 200)


def permission_unavailable_exception_handler(conn, exc: BaseErrorCode) -> JSONResponse:
    """19002 / 19201: 503 on ``/api/v2``; unchanged (HTTP 200 + envelope) everywhere else."""
    if conn.scope.get("type") != "http":
        raise exc
    logger.error("{} {} {!s}", conn.scope.get("method"), conn.scope.get("path"), exc)
    if _is_open_api_path(conn):
        return _envelope(exc, _SERVICE_UNAVAILABLE_HTTP_STATUS)
    return _envelope(exc, 200)


def register_open_api_exception_handlers(app: FastAPI) -> None:
    """Install the ``/api/v2`` handlers. Called from ``main.create_app`` only."""
    app.add_exception_handler(OpenApiAuthError, open_api_auth_exception_handler)
    app.add_exception_handler(PermissionServiceUnavailableError, permission_unavailable_exception_handler)
    app.add_exception_handler(PermissionBackendUnavailableError, permission_unavailable_exception_handler)


__all__ = [
    "open_api_auth_exception_handler",
    "permission_unavailable_exception_handler",
    "register_open_api_exception_handlers",
]
