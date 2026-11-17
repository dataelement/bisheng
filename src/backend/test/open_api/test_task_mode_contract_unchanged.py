"""The Open API task-mode contract is the same with the unified runtime on and off (F004 T035).

Spec AC-39: request format, response format and status meaning of the Open API
deep-research endpoints do not change. Spec AC-23: an unattended (Open API) run
never asks the user and never reads the conversation inbox.

Every test produces the same answer twice, once for a tenant with the
unified-runtime switch off and once with it on, and compares the two. The
endpoint tests go through the real v2 router (admission, scope markers,
exception handlers) and the real ``OpenTaskModeService``; only storage is
faked. The run tests drive the REAL graph of ``create_linsight_agent`` with a
scripted model through the worker's executor (``LinsightWorkflowTask``) with
fakeredis, reusing the harness of ``test/linsight/test_planned_run_unified.py``.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage

from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.database.models.session import MessageSession
from bisheng.linsight.domain import utils as linsight_utils
from bisheng.linsight.domain.models.linsight_execute_task import ExecuteTaskStatusEnum
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion, SessionVersionStatusEnum
from bisheng.linsight.domain.services import agent_factory
from bisheng.linsight.domain.services.workspace_backend import WorkspaceBackend
from bisheng.open_api.api.dependencies import verify_open_api_access
from bisheng.open_api.api.exception_handlers import register_open_api_exception_handlers
from bisheng.open_api.domain.services import task_mode_service
from bisheng.open_api.domain.services.task_mode_service import OpenTaskModeService
from bisheng.open_endpoints.api.endpoints import workstation as endpoints
from bisheng.workstation.domain.services import run_lease
from bisheng.workstation.domain.services.run_dispatch import RunDispatchService
from bisheng.workstation.domain.services.task_submit_service import submit_task_turn as REAL_SUBMIT_TASK_TURN
from bisheng.workstation.domain.services.workstation_service import WorkStationService
from test.linsight.test_planned_run_unified import CHAT, SVID, TODOS, TODOS_DONE, _call, _Env, _PlannedUnifiedModel
from test.open_api.task_mode_support import sa_principal

S = SessionVersionStatusEnum
SWITCH_STATES = (False, True)
TASK_BODY = {
    "run_mode": "task",
    "execution": "async",
    "clientTimestamp": "2026-09-30T10:00:00",
    "text": "Review the attached contracts\nand list the risks",
    "model": "7",
    "instructions": "只看第三章",
}
# The documented status values of the Open API (spec AC-39: their meaning is fixed).
DOCUMENTED_STATUSES = {"queued", "running", "waiting_input", "completed", "failed", "terminated"}
FIXED_TIME = datetime(2026, 9, 30, 10, 0, 0)
OPEN_API_META = {"channel": "open_api_v2", "instructions": None, "credential_id": 7, "identity_mode": "S"}


# ---------------------------------------------------------------------------
# HTTP harness: the real v2 router and OpenTaskModeService, storage faked
# ---------------------------------------------------------------------------


@pytest.fixture
def switch(monkeypatch: pytest.MonkeyPatch):
    """Set the tenant's unified-runtime switch; returns the setter."""

    def set_switch(on: bool) -> AsyncMock:
        probe = AsyncMock(return_value=on)
        monkeypatch.setattr(WorkStationService, "is_unified_runtime_enabled", probe)
        return probe

    return set_switch


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch):
    async def _validate_bearer(*_args, **_kwargs):
        return sa_principal()

    monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", _validate_bearer)
    monkeypatch.setattr(
        endpoints, "get_open_api_operator_async", AsyncMock(return_value=SimpleNamespace(user_id=12, tenant_id=9))
    )
    application = FastAPI()
    register_open_api_exception_handlers(application)
    v2 = APIRouter(prefix="/api/v2", dependencies=[Depends(verify_open_api_access)])
    v2.include_router(endpoints.router)
    application.include_router(v2)
    return application


async def _call_api(app: FastAPI, method: str, path: str, body: Any = None):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"Authorization": "Bearer bs-sak-test", "X-End-User": "emp-1"}
        if method == "post":
            return await client.post(path, json=body, headers=headers)
        return await client.get(path, headers=headers)


def _sa_session() -> MessageSession:
    subject = SessionSubject.service_account(
        tenant_id=9, service_account_id=31, resource_owner_user_id=12, external_user_id="emp-1"
    )
    session = subject.stamp(MessageSession(chat_id="chat-1", name="n", flow_type=15, user_id=12))
    session.is_delete = False
    return session


