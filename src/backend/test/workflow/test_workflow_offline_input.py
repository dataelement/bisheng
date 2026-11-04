from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.common.chat.clients import workflow_client as module
from bisheng.database.models.flow import FlowStatus
from bisheng.workflow.common.workflow import WorkflowStatus
from test.workflow.test_workflow_auto_rerun_status import FakeRedisCallback, make_client


@pytest.mark.parametrize("runtime_exists", [True, False])
@pytest.mark.parametrize("deleted", [True, False])
async def test_stale_card_checks_current_publication_before_dispatch(monkeypatch, runtime_exists, deleted):
    callback = FakeRedisCallback(final_status=WorkflowStatus.INPUT.value)
    client, sent = make_client(monkeypatch, callback, online=False)
    client.workflow = callback if runtime_exists else None
    client.websocket = SimpleNamespace(send_json=AsyncMock())
    if deleted:
        monkeypatch.setattr(module.FlowDao, "get_flow_by_id", lambda _: None)
    resume = Mock()
    monkeypatch.setattr(module.continue_workflow, "apply_async", resume)

    await client._handle_message({"action": "input", "data": {"input_1": {"data": {"text": "stale"}}}})

    assert client.websocket.send_json.call_args.args[0]["message"]["status_code"] == 13010
    assert sent == [{"category": "processing", "type": "close", "message": ""}]
    assert client.workflow is None
    assert callback.stopped is runtime_exists
    assert callback.cleared is False
    resume.assert_not_called()


async def test_same_connection_rechecks_status_for_each_card(monkeypatch):
    callback = FakeRedisCallback(final_status=WorkflowStatus.INPUT.value)
    callback.unique_id, callback.workflow_id, callback.chat_id, callback.user_id = "run", "flow-1", "chat-1", 1
    callback.async_set_user_input = AsyncMock()
    callback.async_set_workflow_status = AsyncMock()
    client, _ = make_client(monkeypatch, callback)
    client.workflow = callback
    client.websocket = SimpleNamespace(send_json=AsyncMock())
    client.get_execute_worker = AsyncMock(return_value="worker")
    client.workflow_run = AsyncMock()
    resume = Mock()
    monkeypatch.setattr(module.continue_workflow, "apply_async", resume)
    payload = {"action": "input", "data": {"input_1": {"data": {"text": "value"}}}}

    await client._handle_message(payload)
    assert resume.call_count == 1
    monkeypatch.setattr(module.FlowDao, "get_flow_by_id", lambda _: SimpleNamespace(status=FlowStatus.OFFLINE.value))
    await client._handle_message(payload)

    assert resume.call_count == 1
    assert callback.async_set_user_input.await_count == 1
    assert client.websocket.send_json.call_args.args[0]["message"]["status_code"] == 13010


async def test_builder_preview_keeps_draft_execution(monkeypatch):
    client, _ = make_client(monkeypatch, FakeRedisCallback(), online=False)
    client.chat_id = ""
    should_start, _ = await client.check_status({"flow_id": "flow-1", "chat_id": ""}, is_init=True)
    assert should_start is True


@pytest.mark.parametrize("runtime_exists", [True, False])
async def test_expired_runtime_settles_stale_card(monkeypatch, runtime_exists):
    callback = FakeRedisCallback()
    client, sent = make_client(monkeypatch, callback)
    client.workflow = callback if runtime_exists else None
    await client.handle_user_input({})
    assert sent == [{"category": "processing", "type": "close", "message": ""}]
