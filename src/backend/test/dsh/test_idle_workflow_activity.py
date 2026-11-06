"""AC-IDLE-02/03: live workflow status polling isn't admitted business input."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from bisheng.common.chat.clients.workflow_client import WorkflowClient
from bisheng.user.domain.services.auth import LoginUser
from bisheng.workflow.common.workflow import WorkflowStatus


async def test_workflow_polling_never_touches_activity_but_admitted_input_does(monkeypatch):
    client = object.__new__(WorkflowClient)
    user = client.login_user = LoginUser.model_construct(user_id=20, tenant_id=2)
    activity = user._business_activity_recorder = AsyncMock()
    client.client_id = "workflow"
    client.execution_snapshot = None
    client.check_status = AsyncMock()
    client.ensure_workflow_available = AsyncMock(return_value=True)
    client.get_execute_worker = AsyncMock(return_value="isolated-test")
    client.workflow_run = AsyncMock()
    client.send_response = AsyncMock()
    client.workflow = SimpleNamespace(
        unique_id="run",
        workflow_id="workflow",
        chat_id="chat",
        user_id=20,
        async_get_workflow_status=AsyncMock(return_value={"status": WorkflowStatus.INPUT.value}),
        async_set_user_input=AsyncMock(),
        async_set_workflow_status=AsyncMock(),
    )
    enqueue = Mock()
    monkeypatch.setattr("bisheng.common.chat.clients.workflow_client.continue_workflow.apply_async", enqueue)
    for _ in range(3):
        await client._handle_message({"action": "check_status"})
    activity.assert_not_awaited()
    await client._handle_message({"action": "input", "data": {"node": {"data": {"answer": "hi"}}}})
    activity.assert_awaited_once()
    client.workflow.async_set_user_input.assert_awaited_once()
    enqueue.assert_called_once()
    activity.reset_mock()
    client.ensure_workflow_available.return_value = False
    await client._handle_message({"action": "input", "data": {"node": {"data": {"answer": "hi"}}}})
    activity.assert_not_awaited()
