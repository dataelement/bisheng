"""Real HTTP statuses for v2 without changing the v1 response contract."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.open_api import OpenApiAuthError
from bisheng.common.errcode.permission import PermissionServiceUnavailableError
from bisheng.common.errcode.tenant_fga import PermissionBackendUnavailableError

OPEN_API_PATH_PREFIX = "/api/v2"


def _is_open_api_path(conn) -> bool:
    return str(conn.scope.get("path") or "").startswith(OPEN_API_PATH_PREFIX)


def _response(exc: BaseErrorCode, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=jsonable_encoder(exc.to_dict()))


def open_api_auth_exception_handler(conn, exc: OpenApiAuthError) -> JSONResponse:
    conn.scope["open_api_error_code"] = exc.code
    if conn.scope.get("type") != "http":
        raise exc
    return _response(exc, exc.http_status if _is_open_api_path(conn) else 200)


def permission_unavailable_exception_handler(conn, exc: BaseErrorCode) -> JSONResponse:
    conn.scope["open_api_error_code"] = exc.code
    if conn.scope.get("type") != "http":
        raise exc
    return _response(exc, 503 if _is_open_api_path(conn) else 200)


def register_open_api_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(OpenApiAuthError, open_api_auth_exception_handler)
    app.add_exception_handler(PermissionServiceUnavailableError, permission_unavailable_exception_handler)
    app.add_exception_handler(PermissionBackendUnavailableError, permission_unavailable_exception_handler)


__all__ = ["register_open_api_exception_handlers"]
