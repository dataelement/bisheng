"""F132 T067: deep-research session registration and per-round turn records (AC-10, AC-37).

Registration happens only at login-state endpoints (submit, continue, user-input,
and the daily-chat task-mode entry); the worker never registers. Every round
(first submit, every follow-up) opens its own summary row with its own turn id
bound to the round's task message row; an ask_user resume reuses the round's
turn id. A round ends exactly once in the ``finally`` of ``async_run`` /
``async_resume`` / ``async_continue`` (success, partial, terminated, direct
answer, failure), and not while parked waiting for the user. Unattended (Open
API) runs never touch memory.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.linsight.domain import task_exec as task_exec_mod
from bisheng.linsight.domain import utils as linsight_utils
from bisheng.linsight.domain.models.linsight_session_version import SessionVersionStatusEnum
from bisheng.linsight.domain.task_exec import LinsightWorkflowTask, UserTerminationError
from bisheng.memory.domain.models.memory_turn_record import KIND_SUMMARY
from bisheng.memory.domain.services.activity import MemoryActivity
from test.linsight._memory_doubles import (  # noqa: F401 - pytest fixtures
    CHAT,
    TENANT_A,
    USER_1,
    USER_2,
    add_task_message,
    cursor_row,
    memory_db,
    memory_runtime_config,
    memory_services,
    seed_session,
    turn_rows,
)

LOGIN = SimpleNamespace(user_id=USER_1, tenant_id=TENANT_A, user_name="u")


def _version(svid="sv-1", chat_id=CHAT, user_id=USER_1, status=SessionVersionStatusEnum.COMPLETED, api_meta=None):
    return SimpleNamespace(
        id=svid,
        session_id=chat_id,
        user_id=user_id,
        tenant_id=TENANT_A,
        status=status,
        api_meta=api_meta,
        question="问题",
        output_result={},
    )


# --------------------------------------------------------------------------- #
# Registration at the login-state endpoints
# --------------------------------------------------------------------------- #


class _FakeQueue:
    items: list = []

    def __init__(self, *args, **kwargs):
        pass

    async def put(self, data):
        _FakeQueue.items.append(data)

    async def put_head(self, data):
        _FakeQueue.items.append(data)


@pytest.fixture
def endpoint_env(monkeypatch, memory_db):
    from bisheng.linsight.api.endpoints import linsight as ep

    _FakeQueue.items = []
    monkeypatch.setattr("bisheng.linsight.worker.LinsightQueue", _FakeQueue)
    monkeypatch.setattr(ep, "get_redis_client", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(ep.MessageSessionDao, "touch_session", AsyncMock())
    monkeypatch.setattr(ep.LinsightSessionVersionDao, "batch_update_session_versions_status", AsyncMock())
    return ep


async def test_ac10_continue_endpoint_registers_session(endpoint_env, monkeypatch, memory_db):
    """AC-10: /workbench/continue (login state) registers the conversation."""
    ep = endpoint_env
    seed_session(memory_db, registered=False)
    monkeypatch.setattr(ep.LinsightSessionVersionDao, "get_by_id", AsyncMock(return_value=_version()))

    resp = await ep.continue_conversation(session_version_id="sv-1", question="再查一下", login_user=LOGIN)

    assert resp.status_code == 200
    row = cursor_row(memory_db)
    assert row is not None and row.user_id == USER_1 and row.tenant_id == TENANT_A


async def test_ac10_user_input_endpoint_registers_session(endpoint_env, monkeypatch, memory_db):
    """AC-10: /workbench/user-input (login state) registers the conversation."""
    ep = endpoint_env
    seed_session(memory_db, registered=False)
    monkeypatch.setattr(ep.LinsightSessionVersionDao, "get_by_id", AsyncMock(return_value=_version()))
    monkeypatch.setattr(ep.LinsightWorkbenchImpl, "human_participate_add_file", AsyncMock(return_value=[]))

    class _Manager:
        def __init__(self, session_version_id):
            pass

        async def get_execution_task(self, task_id):
            return None

    monkeypatch.setattr(ep, "LinsightStateMessageManager", _Manager)

    resp = await ep.user_input(
        session_version_id="sv-1", linsight_execute_task_id="sv-1", input_content="好的", files=None, login_user=LOGIN
    )

    assert resp.status_code == 200
    assert cursor_row(memory_db) is not None


async def test_ac10_submit_endpoint_registers_session(endpoint_env, monkeypatch, memory_db):
    """AC-10: /workbench/submit (login state) registers the new conversation."""
    ep = endpoint_env
    seed_session(memory_db, registered=False)
    monkeypatch.setattr(ep.SensitiveWordPolicyService, "evaluate_workbench_user_text", lambda *a, **k: None)
    monkeypatch.setattr(ep, "settings", SimpleNamespace(aget_all_config=AsyncMock(return_value={})))
    session = SimpleNamespace(chat_id=CHAT, model_dump=lambda: {"chat_id": CHAT})
    version = SimpleNamespace(public_dump=lambda: {"id": "sv-1"}, title=None)
    monkeypatch.setattr(ep.LinsightWorkbenchImpl, "submit_user_question", AsyncMock(return_value=(session, version)))
    monkeypatch.setattr(ep.LinsightWorkbenchImpl, "task_title_generate", AsyncMock(return_value={"task_title": "t"}))
    monkeypatch.setattr(ep.LinsightSessionVersionDao, "insert_one", AsyncMock())

    resp = await ep.submit_linsight_workbench(
        submit_obj=SimpleNamespace(question="查一下", session_id=None), login_user=LOGIN
    )
    events = [e async for e in resp.body_iterator]

    assert any(e.get("event") == "linsight_workbench_submit" for e in events)
    assert cursor_row(memory_db) is not None


async def test_ac10_endpoint_refuses_foreign_session(endpoint_env, monkeypatch, memory_db):
    """AC-10: a session owned by another user is not registered for the caller."""
    ep = endpoint_env
    seed_session(memory_db, user_id=USER_2, registered=False)
    monkeypatch.setattr(ep.LinsightSessionVersionDao, "get_by_id", AsyncMock(return_value=_version(user_id=USER_1)))

    await ep.continue_conversation(session_version_id="sv-1", question="q", login_user=LOGIN)

    assert cursor_row(memory_db) is None


async def test_ac10_task_turn_registers_before_enqueue_only_when_hooked(monkeypatch, memory_db):
    """AC-10: the daily task-mode entry registers before the run is queued; the
    shared submit core (also used by the Open API) registers nothing by itself."""
    from bisheng.linsight.domain.services.memory_turns import register_memory_session
    from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl
    from bisheng.workstation.domain.services import task_submit_service as tss

    seed_session(memory_db, registered=False)
    session = SimpleNamespace(chat_id=CHAT)
    version = _version()
    monkeypatch.setattr(LinsightWorkbenchImpl, "submit_user_question", AsyncMock(return_value=(session, version)))
    monkeypatch.setattr(tss, "_to_linsight_submit", lambda data: data, raising=False)
    monkeypatch.setattr(
        "bisheng.workstation.domain.services.chat_service._to_linsight_submit", lambda data: data, raising=False
    )
    monkeypatch.setattr(linsight_utils, "persist_task_turn_message", AsyncMock())
    seen_at_enqueue: list = []

    async def _enqueue(v):
        seen_at_enqueue.append(cursor_row(memory_db))

    monkeypatch.setattr(linsight_utils, "enqueue_session_for_execution", _enqueue)
    data = SimpleNamespace(files=None)

    await tss.submit_task_turn(data, LOGIN)
    assert seen_at_enqueue == [None]

    await tss.submit_task_turn(data, LOGIN, on_session_created=lambda s, v: register_memory_session(s.chat_id, LOGIN))
    assert seen_at_enqueue[-1] is not None and seen_at_enqueue[-1].user_id == USER_1


async def test_ac10_daily_task_mode_entry_passes_registration_hook(monkeypatch, memory_db):
    """AC-10: the logged-in daily chat task-mode path hands the registration hook to the submit core."""
    from bisheng.workstation.domain.services import chat_service
    from bisheng.workstation.domain.services import task_submit_service as tss

    seed_session(memory_db, registered=False)
    captured: dict = {}

    async def _fake_submit(data, login_user, **kwargs):
        captured.update(kwargs)
        session = SimpleNamespace(chat_id=CHAT, name="已有标题")
        version = _version()
        await kwargs["on_session_created"](session, version)
        return session, version

    monkeypatch.setattr(tss, "submit_task_turn", _fake_submit)
    monkeypatch.setattr(chat_service, "workbench_tenant_id", lambda user: TENANT_A)
    monkeypatch.setattr(chat_service.SensitiveWordPolicyService, "evaluate_workbench_user_text", lambda *a: None)
    monkeypatch.setattr(chat_service.LLMService, "get_bisheng_llm", AsyncMock(return_value=SimpleNamespace()))
    data = SimpleNamespace(text="查一下", conversationId=None, model="m", task_mode=True)

    from bisheng.memory.domain.services.gate import MemoryGate

    async def _register(chat_id):
        await MemoryGate.open(chat_id, LOGIN)

    # The logged-in daily endpoint injects memory_register (Wave 8); only then is a hook passed.
    await chat_service._task_mode_stream_completion(None, data, LOGIN, memory_register=_register)

    assert captured["on_session_created"] is not None
    assert cursor_row(memory_db) is not None

    captured.clear()
    monkeypatch.setattr(tss, "submit_task_turn", _fake_submit_no_hook := AsyncMock(return_value=(SimpleNamespace(chat_id=CHAT, name="已有标题"), _version())))
    await chat_service._task_mode_stream_completion(None, data, LOGIN)
    assert _fake_submit_no_hook.call_args.kwargs.get("on_session_created") is None


# --------------------------------------------------------------------------- #
# Rounds in the worker
# --------------------------------------------------------------------------- #


class _FakeStateManager:
    def __init__(self):
        self.messages: list = []

    async def push_message(self, message):
        self.messages.append(message)

    async def restamp_clarify_answers(self, svid):
        return None


@pytest.fixture
def worker_env(monkeypatch, memory_services, memory_db):
    """A LinsightWorkflowTask whose heavy internals are stubbed; memory calls are real."""
    state = SimpleNamespace(task_message_ids={}, end_calls=[], versions={}, outcome={"run": "ok"})

    async def _feedback(chat_id):
        return {svid: {"message_id": mid, "liked": 0} for svid, mid in state.task_message_ids.items()}

    monkeypatch.setattr(linsight_utils, "get_task_feedback_by_version", _feedback)
    monkeypatch.setattr(linsight_utils, "persist_task_turn_message", AsyncMock())
    monkeypatch.setattr(task_exec_mod, "ensure_linsight_permission_runtime", AsyncMock())
    monkeypatch.setattr(task_exec_mod.LinsightWorkbenchImpl, "init_linsight_config_tools", AsyncMock(return_value=[]))
    monkeypatch.setattr(task_exec_mod.ToolServices, "init_linsight_tools", AsyncMock(return_value=[]))
    monkeypatch.setattr("bisheng.linsight.domain.services.checkpointer.make_checkpointer", lambda: None)

    original_end = MemoryActivity.end_turn.__func__

    async def _spy_end(cls, chat_id, last_message_id, enabled, now=None):
        state.end_calls.append((chat_id, last_message_id, enabled))
        return await original_end(cls, chat_id, last_message_id, enabled, now)

    monkeypatch.setattr(MemoryActivity, "end_turn", classmethod(_spy_end))

    def make(version):
        task = LinsightWorkflowTask()
        manager = _FakeStateManager()

        @asynccontextmanager
        async def _managed(self_):
            self_._state_manager = manager
            yield version

        monkeypatch.setattr(task, "_managed_execution", _managed.__get__(task))
        monkeypatch.setattr(task, "_managed_resume", _managed.__get__(task))
        monkeypatch.setattr(task, "_restore_tenant_context", AsyncMock(return_value=None))
        for name in (
            "_seed_workspace_from_previous",
            "_sync_workspace_originals",
            "_provision_session_skills",
            "_update_session_status",
            "_handle_user_termination",
            "_handle_execution_error",
        ):
            monkeypatch.setattr(task, name, AsyncMock())
        monkeypatch.setattr(task, "_get_round_llm", AsyncMock(return_value=None))
        monkeypatch.setattr(task, "_resolve_allowed_knowledge_ids", AsyncMock(return_value=set()))
        monkeypatch.setattr(task, "_create_agent", AsyncMock(return_value=SimpleNamespace()))

        async def _agent_tasks(agent, session_model):
            outcome = state.outcome["run"]
            if outcome == "waiting":
                task._waiting_for_input = True
            if outcome == "fail":
                raise RuntimeError("model down")
            return outcome != "terminated"

        async def _drive(agent, session_model, value):
            outcome = state.outcome["run"]
            if outcome == "waiting":
                task._waiting_for_input = True
            if outcome == "terminated":
                raise UserTerminationError("stop")
            if outcome == "fail":
                raise RuntimeError("model down")

        monkeypatch.setattr(task, "_execute_agent_tasks", _agent_tasks)
        monkeypatch.setattr(task, "_drive_continue", _drive)
        monkeypatch.setattr(task, "_drive_resume", _drive)
        monkeypatch.setattr(task, "_handle_task_completion", AsyncMock())
        task.manager = manager
        return task

    state.make = make
    return state


async def _first_round(env, memory_db, svid="sv-1", outcome="ok"):
    env.task_message_ids[svid] = add_task_message(memory_db, svid=svid)
    env.outcome["run"] = outcome
    task = env.make(_version(svid=svid))
    await task.async_run(svid, tenant_id=TENANT_A)
    return task


async def test_ac37_each_round_gets_its_own_summary_and_turn_id(worker_env, memory_db):
    """AC-37: the first submit and each later round (new svid) open their own summary row."""
    seed_session(memory_db)

    await _first_round(worker_env, memory_db, "sv-1")
    await _first_round(worker_env, memory_db, "sv-2")

    rows = turn_rows(memory_db, KIND_SUMMARY)
    assert len(rows) == 2
    assert rows[0].turn_id != rows[1].turn_id
    assert [r.message_id for r in rows] == [worker_env.task_message_ids["sv-1"], worker_env.task_message_ids["sv-2"]]
    assert all(r.scene_class == "linsight" and r.chat_id == CHAT for r in rows)
    assert all(r.consolidated is False for r in rows)


async def test_ac37_continue_round_has_own_turn_and_is_not_auto_consolidated(worker_env, memory_db):
    """AC-37 / P-01 option C: a /continue round gets a new turn id, flagged as not to be consolidated."""
    seed_session(memory_db)
    await _first_round(worker_env, memory_db, "sv-1")

    task = worker_env.make(_version(svid="sv-1"))
    await task.async_continue("sv-1", "再追问一次", tenant_id=TENANT_A)

    rows = turn_rows(memory_db, KIND_SUMMARY)
    assert len(rows) == 2 and rows[0].turn_id != rows[1].turn_id
    assert rows[1].consolidated is True
    assert rows[1].message_id == worker_env.task_message_ids["sv-1"]


async def test_ac37_resume_after_ask_user_reuses_round_turn_id(worker_env, memory_db):
    """AC-37: answering ask_user continues the same round; no new summary, no end while parked."""
    seed_session(memory_db)
    await _first_round(worker_env, memory_db, "sv-1", outcome="waiting")
    assert worker_env.end_calls == []  # parked: the round has not ended

    worker_env.outcome["run"] = "ok"
    task = worker_env.make(_version(svid="sv-1"))
    await task.async_resume("sv-1", user_input="好的", tenant_id=TENANT_A)

    rows = turn_rows(memory_db, KIND_SUMMARY)
    assert len(rows) == 1
    assert task._memory.ctx.turn_id == rows[0].turn_id
    assert len(worker_env.end_calls) == 1 and rows[0].ended is True


@pytest.mark.parametrize("outcome", ["ok", "terminated", "fail"])
async def test_ac37_round_end_registers_activity_once(worker_env, memory_db, outcome):
    """AC-37: success / partial / direct answer (all finish through completion), termination and
    failure each end the round exactly once and mark the session pending."""
    seed_session(memory_db)
    await _first_round(worker_env, memory_db, "sv-1", outcome=outcome)

    mid = worker_env.task_message_ids["sv-1"]
    assert worker_env.end_calls == [(CHAT, mid, True)]
    row = cursor_row(memory_db)
    assert row.state == "pending" and row.last_message_id == mid
    assert turn_rows(memory_db, KIND_SUMMARY)[0].ended is True


@pytest.mark.parametrize("outcome", ["ok", "terminated", "fail"])
async def test_ac37_continue_round_end_registers_activity_once(worker_env, memory_db, outcome):
    """AC-37: a continue round ends once on every exit, including the termination that skips
    ``_handle_user_termination`` on this path."""
    seed_session(memory_db)
    worker_env.task_message_ids["sv-1"] = add_task_message(memory_db, svid="sv-1")
    worker_env.outcome["run"] = outcome

    task = worker_env.make(_version(svid="sv-1"))
    await task.async_continue("sv-1", "追问", tenant_id=TENANT_A)

    assert worker_env.end_calls == [(CHAT, worker_env.task_message_ids["sv-1"], True)]


async def test_ac37_memory_disabled_creates_no_summary_and_advances_watermark(worker_env, memory_db):
    """AC-37 / AC-41: with "my memory" off the round writes no summary and is skipped for good."""
    seed_session(memory_db, enabled=False)

    await _first_round(worker_env, memory_db, "sv-1")

    assert turn_rows(memory_db) == []
    mid = worker_env.task_message_ids["sv-1"]
    assert worker_env.end_calls == [(CHAT, mid, False)]
    row = cursor_row(memory_db)
    assert row.watermark_message_id == mid and row.state == "idle"


async def test_ac10_unregistered_session_writes_nothing(worker_env, memory_db):
    """AC-10: a session that never passed a login endpoint gets no summary row."""
    seed_session(memory_db, registered=False)

    await _first_round(worker_env, memory_db, "sv-1")

    assert turn_rows(memory_db) == []
    assert cursor_row(memory_db) is None


async def test_ac10_unattended_run_never_touches_memory(worker_env, memory_db):
    """AC-10: an Open API (unattended) run reads and writes no memory even on a registered chat."""
    seed_session(memory_db)
    worker_env.task_message_ids["sv-1"] = add_task_message(memory_db, svid="sv-1")
    task = worker_env.make(_version(svid="sv-1", api_meta={"channel": "open_api_v2"}))

    await task.async_run("sv-1", tenant_id=TENANT_A)

    assert turn_rows(memory_db) == []
    assert worker_env.end_calls == []
    assert task._memory.tools() == []
