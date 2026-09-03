import asyncio
from types import SimpleNamespace

import pytest

from bisheng.common.chat.clients import workflow_client as workflow_client_module
from bisheng.common.chat.clients.workflow_client import WorkflowClient
from bisheng.database.models.flow import FlowStatus
from bisheng.workflow.common.workflow import WorkflowStatus


class FakeRedisCallback:
    def __init__(self, initial_status=None, final_status=None, events=None):
        self.initial_status = initial_status
        self.final_status = final_status
        self.events = events or []
        self.cleared = False
        self.stopped = False

    def get_workflow_status(self):
        if self.initial_status is None:
            return None
        return {"status": self.initial_status}

    async def async_get_workflow_status(self):
        if self.final_status is None:
            return None
        return {"status": self.final_status}

    async def get_response_until_break(self):
        for event in self.events:
            yield event

    async def async_clear_workflow_status(self):
        self.cleared = True

    def set_workflow_stop(self):
        self.stopped = True

    def clear_workflow_status(self):
        self.cleared = True


def make_client(monkeypatch, callback, *, has_history=True, online=True):
    client = WorkflowClient.__new__(WorkflowClient)
    client.client_id = "flow-1"
    client.chat_id = "chat-1"
    client.user_id = 1
    client.latest_history = SimpleNamespace(category="other") if has_history else None
    client.workflow = None
    client.hash_key = None
    client.websocket = object()
    client.run_lock = asyncio.Lock()

    async def init_history():
        return None

    sent = []

    async def send_response(category, event_type, message):
        sent.append({"category": category, "type": event_type, "message": message})

    async def send_json(message):
        sent.append(message)

    client.init_history = init_history
    client.send_response = send_response
    client.send_json = send_json

    monkeypatch.setattr(workflow_client_module, "RedisCallback", lambda *_args: callback)
    monkeypatch.setattr(
        workflow_client_module.FlowDao,
        "get_flow_by_id",
        lambda _flow_id: SimpleNamespace(status=FlowStatus.ONLINE.value if online else FlowStatus.OFFLINE.value),
    )
    monkeypatch.setattr(workflow_client_module, "generate_uuid", lambda: "generated-id")
    return client, sent


def finished_status_marker():
    return {"event": "workflow_status_checked", "status": "finished"}


@pytest.mark.asyncio
async def test_historical_conversation_without_runtime_status_is_marked_finished(monkeypatch):
    client, sent = make_client(monkeypatch, FakeRedisCallback())

    should_start, _ = await client.check_status({"flow_id": "flow-1", "chat_id": "chat-1"})

    assert should_start is True
    assert sent == [{"category": "processing", "type": "close", "message": finished_status_marker()}]


@pytest.mark.asyncio
async def test_new_conversation_check_does_not_emit_historical_finished_marker(monkeypatch):
    client, sent = make_client(monkeypatch, FakeRedisCallback(), has_history=False)

    should_start, _ = await client.check_status(
        {"flow_id": "flow-1", "chat_id": "chat-1"},
        is_init=True,
    )

    assert should_start is True
    assert sent == []


@pytest.mark.parametrize("status", [WorkflowStatus.SUCCESS.value, WorkflowStatus.FAILED.value])
@pytest.mark.asyncio
async def test_status_already_terminal_drains_events_then_marks_finished(monkeypatch, status):
    pending_event = {"category": "error", "type": "over", "message": {"status_code": 500}}
    callback = FakeRedisCallback(initial_status=status, final_status=status, events=[pending_event])
    client, sent = make_client(monkeypatch, callback)

    await client.check_status({"flow_id": "flow-1", "chat_id": "chat-1"})

    assert sent == [
        pending_event,
        {"category": "processing", "type": "close", "message": finished_status_marker()},
    ]
    assert callback.cleared is True
    assert client.workflow is None


@pytest.mark.parametrize(
    ("initial_status", "final_status"),
    [
        (WorkflowStatus.RUNNING.value, WorkflowStatus.SUCCESS.value),
        (WorkflowStatus.WAITING.value, WorkflowStatus.WAITING.value),
        (WorkflowStatus.INPUT.value, WorkflowStatus.INPUT.value),
    ],
)
@pytest.mark.asyncio
async def test_nonterminal_status_at_open_never_emits_finished_marker(
    monkeypatch,
    initial_status,
    final_status,
):
    callback = FakeRedisCallback(initial_status=initial_status, final_status=final_status)
    client, sent = make_client(monkeypatch, callback)

    await client.check_status({"flow_id": "flow-1", "chat_id": "chat-1"})

    close_messages = [item["message"] for item in sent if item.get("type") == "close"]
    assert finished_status_marker() not in close_messages
    if initial_status == WorkflowStatus.RUNNING.value:
        assert close_messages == [""]
    else:
        assert close_messages == []


@pytest.mark.asyncio
async def test_offline_workflow_close_is_not_marked_finished(monkeypatch):
    callback = FakeRedisCallback()
    client, sent = make_client(monkeypatch, callback, online=False)

    class FakeOfflineError:
        async def websocket_close_message(self, **_kwargs):
            return None

    monkeypatch.setattr(workflow_client_module, "WorkflowOfflineError", FakeOfflineError)

    await client.check_status({"flow_id": "flow-1", "chat_id": "chat-1"})

    assert sent == [{"category": "processing", "type": "close", "message": ""}]
    assert callback.cleared is True
