"""Single-node debug runs execute the sync node off the request's event loop.

A tool node builds its tool through run_async_safe, which refuses to run on a
running event loop. run_once used to call the node inline from the async
endpoint, so every tool node's debug run failed with that error.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bisheng.api.services import workflow as workflow_service
from bisheng.api.services.workflow import WorkFlowService
from bisheng.core.context.tenant import current_tenant_id, get_current_tenant_id


class _FakeToolNode:
    def __init__(self) -> None:
        self.seen: dict = {}

    def handle_input(self, user_input: dict) -> None:
        self.seen["input"] = user_input

    def _run(self, exec_id: str) -> dict:
        try:
            asyncio.get_running_loop()
            self.seen["on_loop"] = True
        except RuntimeError:
            self.seen["on_loop"] = False
        self.seen["tenant"] = get_current_tenant_id()
        return {"output": "page"}

    def parse_log(self, exec_id: str, result: dict) -> list:
        return [[{"key": "output", "value": result["output"], "type": "variable"}]]


async def test_a_tool_node_runs_in_a_worker_thread_with_the_request_context():
    node = _FakeToolNode()
    token = current_tenant_id.set(7)
    try:
        with (
            patch.object(
                workflow_service.FlowDao,
                "get_flow_by_id",
                return_value=SimpleNamespace(id="w1", name="wf", tenant_id=1),
            ),
            patch.object(workflow_service, "require_business_action", AsyncMock()),
            patch.object(workflow_service.NodeFactory, "instance_node", return_value=node),
        ):
            result = await WorkFlowService.run_once(
                SimpleNamespace(user_id=1),
                {"url": "https://example.com"},
                {"id": "tool_1", "data": {"id": "tool_1", "type": "tool", "name": "web_fetch", "description": ""}},
                "w1",
            )
    finally:
        current_tenant_id.reset(token)

    assert node.seen == {"input": {"url": "https://example.com"}, "on_loop": False, "tenant": 7}
    assert result == [[{"key": "output", "value": "page", "type": "variable"}]]
