"""Classify MCP failures without exposing endpoint credentials or server responses."""

import httpx
from httpx_sse import SSEError

from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.tool import (
    ToolMcpAuthError,
    ToolMcpConnectionError,
    ToolMcpNotFoundError,
    ToolMcpProtocolError,
    ToolMcpRequestError,
    ToolMcpTimeoutError,
    ToolMcpUrlError,
)


def mcp_error_code(error: BaseException) -> type[BaseErrorCode]:
    nested = getattr(error, "exceptions", ())
    for child in nested:
        code = mcp_error_code(child)
        if code is not ToolMcpRequestError:
            return code
    if isinstance(error, BaseErrorCode):
        return type(error)
    if isinstance(error, httpx.TimeoutException):
        return ToolMcpTimeoutError
    if isinstance(error, httpx.ConnectError):
        return ToolMcpConnectionError
    if isinstance(error, (httpx.UnsupportedProtocol, httpx.InvalidURL)):
        return ToolMcpUrlError
    if isinstance(error, SSEError):
        return ToolMcpProtocolError
    if isinstance(error, httpx.HTTPStatusError):
        if error.response.status_code in (401, 403):
            return ToolMcpAuthError
        if error.response.status_code == 404:
            return ToolMcpNotFoundError
    return ToolMcpRequestError
