"""Public WS -> saved graph -> real input/LLM/output nodes -> durable answer.

SQLite and an in-memory Redis transport isolate all test data. Celery delivery,
model I/O, publication discovery and permission projection are external seams;
the actual WS adapter, manager, client, subject checks, graph and callbacks run.
"""

import asyncio
import json
from contextlib import asynccontextmanager, contextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
import sqlalchemy as sa
from fastapi import FastAPI, HTTPException
from langchain_core.messages import AIMessage
from sqlmodel import Session, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.chat_session.domain.repositories import moderation_repository
from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.common.chat import manager as manager_module
from bisheng.common.chat.clients import base as base_module
from bisheng.common.chat.clients import workflow_client as client_module
from bisheng.common.errcode.flow import WorkFlowInvalidUserInputError
from bisheng.core.database import tenant_filter
from bisheng.database.models import message as message_module
from bisheng.database.models import session as session_module
from bisheng.database.models.flow import Flow
from bisheng.database.models.flow_version import FlowVersion
from bisheng.database.models.message import ChatMessage
from bisheng.database.models.session import MessageSession
from bisheng.public_endpoints.api.endpoints import workflow as route
from bisheng.public_endpoints.domain.context import (
    PublicApiPrincipal,
    reset_current_public_api_principal,
    set_current_public_api_principal,
)
from bisheng.worker.workflow import redis_callback as callback_module
from bisheng.workflow.common.workflow import WorkflowStatus
from bisheng.workflow.nodes.llm.llm import LLMService
from bisheng.workflow.nodes.start.start import StartNode
from test.knowledge_unification import test_wf_entry as saved_fixtures
from test.workflow.memory_fixtures import graph, import_worker_tasks

store, tenant, admission = saved_fixtures.store, saved_fixtures.tenant, saved_fixtures.admission
FID = UUID(int=91).hex
CHAT = "e2e-public-continuation"


class MemoryRedis:
    def __init__(self):
        self.values = {}
        self.events = {}

    def get(self, key):
        return deepcopy(self.values.get(key))

    def set(self, key, value, **kwargs):
        self.values[key] = deepcopy(value)

    def delete(self, key):
        self.values.pop(key, None)

    def rpush(self, key, value, **kwargs):
        self.events.setdefault(key, []).append(value)

    def lpop(self, key):
        values = self.events.get(key, [])
        return values.pop(0) if values else None

    async def aget(self, key):
        return self.get(key)

    async def aset(self, key, value, **kwargs):
        self.set(key, value, **kwargs)

    async def adelete(self, key):
        self.delete(key)

    async def alpop(self, key):
        return self.lpop(key)


def node(node_id, kind, params, tab=None, version=1):
    data = {
        "id": node_id,
        "name": node_id,
        "type": kind,
        "v": str(version),
        "group_params": [
            {"name": "parameters", "params": [{"key": k, "value": v, "tab": tab} for k, v in params.items()]}
        ],
    }
    if tab:
        data["tab"] = {"value": tab}
    return {"id": node_id, "data": data}


def dialogue_graph(looping=False):
    saved = graph(
        node(
            "input_1",
            "input",
            {
                "user_input": "",
                "dialog_files_content": [],
                "dialog_file_accept": "all",
                "user_input_file": False,
            },
            "dialog_input",
            2,
        ),
        node(
            "llm_1",
            "llm",
            {
                "model_id": 42,
                "system_prompt": "Reply briefly",
                "user_prompt": "{{#input_1.user_input#}}",
            },
            "single",
        ),
        node(
            "output_1",
            "output",
            {
                "output_result": {"type": "none", "value": ""},
                "message": {"msg": "{{#llm_1.output#}}", "files": []},
            },
        ),
    )
    if looping:
        saved["nodes"] = saved["nodes"][:-1]
        saved["edges"][-1]["target"] = "input_1"
    return saved


