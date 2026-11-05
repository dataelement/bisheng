"""T382: real common adapters must admit before session/Redis/queue effects."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.common.chat import manager as manager_module
from bisheng.common.chat.clients import workflow_client as module
from bisheng.common.chat.clients.workflow_client import WorkflowClient
from bisheng.common.chat.types import WorkType
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.workflow.application.execution_port import BoundWorkflowExecutionPort


@pytest.fixture
def client(monkeypatch):
    value = object.__new__(WorkflowClient)
    value.workflow = None
    value.client_id = "trusted-workflow"
    value.chat_id = "chat"
    value.user_id = 7
    value.execution_snapshot = None
    value.session_subject = None
    value.latest_history = None
    value.init_history = AsyncMock()
    value.ensure_workflow_available = AsyncMock(return_value=False)
    value.websocket = SimpleNamespace(send_json=AsyncMock(), close=AsyncMock())
    value.send_response = AsyncMock()
    value.check_status = AsyncMock(return_value=(True, "run"))
    value.get_execute_worker = AsyncMock(return_value="workflow")
    value.workflow_run = AsyncMock()
    value.execution_port = SimpleNamespace(prepare_initial=AsyncMock(return_value={"nodes": [], "edges": []}))
    redis = SimpleNamespace(async_set_workflow_data=AsyncMock(), async_set_workflow_status=AsyncMock())
    factory = Mock(return_value=redis)
    queue = Mock()
    monkeypatch.setattr(module, "RedisCallback", factory)
    monkeypatch.setattr(module, "execute_workflow", SimpleNamespace(apply_async=queue))
    monkeypatch.setattr(
        "bisheng.common.chat.clients.base.ensure_client_execution_lease", AsyncMock(return_value="held")
    )
    monkeypatch.setattr(module, "ensure_client_execution_lease", AsyncMock(return_value="held"))
    return value, factory, redis, queue


async def test_admitted_graph_is_used_and_port_precedes_session_lookup(client):
    value, factory, redis, queue = client
    raw = {"nodes": [{"data": {"id": "untrusted"}}], "edges": []}
    admitted = {"nodes": [{"data": {"id": "verified"}}], "edges": []}
    order = []

    async def prepare(**kwargs):
        order.append("admit")
        assert kwargs["claimed_flow_id"] == value.client_id
        assert kwargs["graph"] is raw and kwargs["version_hint"] == 3
        return admitted

    async def status(message, **kwargs):
        order.append("session")
        assert message["flow_id"] == value.client_id
        return True, "run"

    value.execution_port.prepare_initial.side_effect = prepare
    value.check_status.side_effect = status
    await value.init_workflow({"data": raw, "chat_id": "chat", "version_id": 3})
    assert order[:2] == ["admit", "session"]
    redis.async_set_workflow_data.assert_awaited_once_with(admitted)
    assert queue.call_args.args[0][1] == value.client_id
    factory.assert_called_once()


@pytest.mark.parametrize(
    "error", [ReferenceCoverageNotReadyError(), ResourceReferenceInvalidError(), KnowledgeOperationPlanConflictError()]
)
async def test_business_rejection_keeps_code_and_has_zero_execution_effects(client, error):
    value, factory, redis, queue = client
    value.execution_port.prepare_initial.side_effect = error
    await value.init_workflow({"flow_id": value.client_id, "data": {"nodes": [], "edges": []}})
    value.check_status.assert_not_awaited()
    factory.assert_not_called()
    redis.async_set_workflow_data.assert_not_awaited()
    queue.assert_not_called()
    frame = value.websocket.send_json.await_args.args[0]
    assert frame["message"]["status_code"] == error.Code
    value.websocket.close.assert_not_awaited()


async def test_bound_root_rejection_precedes_every_common_side_effect(client):
    value, factory, _, queue = client
    user = UserPayload(user_id=7, user_name="u", tenant_id=101, user_role=[])
    value.execution_port = BoundWorkflowExecutionPort(value.client_id, user)
    await value.init_workflow({"flow_id": "another-workflow", "data": {"nodes": [], "edges": []}})
    value.check_status.assert_not_awaited()
    factory.assert_not_called()
    queue.assert_not_called()
    assert value.websocket.send_json.await_args.args[0]["message"]["status_code"] == 10996


async def test_missing_port_is_not_a_legacy_execution_fallback(client):
    value, factory, _, queue = client
    value.execution_port = None
    await value.init_workflow({"data": {"nodes": [], "edges": []}})
    value.check_status.assert_not_awaited()
    factory.assert_not_called()
    queue.assert_not_called()
    assert value.websocket.send_json.await_args.args[0]["message"]["status_code"] == 10994


async def test_status_action_cannot_pivot_the_endpoint_bound_root(client):
    value, factory, _, queue = client
    await value._handle_message({"action": "check_status", "flow_id": "another-workflow", "chat_id": "other-chat"})
    value.check_status.assert_not_awaited()
    factory.assert_not_called()
    queue.assert_not_called()
    assert value.chat_id == "chat" and value.workflow is None
    assert value.websocket.send_json.await_args.args[0]["message"]["status_code"] == 10996


async def test_direct_status_check_rejects_root_claim_before_mutating_client(client):
    value, factory, _, _ = client
    with pytest.raises(ResourceReferenceInvalidError):
        await WorkflowClient.check_status(value, {"flow_id": "another-workflow", "chat_id": "other-chat"})
    assert value.chat_id == "chat" and value.workflow is None
    factory.assert_not_called()


async def test_real_manager_forwards_exact_port_to_workflow_client(monkeypatch):
    class ReachedAccept(Exception):
        pass

    manager = object.__new__(manager_module.ChatManager)
    manager.accept_client = AsyncMock(side_effect=ReachedAccept)
    constructor = Mock(return_value=object())
    monkeypatch.setattr(manager_module, "WorkflowClient", constructor)
    identity = UserPayload(user_id=7, user_name="u", tenant_id=101, user_role=[])
    port = BoundWorkflowExecutionPort("w", identity, allow_preview=False)
    websocket = SimpleNamespace()
    with pytest.raises(ReachedAccept):
        await manager.dispatch_client(
            websocket,
            "w",
            "chat",
            identity,
            WorkType.WORKFLOW,
            websocket,
            workflow_execution_port=port,
            execution_snapshot={"channel": "public_v3"},
        )
    assert constructor.call_args.kwargs["workflow_execution_port"] is port
    assert constructor.call_args.args[5] is identity
    assert constructor.call_args.kwargs["execution_snapshot"] == {"channel": "public_v3"}
