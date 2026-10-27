from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from httpx_sse import SSEError

from bisheng.tool.domain.services.mcp_errors import mcp_error_code


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (httpx.ConnectError("secret endpoint"), 15026),
        (httpx.ReadTimeout("secret endpoint"), 15027),
        (SSEError("wrong content type"), 15030),
        (httpx.UnsupportedProtocol("secret endpoint"), 15031),
        (Exception("secret token"), 15032),
    ],
)
def test_nested_transport_errors_have_safe_business_codes(error, code):
    assert mcp_error_code(ExceptionGroup("task group", [error])).Code == code


@pytest.mark.parametrize(("status", "code"), [(401, 15028), (403, 15028), (404, 15029), (500, 15032)])
def test_http_errors_have_specific_business_codes(status, code):
    response = httpx.Response(status, request=httpx.Request("GET", "https://example.com?key=secret"))
    error = httpx.HTTPStatusError("secret", request=response.request, response=response)
    assert mcp_error_code(error).Code == code


async def test_refresh_reports_each_failure_and_continues(monkeypatch):
    from bisheng.tool.domain.services import tool as module

    monkeypatch.setattr(
        module.GptsToolsDao,
        "aget_user_tool_type",
        AsyncMock(
            return_value=[
                SimpleNamespace(id=1, name="Offline"),
                SimpleNamespace(id=2, name="Working"),
            ]
        ),
    )
    monkeypatch.setattr(module.GptsToolsDao, "aget_list_by_type", AsyncMock(return_value=[]))
    monkeypatch.setattr(module, "require_business_action", AsyncMock())
    service = SimpleNamespace(
        login_user=SimpleNamespace(user_id=1),
        refresh_mcp_tools=AsyncMock(
            side_effect=[ExceptionGroup("transport", [httpx.ConnectError("secret")]), None],
        ),
    )
    assert await module.ToolServices.refresh_all_mcp(service) == [{"name": "Offline", "code": 15026}]
    assert service.refresh_mcp_tools.await_count == 2