class Socket:
    """Same-loop ASGI WebSocket transport with bounded receives."""

    def __init__(self, app):
        self.app = app
        self.incoming, self.outgoing = asyncio.Queue(), asyncio.Queue()
        self.task = None

    async def __aenter__(self):
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "scheme": "ws",
            "path": f"/workflow/chat/{FID}",
            "raw_path": f"/workflow/chat/{FID}".encode(),
            "query_string": f"chat_id={CHAT}".encode(),
            "root_path": "",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("test", 80),
            "subprotocols": [],
            "state": {},
        }
        self.task = asyncio.create_task(self.app(scope, self.incoming.get, self.outgoing.put))
        await self.incoming.put({"type": "websocket.connect"})
        assert (await asyncio.wait_for(self.outgoing.get(), 5))["type"] == "websocket.accept"
        return self

    async def send(self, message):
        await self.incoming.put({"type": "websocket.receive", "text": json.dumps(message)})

    async def until(self, category, event_type=None):
        frames = []
        for _ in range(40):
            event = await asyncio.wait_for(self.outgoing.get(), 5)
            assert event["type"] == "websocket.send", event
            frame = json.loads(event["text"])
            frames.append(frame)
            if category == "input" and frame["category"] == "error":
                raise AssertionError(frame)
            if frame["category"] == category and (event_type is None or frame["type"] == event_type):
                return frames
        raise AssertionError("expected workflow event was not returned")

    async def __aexit__(self, *args):
        await self.incoming.put({"type": "websocket.disconnect", "code": 1000})
        try:
            await asyncio.wait_for(self.task, 5)
        finally:
            if not self.task.done():
                self.task.cancel()


