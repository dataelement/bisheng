"""F132 T069: resident memory, experience items and memory tools in deep research.

AC-21, AC-28, AC-51, AC-55, AC-61, AC-87. The memory text (tool guidance +
resident block + experience block) is fetched once when the round starts and
appended by a ``wrap_model_call`` middleware placed after the skills block and
before the citation / language tails. The two memory tools are appended inside
``_generate_tools`` (fresh, continue and resume paths), never reach the
researcher subagent, and the prompt describes them only when they are bound.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import SystemMessage

from bisheng.linsight.domain import task_exec as task_exec_mod
from bisheng.linsight.domain import utils as linsight_utils
from bisheng.linsight.domain.models.linsight_session_version import SessionVersionStatusEnum
from bisheng.linsight.domain.services import agent_factory
from bisheng.linsight.domain.services.memory_turns import (
    MEMORY_PROMPT_HEADER,
    LinsightMemoryMiddleware,
    LinsightMemoryRound,
)
from bisheng.linsight.domain.task_exec import LinsightWorkflowTask
from bisheng.memory.domain.models.memory_turn_record import KIND_SUMMARY
from bisheng.memory.domain.ports import MemoryContext
from bisheng.memory.domain.services import metrics as m
from bisheng.memory.domain.services.resident import EXPERIENCE_HEADER, RESIDENT_HEADER
from test.linsight._memory_doubles import (  # noqa: F401 - pytest fixtures
    CHAT,
    TENANT_A,
    USER_1,
    add_task_message,
    counter,
    memory_db,
    memory_runtime_config,
    memory_services,
    seed_session,
    turn_rows,
)

MEMORY_TOOL_NAMES = {"memory_write", "memory_search"}


def _version(svid="sv-1", api_meta=None):
    return SimpleNamespace(
        id=svid,
        session_id=CHAT,
        user_id=USER_1,
        tenant_id=TENANT_A,
        status=SessionVersionStatusEnum.IN_PROGRESS,
        api_meta=api_meta,
        question="问题",
        output_result={},
        skills=None,
        model=None,
    )


async def _remember(memory_services, content, item_type="preference"):
    ctx = MemoryContext(tenant_id=TENANT_A, user_id=USER_1, chat_id=CHAT, turn_id=None, scene="daily")
    return await memory_services.service.write(ctx, "remember", content=content, type=item_type)


class _FakeReq:
    def __init__(self, system_message):
        self.system_message = system_message

    def override(self, *, system_message):
        return _FakeReq(system_message)


def _appended_text(middleware) -> str:
    captured = {}

    def handler(req):
        captured["req"] = req
        return "RESP"

    middleware.wrap_model_call(_FakeReq(SystemMessage("BASE")), handler)
    return captured["req"].system_message.content_blocks[-1]["text"]


# --------------------------------------------------------------------------- #
# Round text: resident + experience, fetched once (AC-51, AC-55)
# --------------------------------------------------------------------------- #


@pytest.fixture
def task_message(monkeypatch, memory_db):
    ids = {}

    async def _feedback(chat_id):
        return {svid: {"message_id": mid, "liked": 0} for svid, mid in ids.items()}

    monkeypatch.setattr(linsight_utils, "get_task_feedback_by_version", _feedback)

    def make(svid="sv-1"):
        ids[svid] = add_task_message(memory_db, svid=svid)
        return ids[svid]

    return make


async def test_ac51_ac55_round_text_carries_resident_and_experience(memory_services, memory_db, task_message):
    """AC-51 / AC-55: the round prompt holds the resident block and the experience block."""
    seed_session(memory_db)
    task_message()
    await _remember(memory_services, "用户偏好用表格呈现对比")
    await _remember(memory_services, "做行业研究时先列数据来源清单", item_type="experience")

    round_ = LinsightMemoryRound()
    await round_.begin(_version())
    text = round_.prompt()

    assert MEMORY_PROMPT_HEADER in text and "memory_search" in text and "memory_write" in text
    assert RESIDENT_HEADER in text and "用户偏好用表格呈现对比" in text
    assert EXPERIENCE_HEADER in text and "做行业研究时先列数据来源清单" in text
    # experience items are not resident
    assert "做行业研究时先列数据来源清单" not in round_.resident_text


async def test_ac51_text_fetched_once_at_round_start(memory_services, memory_db, task_message):
    """AC-51: items written mid-task do not change the text the model keeps receiving."""
    seed_session(memory_db)
    task_message()
    await _remember(memory_services, "用户在台北工作")
    round_ = LinsightMemoryRound()
    await round_.begin(_version())
    middleware = LinsightMemoryMiddleware(round_.prompt())

    before = _appended_text(middleware)
    await _remember(memory_services, "用户喜欢东京的咖啡馆")
    after = _appended_text(middleware)

    assert before == after and "用户在台北工作" in after and "东京" not in after


async def test_ac87_resident_only_round_has_no_attribution(memory_services, memory_db, task_message):
    """AC-87: a round that only injected resident memory is not attributed, so nothing is streamed."""
    seed_session(memory_db)
    task_message()
    await _remember(memory_services, "用户偏好简体中文")
    pushed: list = []

    async def _push(data):
        pushed.append(data)

    round_ = LinsightMemoryRound()
    await round_.begin(_version(), push=_push)
    await round_.end(False)

    assert pushed == []
    summary = turn_rows(memory_db, KIND_SUMMARY)[0]
    assert summary.resident_rev is not None and summary.scene_class == "linsight"


async def test_ac87_empty_resident_round_has_no_attribution(memory_services, memory_db, task_message):
    """AC-87: nothing injected and nothing retrieved -> no signal, summary without resident rev."""
    seed_session(memory_db)
    task_message()
    pushed: list = []

    async def _push(data):
        pushed.append(data)

    round_ = LinsightMemoryRound()
    await round_.begin(_version(), push=_push)
    await round_.end(False)

    assert pushed == []
    assert turn_rows(memory_db, KIND_SUMMARY)[0].resident_rev is None


async def test_ac61_injection_failure_keeps_tools_and_counts(memory_services, memory_db, task_message, monkeypatch):
    """AC-61: a failing resident read leaves the task running with tools and counts one failure."""
    seed_session(memory_db)
    task_message()

    async def _boom(*args, **kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr(memory_services.resident, "resident", _boom)
    round_ = LinsightMemoryRound()
    await round_.begin(_version())

    assert {t.name for t in round_.tools()} == MEMORY_TOOL_NAMES
    assert RESIDENT_HEADER not in round_.prompt()
    assert await counter(memory_services.kv, TENANT_A, m.INJECT_FAILED) == 1


# --------------------------------------------------------------------------- #
# Agent assembly: middleware placement and prompt <-> tool lockstep
# --------------------------------------------------------------------------- #


@pytest.fixture
def factory_env(monkeypatch):
    captured: dict = {}

    def fake_create_deep_agent(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(name="agent")

    from bisheng.core.config.settings import LinsightConf

    monkeypatch.setattr("deepagents.create_deep_agent", fake_create_deep_agent)
    monkeypatch.setattr(agent_factory, "_resolve_model", AsyncMock(return_value=(SimpleNamespace(), False)))
    monkeypatch.setattr(agent_factory, "settings", SimpleNamespace(get_linsight_conf=lambda: LinsightConf()))
    return captured


def _names(middlewares) -> list[str]:
    return [getattr(mw, "name", type(mw).__name__) for mw in middlewares]


def _memory_tools():
    from bisheng.memory.domain.services.tools import build_memory_tools

    ctx = MemoryContext(tenant_id=TENANT_A, user_id=USER_1, chat_id=CHAT, turn_id="t1", scene="linsight")
    return build_memory_tools(ctx, service=SimpleNamespace(), search=SimpleNamespace())


async def test_ac28_memory_middleware_sits_before_tails_and_subagent_gets_no_memory(factory_env):
    """AC-28 / AC-51: memory context goes before the citation and language tails; the researcher
    subagent neither gets the memory tools nor the memory text."""
    from bisheng.tool.domain.langchain.linsight_knowledge import SearchKnowledgeBase

    session = SimpleNamespace(id="sv-1", session_id=CHAT, tenant_id=TENANT_A, user_id=USER_1, question="q")
    await agent_factory.create_linsight_agent(
        session, [SearchKnowledgeBase(), *_memory_tools()], memory_prompt=MEMORY_PROMPT_HEADER + "\n正文"
    )

    main = _names(factory_env["middleware"])
    assert "LinsightMemoryContext" in main
    assert main.index("LinsightMemoryContext") < main.index("LinsightCitationTail") < main.index("LinsightLanguageTail")
    assert MEMORY_TOOL_NAMES <= {t.name for t in factory_env["tools"]}

    researcher = factory_env["subagents"][0]
    assert not MEMORY_TOOL_NAMES & {t.name for t in researcher.get("tools") or []}
    assert "LinsightMemoryContext" not in _names(researcher["middleware"])


async def test_ac28_memory_text_absent_when_tools_absent(factory_env):
    """prompt <-> tool lockstep: a memory prompt without bound memory tools is dropped."""
    session = SimpleNamespace(id="sv-1", session_id=CHAT, tenant_id=TENANT_A, user_id=USER_1, question="q")

    await agent_factory.create_linsight_agent(session, [], memory_prompt=MEMORY_PROMPT_HEADER)

    assert "LinsightMemoryContext" not in _names(factory_env["middleware"])


# --------------------------------------------------------------------------- #
# Worker paths: fresh, continue and resume all bind tools and text
# --------------------------------------------------------------------------- #


class _FakeStateManager:
    def __init__(self):
        self.messages: list = []

    async def push_message(self, message):
        self.messages.append(message)

    async def restamp_clarify_answers(self, svid):
        return None

    async def set_session_version_info(self, session_model):
        return None


class _FakeScope:
    def __init__(self, *args, **kwargs):
        self.enabled = False

    async def load(self):
        return None

    async def pin_contract(self):
        return None


@pytest.fixture
def worker(monkeypatch, memory_services, memory_db, task_message, tmp_path):
    """A LinsightWorkflowTask driving the real _generate_tools / _create_agent with stubbed IO."""
    state = SimpleNamespace(agent_kwargs=[], on_run=None)

    monkeypatch.setattr(linsight_utils, "persist_task_turn_message", AsyncMock())
    monkeypatch.setattr(task_exec_mod, "ensure_linsight_permission_runtime", AsyncMock())
    monkeypatch.setattr(task_exec_mod.LinsightWorkbenchImpl, "init_linsight_config_tools", AsyncMock(return_value=[]))
    monkeypatch.setattr(task_exec_mod.ToolServices, "init_linsight_tools", AsyncMock(return_value=[]))
    monkeypatch.setattr(task_exec_mod, "get_minio_storage", AsyncMock(return_value=SimpleNamespace(bucket="b")))
    monkeypatch.setattr("bisheng.linsight.domain.services.checkpointer.make_checkpointer", lambda: None)
    monkeypatch.setattr("bisheng.citation.domain.services.linsight_citation_scope.LinsightCitationScope", _FakeScope)

    async def _create(**kwargs):
        state.agent_kwargs.append(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(task_exec_mod, "create_linsight_agent", _create)

    def make(version):
        task = LinsightWorkflowTask()
        manager = _FakeStateManager()

        @asynccontextmanager
        async def _managed(self_):
            self_._state_manager = manager
            self_.file_dir = str(tmp_path)
            yield version

        monkeypatch.setattr(task, "_managed_execution", _managed.__get__(task))
        monkeypatch.setattr(task, "_managed_resume", _managed.__get__(task))
        monkeypatch.setattr(task, "_restore_tenant_context", AsyncMock(return_value=None))
        for name in (
            "_seed_workspace_from_previous",
            "_sync_workspace_originals",
            "_update_session_status",
            "_handle_execution_error",
            "_handle_task_completion",
        ):
            monkeypatch.setattr(task, name, AsyncMock())
        monkeypatch.setattr(
            task, "_provision_session_skills", AsyncMock(return_value=SimpleNamespace(copied=[], failed=[]))
        )
        monkeypatch.setattr(task, "_get_round_llm", AsyncMock(return_value=None))
        monkeypatch.setattr(task, "_resolve_allowed_knowledge_ids", AsyncMock(return_value=set()))

        async def _run(*args):
            if state.on_run is not None:
                await state.on_run(state.agent_kwargs[-1]["tools"])
            return True

        monkeypatch.setattr(task, "_execute_agent_tasks", _run)
        monkeypatch.setattr(task, "_drive_continue", _run)
        monkeypatch.setattr(task, "_drive_resume", _run)
        task.manager = manager
        return task

    state.make = make
    return state


def _memory_events(manager) -> list[dict]:
    return [msg.data for msg in manager.messages if msg.event_type == "memory"]


@pytest.mark.parametrize("path", ["run", "continue", "resume"])
async def test_ac28_every_worker_path_binds_tools_and_prompt(worker, memory_services, memory_db, task_message, path):
    """AC-28: first execution, continue and resume all hand the agent the memory tools and their guidance."""
    seed_session(memory_db)
    task_message()
    task = worker.make(_version())

    if path == "run":
        await task.async_run("sv-1", tenant_id=TENANT_A)
    elif path == "continue":
        await task.async_continue("sv-1", "追问", tenant_id=TENANT_A)
    else:
        await task.async_resume("sv-1", user_input="好", tenant_id=TENANT_A)

    kwargs = worker.agent_kwargs[-1]
    assert MEMORY_TOOL_NAMES <= {t.name for t in kwargs["tools"]}
    assert kwargs["memory_prompt"] and MEMORY_PROMPT_HEADER in kwargs["memory_prompt"]


async def test_ac10_unregistered_run_has_no_tools_and_no_prompt(worker, memory_services, memory_db, task_message):
    """AC-10: without a registration the agent gets neither the tools nor the text."""
    seed_session(memory_db, registered=False)
    task_message()
    task = worker.make(_version())

    await task.async_run("sv-1", tenant_id=TENANT_A)

    kwargs = worker.agent_kwargs[-1]
    assert not MEMORY_TOOL_NAMES & {t.name for t in kwargs["tools"]}
    assert not kwargs.get("memory_prompt")


async def test_ac21_explicit_write_streams_memory_event(worker, memory_services, memory_db, task_message):
    """AC-21: a successful memory_write streams a memory event with flags only, never item text."""
    seed_session(memory_db)
    task_message()

    async def _write(tools):
        tool = next(t for t in tools if t.name == "memory_write")
        await tool.ainvoke({"action": "remember", "content": "用户的报告要附参考文献", "type": "preference"})

    worker.on_run = _write
    task = worker.make(_version())
    await task.async_run("sv-1", tenant_id=TENANT_A)

    events = _memory_events(task.manager)
    assert events and events[0]["has_write"] is True
    assert events[0]["turn_id"] == turn_rows(memory_db, KIND_SUMMARY)[0].turn_id
    assert set(events[0]) == {"turn_id", "has_write", "has_attribution"}
    assert "参考文献" not in str(events)


async def test_ac87_retrieval_only_round_streams_attribution(worker, memory_services, memory_db, task_message):
    """AC-87: a round that only retrieved items streams has_attribution by its end."""
    seed_session(memory_db)
    task_message()
    item = await _remember(memory_services, "做研究时用户关注台北房价", item_type="experience")
    assert item.item_id

    async def _search(tools):
        tool = next(t for t in tools if t.name == "memory_search")
        await tool.ainvoke({"query": "台北房价"})

    worker.on_run = _search
    task = worker.make(_version())
    await task.async_run("sv-1", tenant_id=TENANT_A)

    events = _memory_events(task.manager)
    assert events and events[-1]["has_attribution"] is True and events[-1]["has_write"] is False
    assert "台北" not in str(events)
