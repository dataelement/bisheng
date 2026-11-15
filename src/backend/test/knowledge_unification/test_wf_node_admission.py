"""Single-node runtime admission occurs before node execution. 覆盖 AC: AC-37, AC-79, AC-83, AC-91."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.api.services import workflow as module
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from test.workflow.test_run_once_off_event_loop import _FakeToolNode


@pytest.fixture
def context(monkeypatch):
    identity = UserPayload(user_id=11, user_name="actor", tenant_id=101, user_role=[])
    node = _FakeToolNode()
    node_data = {"id": "tool", "data": {"id": "tool", "type": "tool", "name": "fetch", "description": ""}}
    factory = Mock(return_value=node)
    monkeypatch.setattr(module.FlowDao, "get_flow_by_id", Mock(return_value=SimpleNamespace(id="wf", name="wf")))
    monkeypatch.setattr(module, "require_business_action", AsyncMock())
    monkeypatch.setattr(module.NodeFactory, "instance_node", factory)
    return SimpleNamespace(identity=identity, node=node, factory=factory, node_data=node_data)


async def test_invalid_target_aborts_before_any_node_is_instantiated(context, monkeypatch):
    admission = AsyncMock(side_effect=ResourceReferenceInvalidError(reason="target_invalid"))
    monkeypatch.setattr(module, "prepare_node_preview", admission, raising=False)
    with pytest.raises(ResourceReferenceInvalidError):
        await module.WorkFlowService.run_once(context.identity, {"url": "x"}, context.node_data, "wf")
    admission.assert_awaited_once_with(context.identity, "wf", context.node_data, {"url": "x"})
    context.factory.assert_not_called()


async def test_only_admitted_node_and_input_reach_execution(context, monkeypatch):
    approved = {**context.node_data, "data": {**context.node_data["data"], "name": "admitted"}}
    admission = AsyncMock(return_value=SimpleNamespace(node_data=approved, node_input={"url": "approved"}))
    monkeypatch.setattr(module, "prepare_node_preview", admission, raising=False)
    await module.WorkFlowService.run_once(context.identity, {"url": "untrusted"}, context.node_data, "wf")
    assert context.node.seen["input"] == {"url": "approved"}
    assert context.factory.call_args.kwargs["node_data"].name == "admitted"
    assert context.factory.call_args.kwargs["user_id"] == context.identity.user_id
    admission.assert_awaited_once_with(context.identity, "wf", context.node_data, {"url": "untrusted"})
