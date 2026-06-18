import asyncio
import inspect
import uuid
from contextlib import asynccontextmanager

from bisheng.mcp_manage.clients.base import BaseMcpClient
from bisheng.mcp_manage.langchain import tool as mcp_tool_module
from bisheng.workflow.callback.llm_callback import LLMNodeCallbackHandler


class DummyMcpClient(BaseMcpClient):
    @asynccontextmanager
    async def get_transport(self):
        yield None, None

    async def call_tool(self, name: str, arguments: dict):
        return {"name": name, "arguments": arguments}


def test_mcp_tool_sync_run_uses_persistent_loop_bridge(monkeypatch):
    calls = []

    def fake_run_mcp_async_task(coro_factory):
        calls.append(coro_factory)
        return asyncio.run(coro_factory())

    monkeypatch.setattr(mcp_tool_module, "run_mcp_async_task", fake_run_mcp_async_task)

    tool = mcp_tool_module.McpTool(
        name="maps_direction_driving",
        description="Directions",
        mcp_client=DummyMcpClient(),
        mcp_tool_name="maps_direction_driving",
        arg_schema={"properties": {"count": {"type": "integer"}}},
    )

    result = tool.run(count="3")

    assert result == {
        "name": "maps_direction_driving",
        "arguments": {"count": 3},
    }
    assert len(calls) == 1


def test_workflow_tool_callbacks_are_sync_and_record_tool_log():
    tool_log = []
    handler = LLMNodeCallbackHandler(
        callback=None,
        unique_id="run_1",
        node_id="agent_1",
        node_name="agent",
        output=True,
        output_key="output",
        tool_list=tool_log,
    )
    run_id = uuid.uuid4()

    assert not inspect.iscoroutinefunction(handler.on_tool_start)
    assert not inspect.iscoroutinefunction(handler.on_tool_end)
    assert not inspect.iscoroutinefunction(handler.on_tool_error)

    handler.on_tool_start({"name": "sql_agent"}, "select 1", run_id=run_id)
    assert handler.output is False
    handler.on_tool_end("ok", run_id=run_id, name="sql_agent")

    assert handler.output is True
    assert tool_log == [
        {
            "type": "start",
            "run_id": run_id.hex,
            "name": "sql_agent",
            "input": "select 1",
        },
        {
            "type": "end",
            "run_id": run_id.hex,
            "name": "sql_agent",
            "output": "ok",
        },
    ]
