"""F078: a debug window keeps one temporary agent session per connection.

覆盖 AC: AC-36、AC-37
"""

import asyncio
from types import SimpleNamespace

import pytest

from bisheng.agent_runtime.domain.services import tmp_session as tmp_session_module
from bisheng.common.chat.clients import workflow_client as workflow_client_module
from bisheng.common.chat.clients.workflow_client import WorkflowClient
from bisheng.core.cache import redis_manager
from bisheng.core.storage.minio import minio_manager
from bisheng.worker.workflow import tasks as tasks_module
from bisheng.workflow.common.workflow import WorkflowStatus


class FakeRedisCallback:
    """A run that finishes as soon as the client looks at it."""

    def __init__(self, unique_id, *_args):
        self.unique_id = unique_id

    def get_workflow_status(self):
        return None

    async def async_set_workflow_data(self, _data):
        return None

    async def async_set_workflow_status(self, _status):
        return None

    async def get_response_until_break(self):
        return
        yield

    async def async_get_workflow_status(self):
        return {"status": WorkflowStatus.SUCCESS.value}

    async def async_clear_workflow_status(self):
        return None

    async def async_set_workflow_stop(self):
        return None


@pytest.fixture
def harness(monkeypatch):
    runs: list[dict] = []
    closed: list[str] = []
    ids = iter(f"id{i}" for i in range(100))

    class FakeService:
        def __init__(self, **_kwargs):
            pass

        async def aclose(self, tmp_id):
            closed.append(tmp_id)

    async def find_task_node(_hash_key):
        return "queue-1"

    async def get_client():
        return None

    async def no_new_refs(*_args):
        return None

    monkeypatch.setattr(workflow_client_module, "RedisCallback", FakeRedisCallback)
    # F086 checks subflow references before a run; these drafts have none.
    monkeypatch.setattr(workflow_client_module.SubflowService, "check_new_refs", no_new_refs)
    monkeypatch.setattr(workflow_client_module, "generate_uuid", lambda: next(ids))
    monkeypatch.setattr(
        workflow_client_module.execute_workflow,
        "apply_async",
        lambda args, kwargs=None, queue=None: runs.append({"args": args, "kwargs": kwargs or {}, "queue": queue}),
    )
    monkeypatch.setattr(workflow_client_module.workflow_stateful_worker, "find_task_node", find_task_node)
    monkeypatch.setattr(tmp_session_module, "TmpSessionService", FakeService)
    monkeypatch.setattr(redis_manager, "get_redis_client", get_client)
    monkeypatch.setattr(minio_manager, "get_minio_storage", get_client)
    return runs, closed


def _client(chat_id: str = "") -> WorkflowClient:
    client = WorkflowClient.__new__(WorkflowClient)
    client.client_id = "flow-1"
    client.chat_id = chat_id
    client.user_id = 1
    client.login_user = None
    client.latest_history = None
    client.workflow = None
    client.hash_key = None
    client.agent_tmp_session_id = None
    client.session_subject = None
    client.execution_snapshot = None
    client.ws_closed = False
    client.run_lock = asyncio.Lock()

    async def noop(*_args, **_kwargs):
        return None

    client.send_response = noop
    client.send_json = noop
    client.init_history = noop
    return client


async def _run(client: WorkflowClient, chat_id: str = "") -> None:
    message = {"action": "init_data", "flow_id": "flow-1", "data": {"nodes": []}}
    if chat_id:
        message["chat_id"] = chat_id
    await client.init_workflow(message)


@pytest.fixture(autouse=True)
def online_flow(monkeypatch):
    monkeypatch.setattr(
        workflow_client_module.FlowDao,
        "get_flow_by_id",
        lambda _flow_id: SimpleNamespace(status=2),
    )


async def test_runs_in_one_debug_window_share_the_temp_session(harness):
    runs, _ = harness
    client = _client()

    await _run(client)
    await _run(client)

    assert len(runs) == 2
    # Each run gets its own unique_id, but both use the connection's session.
    assert runs[0]["args"][0] != runs[1]["args"][0]
    first, second = (run["kwargs"]["tmp_session_id"] for run in runs)
    assert first and first == second == client.hash_key


async def test_closing_the_window_after_a_finished_run_cleans_the_session(harness):
    _, closed = harness
    client = _client()
    await _run(client)
    assert client.workflow is None

    await client.close()

    assert closed == [client.hash_key]
    # A second close (the manager's finally) does nothing more.
    await client.close()
    assert len(closed) == 1


async def test_window_closed_by_the_browser_still_cleans_the_session(harness):
    _, closed = harness
    client = _client()
    await _run(client)

    async def gone(*_args, **_kwargs):
        raise RuntimeError("Unexpected ASGI message 'websocket.send', after sending 'websocket.close'")

    # The browser usually disconnects first, so the farewell message fails.
    client.send_response = gone
    with pytest.raises(RuntimeError):
        await client.close()

    assert closed == [client.hash_key]


async def test_stop_keeps_the_session_for_the_next_run(harness):
    _, closed = harness
    client = _client()
    await _run(client)

    await client.close(force_stop=True)

    assert closed == []


async def test_formal_conversation_has_no_temp_session(harness):
    runs, closed = harness
    client = _client()

    await _run(client, chat_id="chat-1")
    await client.close()

    assert runs[0]["kwargs"]["tmp_session_id"] is None
    assert closed == []


async def test_window_closed_without_a_run_cleans_nothing(harness):
    _, closed = harness
    await _client().close()
    assert closed == []


@pytest.mark.parametrize(
    ("chat_id", "passed", "expected"),
    [("", "conn-1", "conn-1"), ("", None, "run-1"), ("chat-1", "conn-1", None)],
)
def test_execute_workflow_hands_the_session_to_the_engine(monkeypatch, chat_id, passed, expected):
    seen = {}

    class FakeWorkflow:
        def __init__(self, *_args, **kwargs):
            seen.update(kwargs)

        def run(self):
            return WorkflowStatus.SUCCESS.value, ""

        def status(self):
            return WorkflowStatus.SUCCESS.value

        def reason(self):
            return ""

    class FakeCallback:
        def __init__(self, unique_id, *_args, **_kwargs):
            self.unique_id = unique_id

        def set_workflow_status(self, *_args):
            return None

        def get_workflow_data(self):
            return {"nodes": []}

    monkeypatch.setattr(tasks_module, "Workflow", FakeWorkflow)
    monkeypatch.setattr(
        tasks_module,
        "settings",
        SimpleNamespace(get_workflow_conf=lambda: SimpleNamespace(max_steps=10, timeout=10)),
    )
    monkeypatch.setattr(tasks_module, "RedisCallback", FakeCallback)
    monkeypatch.setattr(
        tasks_module.FlowDao, "get_flow_by_id", lambda _id: SimpleNamespace(name="f", tenant_id=1, user_id=1)
    )

    tasks_module._execute_workflow("run-1", "flow-1", chat_id, 1, "platform", passed)

    assert seen["tmp_session_id"] == expected
