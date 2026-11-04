"""MCP schema connect failures must surface as a connection error, not an unhandled 500."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.tool import ToolMcpRequestError, ToolMcpTimeoutError
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


SCHEMA = '{"mcpServers":{"remote":{"type":"streamable","url":"http://127.0.0.1:9/mcp"}}}'


@pytest.mark.parametrize("stage", ["connect", "list_tools"])
async def test_schema_discovery_times_out_and_cleans_up_stalled_work(monkeypatch, stage):
    monkeypatch.setattr(tool_mod, "_MCP_SCHEMA_TIMEOUT_SECONDS", 0.01, raising=False)
    cleaned = asyncio.Event()

    async def stalled(*_args):
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    client = AsyncMock()
    client.list_tools.side_effect = stalled
    connect = stalled if stage == "connect" else AsyncMock(return_value=client)
    monkeypatch.setattr(tool_mod.ClientManager, "connect_mcp_from_json", connect)
    with pytest.raises(ToolMcpTimeoutError) as exc_info:
        await asyncio.wait_for(ToolServices.parse_mcp_schema(SCHEMA), timeout=0.2)
    assert exc_info.value.code == 15027
    assert cleaned.is_set()


async def test_schema_discovery_returns_tools_before_deadline(monkeypatch):
    client = AsyncMock()
    client.list_tools.return_value = []
    monkeypatch.setattr(tool_mod.ClientManager, "connect_mcp_from_json", AsyncMock(return_value=client))
    result = await ToolServices.parse_mcp_schema(SCHEMA)
    assert result.children == []
    client.list_tools.assert_awaited_once()


async def test_schema_discovery_preserves_external_cancellation(monkeypatch):
    entered = asyncio.Event()

    async def stalled(_payload):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(tool_mod.ClientManager, "connect_mcp_from_json", stalled)
    task = asyncio.create_task(ToolServices.parse_mcp_schema(SCHEMA))
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
