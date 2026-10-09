"""Transport status and OpenAI-style error shapes for v2 business errors."""

from __future__ import annotations

from starlette.exceptions import HTTPException as StarletteHTTPException

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.common.errcode.open_api import OpenApiAuthError
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


_OPENAI_ERROR_TYPES = {
    401: "authentication_error",
    403: "permission_error",
    404: "not_found_error",
    429: "rate_limit_error",
}


def openai_stream_error(exc: BaseException) -> dict:
    """Build the OpenAI streaming error body: {"error": {message, type, code}}.

    Business errors keep their business code and use the type that matches
    their v2 HTTP status. Other errors are server errors without a code.
    """

    if isinstance(exc, BaseErrorCode):
        status = open_api_http_status(exc)
        if status >= 500:
            error_type = "server_error"
        else:
            error_type = _OPENAI_ERROR_TYPES.get(status, "invalid_request_error")
        return {"error": {"message": exc.message, "type": error_type, "code": exc.code}}
    message = str(exc) or "The assistant failed to generate a response"
    return {"error": {"message": message, "type": "server_error", "code": None}}


__all__ = ["open_api_http_status", "openai_stream_error"]
