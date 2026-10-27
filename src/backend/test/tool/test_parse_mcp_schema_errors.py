"""MCP schema connect failures must surface as a connection error, not an unhandled 500."""

import pytest

from bisheng.common.errcode.tool import ToolMcpRequestError
from bisheng.tool.domain.services import tool as tool_mod
from bisheng.tool.domain.services.tool import ToolServices, _flatten_mcp_error


def test_flatten_mcp_error_unwraps_exception_group():
    grouped = ExceptionGroup("unhandled errors in a TaskGroup", [Exception("Connection closed")])
    assert _flatten_mcp_error(grouped) == "Connection closed"


@pytest.mark.asyncio
async def test_parse_mcp_schema_maps_exception_group_to_tool_error(monkeypatch):
    async def _boom(_payload):
        raise ExceptionGroup("unhandled errors in a TaskGroup", [Exception("Connection closed")])

    monkeypatch.setattr(tool_mod.ClientManager, "connect_mcp_from_json", _boom)

    with pytest.raises(ToolMcpRequestError) as exc_info:
        await ToolServices.parse_mcp_schema(
            '{"mcpServers":{"remote-tool":{"type":"sse","url":"http://127.0.0.1:9/sse"}}}'
        )
    assert exc_info.value.code == 15032
    assert "Connection closed" not in str(exc_info.value)
