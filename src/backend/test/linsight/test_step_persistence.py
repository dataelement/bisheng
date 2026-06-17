"""F035 follow-up: step-persistence fixes (design-增量-步骤持久化修复.md).

Two defects:
  1. Streaming thinking was persisted one-history-entry-per-token. The manager
     now upserts by call_id: thinking deltas accumulate into ONE entry, tool
     start/end collapse into ONE end frame. NeedUserInput (no call_id) still
     appends so set_user_input can read history[-1].
  2. Planning/wrap-up/direct-answer tool steps route to task_id = svid but had
     no DB row, so they were dropped on refresh. A session-level pseudo task row
     (id = svid) now carries them; get_execute_task_detail drops it when empty
     and surfaces it first otherwise.
"""

from unittest.mock import AsyncMock, MagicMock

from bisheng.linsight.domain.models.linsight_execute_task import (
    ExecuteTaskStatusEnum,
    ExecuteTaskTypeEnum,
    LinsightExecuteTask,
)
from bisheng_langchain.linsight.event import ExecStep, NeedUserInput


def _make_manager(monkeypatch):
    """Build a LinsightStateMessageManager with a stateful in-memory history.

    get_execution_task reads from / update_by_id writes to a shared dict so the
    accumulation across add_execution_task_step calls is observable, while Redis
    writes are stubbed.
    """
    from bisheng.linsight.domain.services import state_message_manager as smm

    monkeypatch.setattr(smm, "get_redis_client_sync", lambda: MagicMock())
    mgr = smm.LinsightStateMessageManager("svid")
    mgr._redis_client = MagicMock()
    mgr._redis_client.aset = AsyncMock()

    store = {"history": []}
    task = LinsightExecuteTask(
        id="t1",
        session_version_id="svid",
        task_type=ExecuteTaskTypeEnum.SINGLE,
        status=ExecuteTaskStatusEnum.IN_PROGRESS,
        history=[],
    )

    async def fake_get(task_id):
        task.history = list(store["history"])
        return task

    async def fake_update(task_id, **kwargs):
        if "history" in kwargs:
            store["history"] = kwargs["history"]
        return task

    mgr.get_execution_task = fake_get
    monkeypatch.setattr(smm.LinsightExecuteTaskDao, "update_by_id", fake_update)
    return mgr, store


def _thinking(call_id, text):
    return ExecStep(
        task_id="t1",
        call_id=call_id,
        call_reason="",
        name="thinking",
        output=text,
        step_type="thinking",
        status="end",
    )


def _tool(call_id, status, output=None, params=None):
    return ExecStep(
        task_id="t1",
        call_id=call_id,
        call_reason="",
        name="some_tool",
        params=params,
        output=output,
        step_type="tool",
        status=status,
    )


async def test_thinking_deltas_collapse_to_one_entry(monkeypatch):
    mgr, store = _make_manager(monkeypatch)

    await mgr.add_execution_task_step("t1", _thinking("c1", "Hello "))
    await mgr.add_execution_task_step("t1", _thinking("c1", "world"))
    await mgr.add_execution_task_step("t1", _thinking("c1", "!"))

    assert len(store["history"]) == 1
    assert store["history"][0]["output"] == "Hello world!"
    assert store["history"][0]["step_type"] == "thinking"


async def test_tool_start_end_collapse_to_one_end_frame(monkeypatch):
    mgr, store = _make_manager(monkeypatch)

    await mgr.add_execution_task_step("t1", _tool("c2", "start", params={"a": 1}))
    await mgr.add_execution_task_step("t1", _tool("c2", "end", output="result", params={"a": 1}))

    assert len(store["history"]) == 1
    entry = store["history"][0]
    assert entry["status"] == "end"
    assert entry["output"] == "result"
    assert entry["params"] == {"a": 1}


async def test_distinct_call_ids_kept_separate(monkeypatch):
    mgr, store = _make_manager(monkeypatch)

    await mgr.add_execution_task_step("t1", _thinking("c1", "think"))
    await mgr.add_execution_task_step("t1", _tool("c2", "start"))
    await mgr.add_execution_task_step("t1", _tool("c2", "end", output="r"))

    assert len(store["history"]) == 2


async def test_need_user_input_without_call_id_appends(monkeypatch):
    mgr, store = _make_manager(monkeypatch)

    await mgr.add_execution_task_step("t1", _thinking("c1", "planning"))
    nui = NeedUserInput(task_id="t1", call_reason="please clarify", step_type="call_user_input")
    await mgr.add_execution_task_step("t1", nui)

    assert len(store["history"]) == 2
    # set_user_input relies on the call_user_input step being history[-1].
    assert store["history"][-1]["step_type"] == "call_user_input"