@pytest.fixture
async def dialogue(admission, store, monkeypatch, request):
    async_engine, sync_engine = store
    metadata = sa.MetaData()
    for model in (MessageSession, ChatMessage):
        sa.Table(
            model.__tablename__,
            metadata,
            *[
                sa.Column(
                    c.name,
                    c.type.copy(),
                    primary_key=c.primary_key,
                    nullable=c.nullable,
                    server_default=sa.text("CURRENT_TIMESTAMP")
                    if c.name in {"create_time", "update_time"}
                    else c.server_default,
                )
                for c in model.__table__.columns
            ],
        )
    metadata.create_all(sync_engine)
    monkeypatch.setattr(
        tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | {"messagesession", "chatmessage"}
    )

    @contextmanager
    def sync_session():
        with Session(sync_engine, expire_on_commit=False) as session:
            yield session

    @asynccontextmanager
    async def async_session():
        async with AsyncSession(async_engine, expire_on_commit=False) as session:
            yield session

    for module in (message_module, session_module):
        monkeypatch.setattr(module, "get_sync_db_session", sync_session)
        monkeypatch.setattr(module, "get_async_db_session", async_session)
    monkeypatch.setattr(moderation_repository, "get_sync_db_session", sync_session)
    monkeypatch.setattr(session_module.UserGroupDao, "aget_user_group", AsyncMock(return_value=[]))
    monkeypatch.setattr(session_module, "astamp_session", AsyncMock())
    saved_graph = dialogue_graph(looping=getattr(request, "param", False))
    with sync_session() as session:
        session.execute(
            sa.update(Flow).where(Flow.id == "wf", Flow.tenant_id == 101).values(id=FID, data=saved_graph, status=2)
        )
        session.execute(
            sa.update(FlowVersion).where(FlowVersion.flow_id == "wf", FlowVersion.tenant_id == 101).values(flow_id=FID)
        )
        session.execute(
            sa.update(FlowVersion).where(FlowVersion.id == 1, FlowVersion.tenant_id == 101).values(data=saved_graph)
        )
        session.commit()

    cache = MemoryRedis()
    monkeypatch.setattr(callback_module, "get_redis_client_sync", lambda: cache)
    monkeypatch.setattr(
        type(callback_module.settings), "get_workflow_conf", lambda self: SimpleNamespace(timeout=60, max_steps=50)
    )
    monkeypatch.setattr(callback_module, "save_message_citations_sync", Mock())
    monkeypatch.setattr(callback_module, "promote_chat_attachments_sync", Mock())

    def submit(_id, fn, *args, trace_id=None, **kwargs):
        # Match ThreadPool's reserved trace_id argument. Optional synchronous
        # title/telemetry jobs are outside the conversation under test.
        return asyncio.create_task(fn(*args, **kwargs)) if asyncio.iscoroutinefunction(fn) else None

    monkeypatch.setattr(callback_module.thread_pool, "submit", submit)
    monkeypatch.setattr(client_module.AuditLogService, "create_chat_workflow", Mock())
    monkeypatch.setattr(client_module, "ensure_client_execution_lease", AsyncMock(return_value="skipped"))
    monkeypatch.setattr(client_module.workflow_stateful_worker, "find_task_node", AsyncMock(return_value="test-worker"))
    monkeypatch.setattr(base_module, "release_client_execution_lease", AsyncMock())
    monkeypatch.setattr(manager_module, "record_authenticated_activity", AsyncMock())
    monkeypatch.setattr(manager_module, "check_business_action", AsyncMock(return_value=True))
    monkeypatch.setattr(manager_module.telemetry_service, "log_event", AsyncMock())
    monkeypatch.setattr(manager_module.WorkFlowService, "get_one_workflow_simple_info", AsyncMock(return_value=None))
    monkeypatch.setattr(route.PublishedWorkflowService, "get_workflow", AsyncMock())
    monkeypatch.setattr("bisheng.workflow.nodes.output.output.get_minio_storage_sync", lambda: object())
    original_start = StartNode._run

    def start(self, unique_id):
        self._user_info = "synthetic user"
        return original_start(self, unique_id)

    monkeypatch.setattr(StartNode, "_run", start)
    model = SimpleNamespace(invoke=Mock(return_value=AIMessage(content="Synthetic model answer")))
    monkeypatch.setattr(LLMService, "get_bisheng_llm_sync", lambda **kwargs: model)
    tasks = import_worker_tasks()
    monkeypatch.setattr(tasks, "_global_workflow", {})
    monkeypatch.setattr(tasks, "_online_memory_switch", lambda *_: False)
    monkeypatch.setattr(tasks, "_end_memory_turn", Mock())
    launches, continuations, clients = [], [], []

    def execute(args, **kwargs):
        launches.append(args)
        tasks._execute_workflow(*args[:5])

    def resume(args, **kwargs):
        continuations.append(args)
        tasks._continue_workflow(*args[:5])

    monkeypatch.setattr(client_module, "execute_workflow", SimpleNamespace(apply_async=execute))
    monkeypatch.setattr(client_module, "continue_workflow", SimpleNamespace(apply_async=resume))
    manager = manager_module.ChatManager()

    async def accept(key, client, socket):
        clients.append(client)
        await socket.accept()

    async def close(key, **kwargs):
        return None

    monkeypatch.setattr(manager, "accept_client", accept)
    monkeypatch.setattr(manager, "close_client", close)
    monkeypatch.setattr(manager, "clear_client", lambda *_: None)
    monkeypatch.setattr(route, "chat_manager", manager)

    @asynccontextmanager
    async def public_context(resource_type, resource_id):
        principal = PublicApiPrincipal(
            tenant_id=101, operator_user_id=11, operator_name="ordinary", resource_type="workflow", resource_id=FID
        )
        token = set_current_public_api_principal(principal)
        try:
            snapshot = Mock()
            snapshot.model_copy.return_value.model_dump.return_value = {"channel": "public_v3"}
            yield SimpleNamespace(
                operator=admission.identity,
                session_subject=SessionSubject.public_v3(tenant_id=101, operator_user_id=11, resource_id=FID),
                snapshot=snapshot,
            )
        finally:
            reset_current_public_api_principal(token)

    monkeypatch.setattr(route, "public_execution", public_context)
    app = FastAPI()
    app.include_router(route.router)
    yield SimpleNamespace(
        app=app, cache=cache, db=sync_session, model=model, launches=launches, resumes=continuations, clients=clients
    )


async def initialize(socket):
    await socket.send(
        {
            "action": "init_data",
            "flow_id": FID,
            "chat_id": CHAT,
            "source": "platform",
            "execution_snapshot": None,
            "data": {"nodes": [], "edges": []},
        }
    )
    return (await socket.until("input"))[-1]


def answer(prompt):
    return {
        "action": "input",
        "flow_id": FID,
        "chat_id": CHAT,
        "data": {
            "input_1": {
                "data": {"user_input": "Hello", "dialog_files_content": []},
                "message": "Hello",
                "message_id": prompt["message_id"],
            },
        },
    }