def _version(status=S.NOT_STARTED, output=None, files=None) -> LinsightSessionVersion:
    return LinsightSessionVersion(
        id="svid-1",
        session_id="chat-1",
        user_id=12,
        question="q",
        status=status,
        output_result=output,
        files=files,
        tenant_id=9,
        api_meta=dict(OPEN_API_META),
        create_time=FIXED_TIME,
        update_time=FIXED_TIME,
    )


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch):
    """The task record, its todo rows and its deliverables, kept in memory."""
    state = SimpleNamespace(version=_version(), todos=[], objects={}, terminated=[])

    async def _get_version(task_id):
        return state.version if state.version and task_id == state.version.id else None

    async def _todos(_svid, is_parent_task=False):
        return state.todos

    async def _size(object_name):
        data = state.objects.get(object_name)
        return None if data is None else len(data)

    async def _terminate(version):
        state.terminated.append(version.id)
        version.status = S.TERMINATED

    class _Resp:
        def __init__(self, data: bytes) -> None:
            self.data = data

        def stream(self, _size):
            yield self.data

        def close(self):
            pass

        def release_conn(self):
            pass

    def _download(object_name=None, bucket_name=None):
        return _Resp(state.objects[object_name])

    monkeypatch.setattr(task_mode_service.LinsightSessionVersionDao, "get_by_id", _get_version)
    monkeypatch.setattr(task_mode_service.MessageSessionDao, "async_get_one", AsyncMock(return_value=_sa_session()))
    monkeypatch.setattr(task_mode_service.LinsightExecuteTaskDao, "get_by_session_version_id", _todos)
    monkeypatch.setattr(OpenTaskModeService, "_object_size", staticmethod(_size))
    monkeypatch.setattr(OpenTaskModeService, "_queue_position", staticmethod(AsyncMock(return_value=2)))
    monkeypatch.setattr("bisheng.linsight.domain.services.workbench_impl.LinsightWorkbenchImpl.terminate", _terminate)
    monkeypatch.setattr(
        "bisheng.core.storage.minio.minio_manager.get_minio_storage",
        AsyncMock(return_value=SimpleNamespace(download_object_sync=_download)),
    )
    return state


def _shape(value: Any) -> Any:
    """The field structure of a JSON value: keys and value types, not the values."""
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_shape(item) for item in value]
    return type(value).__name__


# ---------------------------------------------------------------------------
# AC-39: the four endpoints
# ---------------------------------------------------------------------------


async def test_submit_response_shape(app, switch, task_mode_seams, monkeypatch: pytest.MonkeyPatch):
    # The REAL submit core, faked below it: what it hands the worker is compared too.
    monkeypatch.setattr(
        "bisheng.workstation.domain.services.task_submit_service.submit_task_turn", REAL_SUBMIT_TASK_TURN
    )
    monkeypatch.setattr(
        "bisheng.workstation.domain.services.task_submit_service._consume_task_invite", AsyncMock(return_value=False)
    )
    created: list[dict] = []
    enqueued: list[LinsightSessionVersion] = []

    async def _submit_user_question(submit_obj, login_user, display_files=None, **kwargs):
        created.append(kwargs)
        version = LinsightSessionVersion(
            id="svid-1",
            session_id="chat-1",
            user_id=12,
            question=submit_obj.question,
            tenant_id=9,
            api_meta=kwargs.get("api_meta"),
        )
        return SimpleNamespace(chat_id="chat-1"), version

    async def _enqueue(version):
        enqueued.append(version)

    monkeypatch.setattr(
        "bisheng.linsight.domain.services.workbench_impl.LinsightWorkbenchImpl.submit_user_question",
        _submit_user_question,
    )
    monkeypatch.setattr(linsight_utils, "persist_task_turn_message", AsyncMock())
    monkeypatch.setattr(linsight_utils, "enqueue_session_for_execution", _enqueue)
    # The Open API never goes through the unified send entry.
    dispatch_submit = AsyncMock(side_effect=AssertionError("the Open API went through RunDispatchService.submit"))
    monkeypatch.setattr(RunDispatchService, "submit", dispatch_submit)

    answers = []
    for on in SWITCH_STATES:
        switch(on)
        created.clear()
        enqueued.clear()
        response = await _call_api(app, "post", "/api/v2/workstation/chat/completions", TASK_BODY)
        assert response.status_code == 200, response.text
        (handed_over,) = enqueued
        answers.append(
            {
                "body": response.json(),
                "submit_kwargs": {key: value for key, value in created[0].items() if key != "session_subject"},
                "api_meta": handed_over.api_meta,
            }
        )

    off, on = answers
    assert on == off
    assert set(off["body"]["data"]) == {"task_id", "status", "queue_position"}
    assert off["body"]["data"] == {"task_id": "svid-1", "status": "queued", "queue_position": 3}
    # The worker sees an unattended run with no run id of the unified send entry.
    assert off["api_meta"] == {
        "channel": "open_api_v2",
        "instructions": "只看第三章",
        "credential_id": 7,
        "identity_mode": "S",
    }
    dispatch_submit.assert_not_called()