# ---------------------------------------------------------------------------
# Problem 2: session-level pseudo task row
# ---------------------------------------------------------------------------


async def test_ensure_session_pseudo_task_creates_once(monkeypatch):
    from bisheng.linsight.domain import task_exec as te

    created = []

    async def fake_get_by_id(task_id):
        return None  # not yet created

    async def fake_batch_create(tasks):
        created.extend(tasks)
        return tasks

    monkeypatch.setattr(te.LinsightExecuteTaskDao, "get_by_id", fake_get_by_id)
    monkeypatch.setattr(te.LinsightExecuteTaskDao, "batch_create_tasks", fake_batch_create)

    exec_task = te.LinsightWorkflowTask()
    session = MagicMock()
    session.id = "svid-123"

    await exec_task._ensure_session_pseudo_task(session)

    assert len(created) == 1
    row = created[0]
    assert row.id == "svid-123"
    assert row.session_version_id == "svid-123"
    assert (row.task_data or {}).get("is_session_global") is True


async def test_ensure_session_pseudo_task_idempotent(monkeypatch):
    from bisheng.linsight.domain import task_exec as te

    created = []

    async def fake_get_by_id(task_id):
        return MagicMock()  # already exists

    async def fake_batch_create(tasks):
        created.extend(tasks)
        return tasks

    monkeypatch.setattr(te.LinsightExecuteTaskDao, "get_by_id", fake_get_by_id)
    monkeypatch.setattr(te.LinsightExecuteTaskDao, "batch_create_tasks", fake_batch_create)

    exec_task = te.LinsightWorkflowTask()
    session = MagicMock()
    session.id = "svid-123"

    await exec_task._ensure_session_pseudo_task(session)

    assert created == []  # no duplicate insert


async def test_direct_answer_greeting_skips_report_despite_pseudo_task(monkeypatch):
    """A trivial greeting plans no todo. The always-present session pseudo task
    must NOT trigger report synthesis (regression guard for F035 problem 2):
    _handle_direct_answer_completion gates on REAL planned todos only.
    """
    from bisheng.linsight.domain import task_exec as te

    exec_task = te.LinsightWorkflowTask()
    exec_task.session_version_id = "svid"
    exec_task._last_assistant_text = "你好！有什么可以帮你的？"
    exec_task.file_dir = "/tmp/nonexistent-linsight"

    sm = MagicMock()
    sm.set_session_version_info = AsyncMock()
    # Only the session-global pseudo task is present (no planned todos).
    sm.get_execution_tasks = AsyncMock(return_value=[_pseudo([])])
    sm.update_execution_task_status = AsyncMock()
    sm.push_message = AsyncMock()
    exec_task._state_manager = sm

    called = {"final": False, "fallback": False}

    async def _final(*a, **k):
        called["final"] = True
        return []

    async def _fallback(*a, **k):
        called["fallback"] = True
        return [{"f": 1}]

    monkeypatch.setattr(te.linsight_execute_utils, "get_final_result_file", _final)
    monkeypatch.setattr(te.linsight_execute_utils, "build_fallback_report_file", _fallback)
    monkeypatch.setattr(te.linsight_execute_utils, "read_file_directory", AsyncMock(return_value=[]))
    monkeypatch.setattr(te.linsight_execute_utils, "persist_task_turn_message", AsyncMock())

    session = MagicMock()
    session.id = "svid"
    session.model_dump = MagicMock(return_value={})

    await exec_task._handle_direct_answer_completion(session)

    # No report synthesized for a greeting, even though the pseudo task exists.
    assert called["final"] is False
    assert called["fallback"] is False
    assert session.output_result["final_files"] == []


def _pseudo(history):
    return LinsightExecuteTask(
        id="svid",
        session_version_id="svid",
        parent_task_id=None,
        task_type=ExecuteTaskTypeEnum.SINGLE,
        status=ExecuteTaskStatusEnum.IN_PROGRESS,
        task_data={"name": "执行准备", "is_session_global": True},
        history=history,
    )


def _real_task(tid):
    return LinsightExecuteTask(
        id=tid,
        session_version_id="svid",
        parent_task_id=None,
        previous_task_id=None,
        next_task_id=None,
        task_type=ExecuteTaskTypeEnum.SINGLE,
        status=ExecuteTaskStatusEnum.SUCCESS,
        task_data={"name": f"task-{tid}"},
        history=[],
    )


