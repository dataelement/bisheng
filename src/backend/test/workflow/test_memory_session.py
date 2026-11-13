"""F132 T064: workflow session registration and end of turn.

Covers AC-10, AC-37, AC-42. Only the logged-in workflow WebSocket endpoint hands
the client a registration callback (R2); the client calls it when the message
carries a ``chat_id`` (V8). The Celery task ends a turn every time it yields
(waiting for input, success, failure) (§4.4 "工作流：一轮结束").
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlmodel import select

from bisheng.database.models.message import ChatMessage
from bisheng.database.models.session import MessageSession
from bisheng.memory.domain.models.memory_item import MemoryItem
from bisheng.memory.domain.models.memory_session_cursor import MemorySessionCursor
from bisheng.memory.domain.services.activity import MemoryActivity
from bisheng.memory.domain.services.consolidator import Consolidator
from bisheng.memory.domain.services.metrics import MemoryMetrics
from bisheng.workflow.common.workflow import WorkflowStatus
from test.workflow.memory_fixtures import (  # noqa: F401  (fixtures)
    TENANT_A,
    USER_1,
    details,
    import_worker_tasks,
    index,
    kv,
    make_message,
    memory_db,
    memory_runtime_config,
    register_chat,
    seed_online_workflow,
    seed_user,
    service,
    wired,
)

CHAT = "wf-chat-1"


def _login(user_id=USER_1):
    return SimpleNamespace(user_id=user_id, tenant_id=TENANT_A, user_name="u")


def _cursor(memory_db, chat_id=CHAT):
    with memory_db.session() as s:
        return s.get(MemorySessionCursor, chat_id)


def _cursors(memory_db):
    with memory_db.session() as s:
        return list(s.exec(select(MemorySessionCursor)).all())


# ---- registration ------------------------------------------------------------------------


@pytest.fixture
def logged_in_callback(monkeypatch):
    """The registration callback the logged-in workflow WebSocket endpoint hands to dispatch_client."""
    from bisheng.api.v1 import workflow as wf_api

    dispatch = AsyncMock()
    monkeypatch.setattr(wf_api.chat_manager, "dispatch_client", dispatch)
    monkeypatch.setattr(wf_api, "require_business_action", AsyncMock())
    login = _login()
    return SimpleNamespace(dispatch=dispatch, login=login, endpoint=wf_api.workflow_ws)


async def test_ac10_logged_in_endpoint_passes_a_register_callback(memory_db, logged_in_callback):
    """AC-10: the logged-in workflow endpoint passes memory_register; calling it registers the chat."""
    seed_user(memory_db)
    ws = Mock()
    await logged_in_callback.endpoint(
        workflow_id="wf-1", websocket=ws, chat_id=None, login_user=logged_in_callback.login
    )
    register = logged_in_callback.dispatch.await_args.kwargs["memory_register"]
    assert callable(register)
    await register(CHAT)
    row = _cursor(memory_db)
    assert (row.tenant_id, row.user_id, row.eligible) == (TENANT_A, USER_1, True)


async def test_ac10_guest_workflow_endpoint_passes_no_register_callback(monkeypatch):
    """AC-10: the guest-link workflow endpoint never passes memory_register."""
    from bisheng.public_endpoints.api.endpoints import workflow as public_wf

    dispatch = AsyncMock()
    snapshot = Mock()
    snapshot.model_copy.return_value.model_dump.return_value = {}

    @asynccontextmanager
    async def _execution(*args, **kwargs):
        yield SimpleNamespace(session_subject=object(), snapshot=snapshot, operator=_login(9))

    monkeypatch.setattr(public_wf.chat_manager, "dispatch_client", dispatch)
    monkeypatch.setattr(public_wf, "public_execution", _execution)
    monkeypatch.setattr(public_wf.PublishedWorkflowService, "validate_websocket_session", AsyncMock())
    import uuid

    await public_wf.workflow_ws(workflow_id=uuid.uuid4(), websocket=Mock(), chat_id=CHAT)
    dispatch.assert_awaited_once()
    assert "memory_register" not in dispatch.await_args.kwargs


def _client(monkeypatch, register):
    from bisheng.common.chat.clients import workflow_client as wc
    from bisheng.common.chat.types import WorkType

    monkeypatch.setattr(wc.ChatMessageDao, "aget_latest_message_by_chatid", AsyncMock(return_value=None))
    monkeypatch.setattr(wc.AuditLogService, "create_chat_workflow", Mock())
    monkeypatch.setattr(wc, "get_request_ip", Mock(return_value="127.0.0.1"))
    monkeypatch.setattr(wc, "RedisCallback", Mock())
    monkeypatch.setattr(wc.WorkflowClient, "ensure_workflow_available", AsyncMock(return_value=False))
    client = wc.WorkflowClient(Mock(), "key", "wf-1", "", USER_1, _login(), WorkType.WORKFLOW, Mock())
    client.memory_register = register
    return client


async def test_ac10_client_registers_when_message_carries_chat_id(monkeypatch):
    """AC-10: the client calls the injected callback with the chat_id from the message."""
    register = AsyncMock()
    client = _client(monkeypatch, register)
    await client.check_status({"flow_id": "wf-1", "chat_id": CHAT}, is_init=True)
    register.assert_awaited_once_with(CHAT)
    await client.check_status({"flow_id": "wf-1", "chat_id": "chat-2"}, is_init=True)
    assert register.await_args.args == ("chat-2",)


async def test_ac10_debug_run_without_chat_id_does_not_register(monkeypatch):
    """AC-10: canvas debug / evaluation (empty chat_id) never registers."""
    register = AsyncMock()
    client = _client(monkeypatch, register)
    await client.check_status({"flow_id": "wf-1", "chat_id": ""}, is_init=True)
    register.assert_not_awaited()


async def test_ac10_client_without_callback_never_registers(memory_db, monkeypatch):
    """AC-10: guest and open connections get no callback, so no registration row appears."""
    client = _client(monkeypatch, None)
    await client.check_status({"flow_id": "wf-1", "chat_id": CHAT}, is_init=True)
    assert _cursors(memory_db) == []


async def test_registration_failure_does_not_break_the_client(monkeypatch):
    """Registration is best effort: a failing callback leaves the workflow run untouched."""
    client = _client(monkeypatch, AsyncMock(side_effect=RuntimeError("db down")))
    flag, unique_id = await client.check_status({"flow_id": "wf-1", "chat_id": CHAT}, is_init=True)
    assert unique_id == f"{CHAT}_async_task_id"


# ---- end of turn in the Celery task ---------------------------------------------------------


class FakeRedisCallback:
    user_input = {"input_1": {"user_input": "继续"}}

    def __init__(self, unique_id, workflow_id, chat_id, user_id, source="platform", tenant_id=None):
        self.unique_id, self.workflow_id, self.chat_id = unique_id, workflow_id, chat_id
        self.workflow = None

    def set_workflow_status(self, status, reason=""):
        pass

    def get_workflow_data(self):
        return {"nodes": [], "edges": []}

    def get_user_input(self):
        return FakeRedisCallback.user_input


class FakeWorkflow:
    """Stands in for Workflow; ``outcome`` drives the status or raises."""

    outcome = WorkflowStatus.SUCCESS.value

    def __init__(self, *args, chat_id="", memory_enabled=False, **kwargs):
        self.graph_engine = SimpleNamespace(graph_state=SimpleNamespace(chat_id=chat_id, memory_enabled=memory_enabled))
        self._status = WorkflowStatus.RUNNING.value

    def run(self, input_data=None):
        if isinstance(FakeWorkflow.outcome, Exception):
            raise FakeWorkflow.outcome
        self._status = FakeWorkflow.outcome
        return self._status, ""

    def status(self):
        return self._status

    def reason(self):
        return ""


@pytest.fixture
def worker(monkeypatch, memory_db):
    tasks = import_worker_tasks()
    monkeypatch.setattr(tasks, "RedisCallback", FakeRedisCallback)
    monkeypatch.setattr(tasks, "Workflow", FakeWorkflow)
    monkeypatch.setattr(
        tasks.FlowDao, "get_flow_by_id", Mock(return_value=SimpleNamespace(name="报销流程", tenant_id=1, user_id=1))
    )
    monkeypatch.setattr(
        type(tasks.settings),
        "get_workflow_conf",
        lambda self: SimpleNamespace(max_steps=10, timeout=10),
        raising=False,
    )
    calls = []
    original = MemoryActivity.end_turn_sync.__func__

    def _spy(cls, chat_id, last_message_id, enabled, now=None):
        calls.append((chat_id, enabled))
        return original(cls, chat_id, last_message_id, enabled, now)

    monkeypatch.setattr(MemoryActivity, "end_turn_sync", classmethod(_spy))
    monkeypatch.setattr(tasks, "_global_workflow", {})
    FakeWorkflow.outcome = WorkflowStatus.SUCCESS.value
    return SimpleNamespace(tasks=tasks, calls=calls)


def _seed_session(memory_db, messages=2, switch=True):
    seed_online_workflow(memory_db, "wf-1", switch=switch)
    register_chat(memory_db, CHAT)
    with memory_db.session() as s:
        s.add(MessageSession(chat_id=CHAT, flow_id="wf-1", flow_type=10, user_id=USER_1, name="c"))
        ids = []
        for i in range(messages):
            m = make_message(CHAT, USER_1, f"第{i}条", category="question" if i % 2 == 0 else "output_msg")
            s.add(m)
            s.flush()
            ids.append(m.id)
        s.commit()
    return ids


@pytest.mark.parametrize(
    "outcome",
    [WorkflowStatus.SUCCESS.value, WorkflowStatus.FAILED.value, WorkflowStatus.INPUT.value, RuntimeError("boom")],
)
async def test_ac37_each_yield_marks_activity_once(memory_db, worker, outcome):
    """AC-37: success, failure, waiting for input and an exception each end the turn exactly once."""
    ids = _seed_session(memory_db)
    FakeWorkflow.outcome = outcome
    await asyncio.to_thread(worker.tasks._execute_workflow, "u-1", "wf-1", CHAT, USER_1)
    assert worker.calls == [(CHAT, True)]
    row = _cursor(memory_db)
    assert row.state == "pending" and row.last_message_id == ids[-1] and row.last_activity_at is not None


async def test_ac37_continue_after_input_marks_activity_again(memory_db, worker):
    """AC-37: a run that stopped for input and is resumed ends a turn again at the next yield."""
    _seed_session(memory_db)
    FakeWorkflow.outcome = WorkflowStatus.INPUT.value
    await asyncio.to_thread(worker.tasks._execute_workflow, "u-1", "wf-1", CHAT, USER_1)
    FakeWorkflow.outcome = WorkflowStatus.SUCCESS.value
    await asyncio.to_thread(worker.tasks._continue_workflow, "u-1", "wf-1", CHAT, USER_1)
    assert worker.calls == [(CHAT, True), (CHAT, True)]


async def test_ac37_continue_with_lost_run_object_still_ends_the_turn(memory_db, worker):
    """AC-37: the resumed run object is gone (expired); the turn still ends, as not enabled."""
    _seed_session(memory_db)
    await asyncio.to_thread(worker.tasks._continue_workflow, "gone", "wf-1", CHAT, USER_1)
    assert worker.calls == [(CHAT, False)]


async def test_memory_off_advances_the_watermark(memory_db, worker):
    """AC-41 / decision 7: memory not enabled for the run (switch off) -> watermark moves past it."""
    ids = _seed_session(memory_db, switch=False)
    await asyncio.to_thread(worker.tasks._execute_workflow, "u-1", "wf-1", CHAT, USER_1)
    assert worker.calls == [(CHAT, False)]
    row = _cursor(memory_db)
    assert row.watermark_message_id == ids[-1] and row.state != "pending"


async def test_ac10_runs_without_chat_id_do_not_touch_memory(memory_db, worker):
    """AC-10: evaluation / debug runs (empty chat_id) never end a memory turn."""
    await asyncio.to_thread(worker.tasks._execute_workflow, "u-1", "wf-1", "", USER_1)
    assert worker.calls == [] and _cursors(memory_db) == []


async def test_end_turn_failure_does_not_change_the_run(memory_db, worker, monkeypatch):
    """Ending the memory turn is best effort and never fails the workflow task."""
    _seed_session(memory_db)
    monkeypatch.setattr(MemoryActivity, "end_turn_sync", classmethod(Mock(side_effect=RuntimeError("db"))))
    await asyncio.to_thread(worker.tasks._execute_workflow, "u-1", "wf-1", CHAT, USER_1)


class FakeContent:
    def __init__(self):
        self.calls = []

    async def __call__(self, ctx, cursor, end_id):
        self.calls.append((cursor.chat_id, ctx.scene, ctx.app_id))
        return [{"op": "add", "content": "用户的成本中心是 C-100", "type": "fact"}]


async def test_ac42_workflow_session_is_consolidated_after_quiet_period(memory_db, worker, service, kv):
    """AC-37, AC-42: after a workflow turn and the quiet period, the session is consolidated into items."""
    _seed_session(memory_db)
    await asyncio.to_thread(worker.tasks._execute_workflow, "u-1", "wf-1", CHAT, USER_1)
    content = FakeContent()
    consolidator = Consolidator(service=service, kv=kv, metrics=MemoryMetrics(kv), content_fn=content)
    await consolidator.consolidate_user(TENANT_A, USER_1, now=datetime.now() + timedelta(days=1))
    assert content.calls == [(CHAT, "workflow", "wf-1")]
    with memory_db.session() as s:
        items = list(s.exec(select(MemoryItem)).all())
        assert len(s.exec(select(ChatMessage)).all()) == 2
    assert [(i.content, i.source_scene, i.source_app_name) for i in items] == [
        ("用户的成本中心是 C-100", "workflow", "报销流程")
    ]
    assert _cursor(memory_db).state == "idle"