@pytest.mark.parametrize("status", list(S))
async def test_task_status_values(app, switch, store, status):
    output = {"answer": "done", "final_files": []} if status == S.COMPLETED else {"error_type": "x"}
    answers = []
    for on in SWITCH_STATES:
        switch(on)
        store.version = _version(status, output=output)
        store.todos = [
            SimpleNamespace(id="svid-1", status=ExecuteTaskStatusEnum.IN_PROGRESS),
            SimpleNamespace(id="t1", status=ExecuteTaskStatusEnum.SUCCESS),
            SimpleNamespace(id="t2", status=ExecuteTaskStatusEnum.IN_PROGRESS),
        ]
        response = await _call_api(app, "get", "/api/v2/workstation/tasks/svid-1")
        assert response.status_code == 200, response.text
        answers.append(response.json())

    off, on = answers
    assert on == off
    assert off["data"]["status"] in DOCUMENTED_STATUSES


async def test_task_status_after_a_real_run(monkeypatch: pytest.MonkeyPatch, tmp_path, store, app, switch):
    """The record a real worker run leaves behind reads the same through the Open API."""
    answers = []
    for on in SWITCH_STATES:
        switch(on)
        run = await _run_open_api_task(monkeypatch, tmp_path / str(on), unified=on)
        store.version = run.env.version
        store.objects = {"linsight/final_result/sv-9001/f1.md": b"# report"}
        store.todos = []
        monkeypatch.setattr(
            task_mode_service.MessageSessionDao,
            "async_get_one",
            AsyncMock(return_value=_sa_session().model_copy(update={"chat_id": CHAT})),
        )
        response = await _call_api(app, "get", f"/api/v2/workstation/tasks/{SVID}")
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        data.pop("created_at", None)
        data.pop("updated_at", None)
        answers.append((run.env.version.status, data))

    off, on = answers
    assert on == off
    assert off[0] == S.COMPLETED and off[1]["status"] == "completed"
    assert [item["file_id"] for item in off[1]["result"]["files"]] == ["f1"]


async def test_files_response_shape(app, switch, store):
    output = {
        "answer": "see the report",
        "final_files": [
            {
                "file_id": "f1",
                "file_name": "报告.docx",
                "file_path": "/root/.cache/x/报告.docx",
                "file_url": "linsight/final_result/svid-1/f1.docx",
            },
            {"file_id": "f2", "file_name": "notes.md", "file_url": "linsight/final_result/svid-1/f2.md"},
        ],
        "phantom_deliverables": ["summary.pdf"],
    }
    store.objects = {"linsight/final_result/svid-1/f1.docx": b"docx-bytes", "linsight/final_result/svid-1/f2.md": b"#"}
    answers = []
    for on in SWITCH_STATES:
        switch(on)
        store.version = _version(S.COMPLETED, output=output)
        view = await _call_api(app, "get", "/api/v2/workstation/tasks/svid-1")
        download = await _call_api(app, "get", "/api/v2/workstation/tasks/svid-1/files/f1")
        missing = await _call_api(app, "get", "/api/v2/workstation/tasks/svid-1/files/nope")
        answers.append(
            {
                "view": view.json(),
                "download": (download.status_code, download.content, download.headers["content-disposition"]),
                "missing": (missing.status_code, missing.json()["status_code"]),
            }
        )

    off, on = answers
    assert on == off
    result = off["view"]["data"]["result"]
    assert _shape(result["files"][0]) == {
        "file_id": "str",
        "file_name": "str",
        "file_type": "str",
        "size": "int",
        "primary": "bool",
    }
    assert [(f["file_id"], f["size"], f["primary"]) for f in result["files"]] == [("f1", 10, True), ("f2", 1, False)]
    assert result["unavailable_deliverables"] == [{"file_name": "summary.pdf", "reason": "not_generated"}]
    assert "/root/.cache" not in str(off["view"]) and "final_result" not in str(off["view"])
    assert off["download"][0] == 200 and off["download"][1] == b"docx-bytes"
    assert off["missing"][0] == 404


@pytest.mark.parametrize("status", [S.NOT_STARTED, S.IN_PROGRESS, S.COMPLETED, S.TERMINATED])
async def test_terminate(app, switch, store, status):
    answers = []
    for on in SWITCH_STATES:
        switch(on)
        store.version = _version(status, output={})
        store.terminated.clear()
        response = await _call_api(app, "post", "/api/v2/workstation/tasks/svid-1/terminate")
        answers.append((response.status_code, response.json(), list(store.terminated)))

    off, on = answers
    assert on == off
    if status in (S.NOT_STARTED, S.IN_PROGRESS):
        assert off[0] == 200 and off[1]["data"]["status"] == "terminated"
        assert off[2] == ["svid-1"]
    else:
        # A finished task cannot be stopped: the same 409 with the same status code.
        assert off[0] == 409 and off[2] == []