@pytest.mark.parametrize("reconnect", [False, True])
async def test_public_initialization_input_resume_and_model_answer_are_one_bound_conversation(dialogue, reconnect):
    h = dialogue
    async with Socket(h.app) as socket:
        prompt = await initialize(socket)
        assert h.clients[-1].workflow.source == "api"
        if not reconnect:
            await socket.send(answer(prompt))
            frames = await socket.until("processing", "close")
    if reconnect:
        async with Socket(h.app) as socket:
            await socket.send({"action": "check_status", "flow_id": FID, "chat_id": CHAT})
            prompt = (await socket.until("input"))[-1]
            assert h.clients[-1].workflow.source == "api"
            await socket.send(answer(prompt))
            frames = await socket.until("processing", "close")
    assert not [f for f in frames if f["category"] == "error"]
    assert any(f["category"] == "output_msg" and f["message"]["msg"] == "Synthetic model answer" for f in frames)
    assert len(h.launches) == len(h.resumes) == h.model.invoke.call_count == 1
    assert h.launches[0][4:] == h.resumes[0][4:] == ["api", {"channel": "public_v3"}]
    with h.db() as db:
        session = db.exec(select(MessageSession).where(MessageSession.chat_id == CHAT)).one()
        messages = db.exec(select(ChatMessage).where(ChatMessage.chat_id == CHAT)).all()
    assert session.api_subject_type == "public_v3" and session.tenant_id == 101 and session.flow_id == FID
    assert {m.user_id for m in messages} == {11} and {m.tenant_id for m in messages} == {101}
    assert any(m.category == "question" and m.message == "Hello" for m in messages)
    assert any(m.category == "output_msg" and "Synthetic model answer" in m.message for m in messages)


@pytest.mark.parametrize(
    "violation",
    [
        "natural_session",
        "wrong_resource",
        "wrong_tenant",
        "deleted",
        "wrong_chat",
        "wrong_flow",
        "wrong_message",
        "wrong_message_owner",
        "wrong_message_resource",
        "wrong_message_chat",
        "missing_pending",
        "extra_field",
    ],
)
async def test_public_input_keeps_subject_message_and_field_checks_before_writes_or_resume(dialogue, violation):
    h = dialogue
    async with Socket(h.app) as socket:
        prompt = await initialize(socket)
        payload = answer(prompt)
        with h.db() as db:
            if violation in {"natural_session", "wrong_resource", "wrong_tenant", "deleted"}:
                row = db.exec(select(MessageSession).where(MessageSession.chat_id == CHAT)).one()
                field, value = {
                    "natural_session": ("api_subject_type", None),
                    "wrong_resource": ("flow_id", "another"),
                    "wrong_tenant": ("tenant_id", 202),
                    "deleted": ("is_delete", True),
                }[violation]
                setattr(row, field, value)
                db.add(row)
                db.commit()
            elif violation in {"wrong_message_owner", "wrong_message_resource", "wrong_message_chat"}:
                row = db.get(ChatMessage, prompt["message_id"])
                field, value = {
                    "wrong_message_owner": ("user_id", 22),
                    "wrong_message_resource": ("flow_id", "another"),
                    "wrong_message_chat": ("chat_id", "victim"),
                }[violation]
                setattr(row, field, value)
                db.add(row)
                db.commit()
            before = [m.model_dump() for m in db.exec(select(ChatMessage)).all()]
        if violation == "wrong_chat":
            payload["chat_id"] = "victim"
        elif violation == "wrong_flow":
            payload["flow_id"] = "victim"
        elif violation == "wrong_message":
            payload["data"]["input_1"]["message_id"] += 100
        elif violation == "extra_field":
            payload["data"]["input_1"]["data"]["code"] = "untrusted"
        elif violation == "missing_pending":
            h.cache.delete(h.clients[-1].workflow.workflow_pending_key)
        await socket.send(payload)
        frames = await socket.until("processing", "close")
        errors = [f["message"] for f in frames if f["category"] == "error"]
        assert len(errors) == 1 and errors[0]["status_code"] == (
            10543
            if violation
            in {
                "wrong_message",
                "wrong_message_owner",
                "wrong_message_resource",
                "wrong_message_chat",
                "missing_pending",
                "extra_field",
            }
            else 10996
            if violation == "wrong_flow"
            else 404
        )
        assert not h.resumes and not h.model.invoke.called
        assert h.clients[-1].workflow.get_workflow_status()["status"] == WorkflowStatus.INPUT.value
        with h.db() as db:
            assert [m.model_dump() for m in db.exec(select(ChatMessage)).all()] == before


