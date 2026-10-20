"""F086: a debug run of an unsaved draft checks the subflows it adds, like saving would (R-5.1)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from bisheng.common.chat.clients import workflow_client as workflow_client_module
from bisheng.common.chat.clients.workflow_client import WorkflowClient
from bisheng.common.errcode.flow import WorkFlowSubflowNoPermissionError


def _client(monkeypatch, check_new_refs: AsyncMock):
    client = WorkflowClient.__new__(WorkflowClient)
    client.client_id = "parent"
    client.chat_id = ""
    client.login_user = "user"
    client.workflow = None
    client.run_lock = asyncio.Lock()
    sent = []

    async def send_response(category, event_type, message):
        sent.append((category, event_type, message))

    client.send_response = send_response
    client.check_status = AsyncMock(return_value=(False, "unique"))
    monkeypatch.setattr(workflow_client_module.SubflowService, "check_new_refs", check_new_refs)
    return client, sent


async def test_draft_with_a_subflow_the_user_cannot_edit_is_not_run(monkeypatch):
    error = WorkFlowSubflowNoPermissionError(subflow_name="B")
    client, sent = _client(monkeypatch, AsyncMock(side_effect=error))
    execute = MagicMock()
    monkeypatch.setattr(workflow_client_module, "execute_workflow", execute)

    await client.init_workflow({"action": "init_data", "flow_id": "other", "data": {"nodes": []}})

    client.check_status.assert_not_awaited()
    execute.apply_async.assert_not_called()
    assert client.workflow is None
    assert sent == [("error", "over", error.to_dict())]
    assert sent[0][2]["status_code"] == 10566


async def test_check_uses_the_connected_workflow_and_the_draft(monkeypatch):
    check = AsyncMock()
    client, _ = _client(monkeypatch, check)

    await client.init_workflow({"action": "init_data", "flow_id": "other", "data": {"nodes": ["draft"]}})

    # The connection's own workflow, not the flow_id in the message, decides what is already recorded.
    check.assert_awaited_once_with("user", "parent", {"nodes": ["draft"]})
    client.check_status.assert_awaited_once()
