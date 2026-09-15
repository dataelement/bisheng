"""Real HTTP statuses for v2 without changing the v1 response contract."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette._utils import is_async_callable
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.common.errcode.open_api import (
    OpenApiAsyncUnsupportedError,
    OpenApiAuthError,
    OpenApiTaskModeUnsupportedError,
)
from bisheng.common.errcode.permission import (
    AuthorizationModelMismatchError,
    PermissionCheckFailedError,
    PermissionDeniedError,
    PermissionEnumerationIncompleteError,
    PermissionInvalidResourceError,
    PermissionProjectionFailedError,
    PermissionPublishNotReadyError,
    PermissionServiceUnavailableError,
)
from bisheng.common.errcode.tenant_fga import PermissionBackendUnavailableError

OPEN_API_PATH_PREFIX = "/api/v2"


def _is_open_api_path(conn) -> bool:
    path = str(conn.scope.get("path") or "")
    return path == OPEN_API_PATH_PREFIX or path.startswith(OPEN_API_PATH_PREFIX + "/")


def _response(exc: BaseErrorCode, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=jsonable_encoder(exc.to_dict()))


def open_api_http_status(exc: BaseErrorCode | StarletteHTTPException) -> int:
    """Map a v2 business error to its transport status without changing its code."""

    if isinstance(exc, StarletteHTTPException):
        error_type = getattr(exc, "error_code_class", type(exc))
        code = exc.status_code
    else:
        error_type = type(exc)
        code = exc.code
    if issubclass(error_type, OpenApiAuthError):
        return getattr(exc, "http_status", error_type.http_status)
    if issubclass(
        error_type,
        (
            PermissionServiceUnavailableError,
            PermissionBackendUnavailableError,
            PermissionCheckFailedError,
            PermissionEnumerationIncompleteError,
            PermissionProjectionFailedError,
            PermissionPublishNotReadyError,
            AuthorizationModelMismatchError,
        ),
    ):
        return 503
    if issubclass(error_type, (UnAuthorizedError, PermissionDeniedError, SpacePermissionDeniedError)):
        return 403
    if issubclass(error_type, (NotFoundError, PermissionInvalidResourceError)):
        return 404
    if error_type.__name__.endswith("NotFoundError") or "NotExist" in error_type.__name__:
        return 404
    if 400 <= code <= 599:
        return int(code)
    return 400


def mark_open_api_error(conn, exc: BaseErrorCode) -> None:
    if _is_open_api_path(conn):
        conn.scope["open_api_error_code"] = exc.code


async def open_api_auth_exception_handler(conn, exc: OpenApiAuthError) -> JSONResponse:
    mark_open_api_error(conn, exc)
    if conn.scope.get("type") != "http":
        raise exc
    return _response(exc, exc.http_status if _is_open_api_path(conn) else 200)


async def permission_unavailable_exception_handler(conn, exc: BaseErrorCode) -> JSONResponse:
    mark_open_api_error(conn, exc)
    if conn.scope.get("type") != "http":
        raise exc
    return _response(exc, 503 if _is_open_api_path(conn) else 200)


def register_open_api_exception_handlers(app: FastAPI) -> None:
    _register_v2_handler(app, BaseErrorCode, open_api_business_exception_handler)
    _register_v2_handler(app, HTTPException, open_api_http_exception_handler)
    _register_v2_handler(app, StarletteHTTPException, open_api_http_exception_handler)
    _register_v2_handler(app, RequestValidationError, open_api_validation_exception_handler)
    app.add_exception_handler(OpenApiAuthError, open_api_auth_exception_handler)
    app.add_exception_handler(PermissionServiceUnavailableError, permission_unavailable_exception_handler)
    app.add_exception_handler(PermissionBackendUnavailableError, permission_unavailable_exception_handler)


def _register_v2_handler(app: FastAPI, error_type: type[Exception], handler) -> None:
    previous = app.exception_handlers.get(error_type)
    if previous is None and error_type is HTTPException:
        previous = app.exception_handlers.get(StarletteHTTPException)

    async def dispatch(conn, exc):
        if _is_open_api_path(conn):
            return await handler(conn, exc)
        if previous is not None:
            if is_async_callable(previous):
                return await previous(conn, exc)
            return await run_in_threadpool(previous, conn, exc)
        if isinstance(exc, BaseErrorCode):
            return _response(exc, 200)
        raise exc

    app.add_exception_handler(error_type, dispatch)


async def open_api_business_exception_handler(conn, exc: BaseErrorCode) -> JSONResponse:
    mark_open_api_error(conn, exc)
    return _response(exc, open_api_http_status(exc))


async def _authenticate_parse_failure(request: Request) -> JSONResponse | None:
    """FastAPI parses JSON/forms before dependencies; auth still takes priority."""

    if request.scope.get("open_api_principal") is not None or request.scope.get("endpoint") is None:
        return None
    from bisheng.open_api.api.dependencies import open_api_access_context

    try:
        # The parser already consumed the body and the exception handler has a
        # different Request instance. Never attempt to read that stream again.
        async with open_api_access_context(request, inspect_body=False):
            pass
    except OpenApiAuthError as exc:
        return await open_api_auth_exception_handler(request, exc)
    return None


async def open_api_http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    auth_response = await _authenticate_parse_failure(request)
    if auth_response is not None:
        return auth_response
    request.scope["open_api_error_code"] = exc.status_code
    detail = exc.detail.get("error", exc.detail) if isinstance(exc.detail, dict) else exc.detail
    return JSONResponse(
        status_code=open_api_http_status(exc),
        content=jsonable_encoder({"status_code": exc.status_code, "status_message": detail}),
        headers=exc.headers,
    )


async def open_api_validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    auth_response = await _authenticate_parse_failure(request)
    if auth_response is not None:
        return auth_response
    # These are daily-chat capabilities, not global v2 field names. Other
    # endpoints may use the same names inside their own business payloads.
    if request.url.path.rstrip("/") == "/api/v2/workstation/chat/completions":
        body = exc.body if isinstance(exc.body, dict) else {}
        if body.get("task_mode") is True or ("run_mode" in body and body["run_mode"] != "daily"):
            return await open_api_auth_exception_handler(request, OpenApiTaskModeUnsupportedError())
        if body.get("execution") not in (None, "sync") or body.get("background") is True:
            return await open_api_auth_exception_handler(request, OpenApiAsyncUnsupportedError())
    request.scope["open_api_error_code"] = 400
    return JSONResponse(
        status_code=400,
        content=jsonable_encoder(
            {"status_code": 400, "status_message": exc.errors()},
            custom_encoder={ValueError: str},
        ),
    )


__all__ = ["mark_open_api_error", "open_api_http_status", "register_open_api_exception_handlers"]
