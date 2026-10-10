"""MCP-compliant success and tool-error result encoding."""

from __future__ import annotations

import json

from fastapi import HTTPException
from mcp import types
from pydantic import BaseModel, ConfigDict, ValidationError

from bisheng.common.errcode import BaseErrorCode
from bisheng.open_mcp.upload import McpUploadError


class McpErrorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: int | str
    message: str


_HTTP_ERROR_CODES = {
    400: "INVALID_ARGUMENT",
    401: "UNAUTHENTICATED",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    409: "CONFLICT",
    429: "RATE_LIMITED",
    500: "TOOL_EXECUTION_FAILED",
    502: "DEPENDENCY_UNAVAILABLE",
    503: "DEPENDENCY_UNAVAILABLE",
    504: "DEPENDENCY_UNAVAILABLE",
}


def success_result(data: BaseModel | dict) -> types.CallToolResult:
    payload = data.model_dump(mode="json", by_alias=True) if isinstance(data, BaseModel) else data
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        structuredContent=payload,
        isError=False,
    )


def error_result(code: int | str, message: str) -> types.CallToolResult:
    safe_message = message.strip() or "Tool execution failed"
    payload = {"error": McpErrorPayload(code=code, message=safe_message).model_dump(mode="json")}
    return types.CallToolResult(
        content=[
            types.TextContent(
                type="text",
                text=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            )
        ],
        isError=True,
    )


def error_result_from_exception(exc: Exception) -> types.CallToolResult:
    if isinstance(exc, McpUploadError):
        return error_result(exc.code, str(exc))
    if isinstance(exc, BaseErrorCode):
        return error_result(exc.code, exc.message)
    if isinstance(exc, ValidationError):
        first = exc.errors(include_url=False)[0]
        location = ".".join(str(item) for item in first.get("loc", ()))
        message = first.get("msg", "Invalid tool arguments")
        return error_result("INVALID_ARGUMENT", f"{location}: {message}" if location else message)
    if isinstance(exc, HTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            message = str(detail.get("error") or detail.get("message") or "Request rejected")
        else:
            message = str(detail)
        code = (
            exc.status_code
            if exc.status_code > 599
            else _HTTP_ERROR_CODES.get(exc.status_code, "TOOL_EXECUTION_FAILED")
        )
        return error_result(code, message)
    return error_result("TOOL_EXECUTION_FAILED", "Tool execution failed")


__all__ = ["McpErrorPayload", "error_result", "error_result_from_exception", "success_result"]