async def test_detail_drops_empty_pseudo_task(monkeypatch):
    from bisheng.linsight.domain.services import workbench_impl as wi

    tasks = [_pseudo([]), _real_task("aaaa")]

    async def fake_get(svid, *a, **k):
        return tasks

    monkeypatch.setattr(wi.LinsightExecuteTaskDao, "get_by_session_version_id", fake_get)

    result = await wi.LinsightWorkbenchImpl.get_execute_task_detail("svid")
    ids = [node["id"] for node in result]
    assert "svid" not in ids
    assert "aaaa" in ids


async def test_detail_surfaces_nonempty_pseudo_first(monkeypatch):
    from bisheng.linsight.domain.services import workbench_impl as wi

    tasks = [_real_task("aaaa"), _pseudo([{"call_id": "c1", "output": "x"}])]

    async def fake_get(svid, *a, **k):
        return tasks

    monkeypatch.setattr(wi.LinsightExecuteTaskDao, "get_by_session_version_id", fake_get)

    result = await wi.LinsightWorkbenchImpl.get_execute_task_detail("svid")
    ids = [node["id"] for node in result]
    assert ids[0] == "svid"  # global pseudo task first
    assert "aaaa" in ids


# ---------------------------------------------------------------------------
# F035 reload parity: clarify answers survive resume re-stream
# ---------------------------------------------------------------------------


def _make_answer_manager(monkeypatch, history, task_data):
    """Manager whose task carries a stateful history + task_data store.

    Unlike _make_manager this also tracks task_data so set_user_input's
    clarify_answers append and restamp_clarify_answers can be observed.
    """
    from bisheng.linsight.domain.services import state_message_manager as smm

    monkeypatch.setattr(smm, "get_redis_client_sync", lambda: MagicMock())
    mgr = smm.LinsightStateMessageManager("svid")
    mgr._redis_client = MagicMock()
    mgr._redis_client.aset = AsyncMock()

    store = {"history": list(history), "task_data": dict(task_data)}
    task = LinsightExecuteTask(
        id="svid",
        session_version_id="svid",
        task_type=ExecuteTaskTypeEnum.SINGLE,
        status=ExecuteTaskStatusEnum.IN_PROGRESS,
        task_data=dict(task_data),
        history=list(history),
    )

    async def fake_get(task_id):
        task.history = [dict(h) for h in store["history"]]
        task.task_data = dict(store["task_data"])
        return task

    async def fake_update(task_id, **kwargs):
        if "history" in kwargs:
            store["history"] = kwargs["history"]
        if "task_data" in kwargs:
            store["task_data"] = kwargs["task_data"]
        return task

    mgr.get_execution_task = fake_get
    monkeypatch.setattr(smm.LinsightExecuteTaskDao, "update_by_id", fake_update)
    return mgr, store


def _clarify_entry(reason, answered=False, answer=None):
    entry = {"step_type": "call_user_input", "call_reason": reason, "params": {"tool_calls": []}}
    if answered:
        entry["is_completed"] = True
        entry["user_input"] = answer
    return entry


async def test_restamp_reapplies_answers_after_clobber(monkeypatch):
    # Two clarifies were answered, but a resume re-stream wiped the per-step stamp
    # (entries back to unanswered). The authoritative answers live in task_data.
    history = [
        {"step_type": "thinking", "call_id": "th1", "output": "planning"},
        _clarify_entry("q1"),
        _clarify_entry("q2"),
    ]
    mgr, store = _make_answer_manager(monkeypatch, history, {"clarify_answers": ["male, 40", "80kg"]})

    await mgr.restamp_clarify_answers("svid")

    clarifies = [h for h in store["history"] if h["step_type"] == "call_user_input"]
    assert [c["is_completed"] for c in clarifies] == [True, True]
    assert [c["user_input"] for c in clarifies] == ["male, 40", "80kg"]


async def test_restamp_leaves_still_pending_clarify_untouched(monkeypatch):
    # One answer recorded but two clarifies present (the 2nd is genuinely pending).
    history = [_clarify_entry("q1"), _clarify_entry("q2")]
    mgr, store = _make_answer_manager(monkeypatch, history, {"clarify_answers": ["male, 40"]})

    await mgr.restamp_clarify_answers("svid")

    clarifies = [h for h in store["history"] if h["step_type"] == "call_user_input"]
    assert clarifies[0].get("is_completed") is True
    assert clarifies[0]["user_input"] == "male, 40"
    assert clarifies[1].get("is_completed") is not True  # pending — untouched


async def test_restamp_noop_without_recorded_answers(monkeypatch):
    history = [_clarify_entry("q1")]
    mgr, store = _make_answer_manager(monkeypatch, history, {})

    await mgr.restamp_clarify_answers("svid")

    assert store["history"][0].get("is_completed") is not True
