"""STDIO MCP is frozen off: create and execute both raise 15025, no process spawn."""

from types import SimpleNamespace

import pytest

from bisheng.common.errcode.tool import ToolMcpStdioError
from bisheng.core.config.settings import McpConf
from bisheng.mcp_manage.clients.sse import SseClient
from bisheng.mcp_manage.clients.streamable import StreamableClient
from bisheng.mcp_manage.constant import McpClientType
from bisheng.mcp_manage.manager import ClientManager
from bisheng.tool.domain.services import tool as tool_mod
from bisheng.tool.domain.services.executor import ToolExecutor
from bisheng.tool.domain.services.tool import ToolServices

_COMMAND_SCHEMA = '{"mcpServers":{"local-tool":{"command":"python","args":["tool_server.py"]}}}'
_TYPED_STDIO_SCHEMA = '{"mcpServers":{"local-tool":{"type":"stdio","command":"python"}}}'
_SSE_SCHEMA = '{"mcpServers":{"remote":{"type":"sse","url":"http://127.0.0.1:9/sse"}}}'
_STREAMABLE_SCHEMA = '{"mcpServers":{"remote":{"type":"streamable","url":"http://127.0.0.1:9/mcp"}}}'


def test_mcp_conf_enable_stdio_stays_false():
    assert McpConf().enable_stdio is False
    assert McpConf(enable_stdio=True).enable_stdio is False


def test_connect_from_command_raises_without_stdio_client():
    with pytest.raises(ToolMcpStdioError) as exc_info:
        ClientManager.sync_connect_mcp_from_json(_COMMAND_SCHEMA)
    assert exc_info.value.Code == 15025


def test_connect_from_type_stdio_raises():
    with pytest.raises(ToolMcpStdioError):
        ClientManager.sync_connect_mcp_from_json(_TYPED_STDIO_SCHEMA)


def test_connect_stdio_type_directly_raises():
    with pytest.raises(ToolMcpStdioError):
        ClientManager.sync_connect_mcp(McpClientType.STDIO.value, command="python")


def test_sse_and_streamable_still_construct():
    sse = ClientManager.sync_connect_mcp_from_json(_SSE_SCHEMA)
    streamable = ClientManager.sync_connect_mcp_from_json(_STREAMABLE_SCHEMA)
    assert isinstance(sse, SseClient)
    assert isinstance(streamable, StreamableClient)


@pytest.mark.asyncio
async def test_parse_mcp_schema_rejects_stdio_before_connect(monkeypatch):
    async def _should_not_run(_payload):
        raise AssertionError("connect_mcp_from_json must not run for STDIO")

    monkeypatch.setattr(tool_mod.ClientManager, "connect_mcp_from_json", _should_not_run)

    with pytest.raises(ToolMcpStdioError) as exc_info:
        await ToolServices.parse_mcp_schema(_COMMAND_SCHEMA)
    assert exc_info.value.Code == 15025


def test_init_mcp_tool_rejects_saved_stdio_schema():
    tool = SimpleNamespace(tool_key="k", desc="d", name="n", extra='{"inputSchema":{}}')
    tool_type = SimpleNamespace(openapi_schema=_COMMAND_SCHEMA)
    with pytest.raises(ToolMcpStdioError):
        ToolExecutor._init_mcp_tool(tool, tool_type)