# ---------------------------------------------------------------------------
# AC-23: an unattended run never asks and never reads the inbox
# ---------------------------------------------------------------------------

# The model tries to ask anyway: the tool is not bound, so the graph answers with
# a tool error and the run goes on; nothing parks.
UNATTENDED_SCRIPT = [
    _call("write_todos", {"todos": TODOS}, "c1"),
    _call("ask_user", {"reason": "为了制定计划，请先确认", "questions": [{"question": "要看哪一章？"}]}, "c2"),
    _call("write_todos", {"todos": TODOS_DONE}, "c3"),
    AIMessage("研究完成"),
]


async def _run_open_api_task(monkeypatch: pytest.MonkeyPatch, tmp_path, *, unified: bool) -> SimpleNamespace:
    """One worker execution of an Open API task, from claim to the completion handler."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    env = _Env(monkeypatch, tmp_path, unified=unified)
    env.version.api_meta = dict(OPEN_API_META)
    final_files = [{"file_id": "f1", "file_name": "report.md", "file_url": "linsight/final_result/sv-9001/f1.md"}]
    monkeypatch.setattr(linsight_utils, "read_file_directory", AsyncMock(return_value=[]))
    monkeypatch.setattr(linsight_utils, "get_final_result_file", AsyncMock(return_value=final_files))
    monkeypatch.setattr(linsight_utils, "build_fallback_report_file", AsyncMock(return_value=final_files))
    monkeypatch.setattr(linsight_utils, "persist_task_turn_message", AsyncMock())
    drained: list[str] = []

    async def _drain_inbox(self, conversation_id: str) -> list[dict]:
        drained.append(conversation_id)
        return []

    monkeypatch.setattr(RunDispatchService, "drain_inbox", _drain_inbox)

    task = env.task()
    task._persist_report_citations = AsyncMock()
    model = _PlannedUnifiedModel(script=UNATTENDED_SCRIPT)
    monkeypatch.setattr(agent_factory, "_resolve_model", AsyncMock(return_value=(model, False)))
    async with task._acquire_session_run_lock():
        await task._enter_conversation_thread(env.version)
        backend = WorkspaceBackend(
            workspace_prefix=task._workspace_prefix(env.version), minio=env.store, file_dir=str(tmp_path)
        )
        agent = await agent_factory.create_linsight_agent(
            env.version, [], backend=backend, file_dir=str(tmp_path), checkpointer=env.saver
        )
        completed = await task._execute_agent_tasks(agent, env.version)
        assert completed is True
        await task._handle_task_completion(env.version)
    return SimpleNamespace(env=env, task=task, agent=agent, model=model, drained=drained)


async def test_unattended_never_asks(monkeypatch: pytest.MonkeyPatch, tmp_path):
    legacy = await _run_open_api_task(monkeypatch, tmp_path / "off", unified=False)
    unified = await _run_open_api_task(monkeypatch, tmp_path / "on", unified=True)

    for run in (legacy, unified):
        # The model really asked; the graph had no ask_user to run and went on.
        assert run.model.calls == len(UNATTENDED_SCRIPT)
        assert run.task._waiting_for_input is False
        assert run.env.version.status == S.COMPLETED
        assert "need_user_input" not in run.env.state.types()
        # Neither the tool nor an inbox middleware is part of the graph.
        nodes = list(run.agent.get_graph().nodes)
        assert not any("inbox" in str(node).lower() for node in nodes)
        assert run.drained == []

    # The unified channel wrote no ask_user event and the conversation ended idle, not parked.
    events = await unified.env.events()
    types = [event["type"] for event in events]
    assert types[0] == "run_started" and types[-1] == "run_finished"
    assert not any(kind.startswith("ask_user") for kind in types)
    assert (await unified.env.lease.get_state(CHAT)).status == run_lease.STATUS_IDLE
    assert unified.env.finished == [(CHAT, SVID)]

    # The legacy push channel and the run record are the same with the switch on and off.
    assert unified.env.state.types() == legacy.env.state.types()
    assert unified.env.version.output_result["answer"] == legacy.env.version.output_result["answer"]
    assert unified.env.version.output_result["final_files"] == legacy.env.version.output_result["final_files"]
    # The switch-off run left no unified runtime state behind.
    assert await legacy.env.run_keys() == []