@pytest.mark.parametrize(
    "error,code",
    [(HTTPException(403, "SECRET"), 403), (WorkFlowInvalidUserInputError(), 10543), (RuntimeError("SECRET"), 10541)],
)
async def test_input_errors_reach_the_page_and_settle_waiting_without_leaking_internal_details(dialogue, error, code):
    h = dialogue
    async with Socket(h.app) as socket:
        prompt = await initialize(socket)
        h.clients[-1].handle_user_input = AsyncMock(side_effect=error)
        await socket.send(answer(prompt))
        frames = await socket.until("processing", "close")
    errors = [f["message"] for f in frames if f["category"] == "error"]
    assert len(errors) == 1 and errors[0]["status_code"] == code
    assert "SECRET" not in json.dumps(frames) and not h.resumes


@pytest.mark.parametrize("dialogue", [True], indirect=True)
async def test_looping_workflow_accepts_two_rounds_and_rejects_replayed_prompt(dialogue):
    h = dialogue
    async with Socket(h.app) as socket:
        first = await initialize(socket)
        await socket.send(answer(first))
        frames = await socket.until("input")
        second = frames[-1]
        assert second["message_id"] != first["message_id"]
        assert any(f["category"] == "output_msg" for f in frames)
        await socket.send(answer(first))
        rejected = await socket.until("processing", "close")
        assert next(f for f in rejected if f["category"] == "error")["message"]["status_code"] == 10543
        assert len(h.resumes) == h.model.invoke.call_count == 1
        await socket.send(answer(second))
        frames = await socket.until("input")
        assert any(f["category"] == "output_msg" for f in frames)
        assert frames[-1]["message_id"] != second["message_id"]
    assert len(h.launches) == 1 and len(h.resumes) == h.model.invoke.call_count == 2


async def test_platform_persistence_still_rejects_public_owned_sessions(dialogue):
    h = dialogue
    async with Socket(h.app) as socket:
        prompt = await initialize(socket)
        # Recreate the original channel mismatch after admission. The natural
        # person persistence guard must continue refusing public-v3 ownership.
        h.clients[-1].workflow.source = "platform"
        await socket.send(answer(prompt))
        frames = await socket.until("processing", "close")
    assert next(f for f in frames if f["category"] == "error")["message"]["status_code"] == 403
    assert not h.resumes and not h.model.invoke.called


async def test_input_concurrency_rejection_settles_waiting_without_consuming_input(dialogue, monkeypatch):
    h = dialogue
    async with Socket(h.app) as socket:
        prompt = await initialize(socket)
        monkeypatch.setattr(client_module, "ensure_client_execution_lease", AsyncMock(return_value="rejected"))
        await socket.send(answer(prompt))
        frames = await socket.until("processing", "close")
        assert next(f for f in frames if f["category"] == "error")["message"]["status_code"] == 12045
        assert h.clients[-1].workflow.get_workflow_status()["status"] == WorkflowStatus.INPUT.value
    assert not h.resumes and not h.model.invoke.called


async def test_initialization_authorization_error_keeps_its_code_and_ends_waiting(dialogue, monkeypatch):
    h = dialogue
    async with Socket(h.app) as socket:
        monkeypatch.setattr(
            h.clients[-1].execution_port, "prepare_initial", AsyncMock(side_effect=HTTPException(403, "SECRET"))
        )
        await socket.send({"action": "init_data", "flow_id": FID, "chat_id": CHAT, "data": {}})
        frames = await socket.until("processing", "close")
    assert next(f for f in frames if f["category"] == "error")["message"]["status_code"] == 403
    assert "SECRET" not in json.dumps(frames)
    assert not h.launches and not h.resumes and not h.model.invoke.called
