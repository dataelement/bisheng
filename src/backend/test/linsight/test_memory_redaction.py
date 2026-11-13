"""F132 T071: no memory content in deep-research step history, workspace files or the share API (AC-09).

A ``memory_search`` call carries ``ARG_SECRET`` in its arguments and
``RESULT_SECRET`` in its result (the result starts with the search header, as
the real tool output does). Every sink V3 found must hold neither: step history
in the database, the Redis task key, the WS message list, the compaction file
``conversation_history/*.md``, and ``large_tool_results/*`` (three offload
paths). Non-memory tools are unchanged.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from deepagents import create_deep_agent
from deepagents.backends.protocol import EditResult, FileDownloadResponse, WriteResult
from deepagents.graph import DeepAgentState
from deepagents.middleware._overflow_clip import _clip_overflow_tail
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from bisheng.linsight.domain.models.linsight_execute_task import ExecuteTaskTypeEnum
from bisheng.linsight.domain.services import state_message_manager as smm
from bisheng.linsight.domain.services.context_budget import BishengSummarizationMiddleware, ToolResultBudgetMiddleware
from bisheng.linsight.domain.services.stream_event_mapper import StreamEventMapper
from bisheng.linsight.domain.services.workspace_backend import WorkspaceBackend
from bisheng.linsight.domain.task_exec import LinsightWorkflowTask
from bisheng.memory.domain.services.search import SEARCH_HEADER
from test.linsight.fixtures.fake_minio import FakeMinioStorage

SVID = "sv-memory-redact"
ARG_SECRET = "ARG_SECRET_用户偏好查询"
RESULT_SECRET = "RESULT_SECRET_用户住在台北"
PLAIN_SECRET = "PLAIN_TOOL_OUTPUT_保留"


def _memory_result(extra: str = "") -> str:
    return f"{SEARCH_HEADER}\n- id=item-7 [事实] {RESULT_SECRET}（记录于 2026-11-01）{extra}"


def _memory_call(call_id: str = "call_m1", name: str = "memory_search", result: str | None = None):
    ai = AIMessage("", tool_calls=[{"name": name, "args": {"query": ARG_SECRET}, "id": call_id}])
    tm = ToolMessage(content=result if result is not None else _memory_result(), tool_call_id=call_id)
    return ai, tm


def _plain_call(call_id: str = "call_p1"):
    ai = AIMessage("", tool_calls=[{"name": "web_search", "args": {"query": "公开问题"}, "id": call_id}])
    tm = ToolMessage(content=PLAIN_SECRET, tool_call_id=call_id)
    return ai, tm


def _map(mapper: StreamEventMapper, msg, ns=None) -> list:
    return mapper.normalize("messages", (msg, {}), namespace=ns)


# --------------------------------------------------------------------------- #
# Step events -> DB history, Redis task key, WS list (sinks 1-7)
# --------------------------------------------------------------------------- #


class _FakeRedis:
    def __init__(self):
        self.kv: dict[str, Any] = {}
        self.lists: dict[str, list] = {}

    async def aget(self, key):
        return self.kv.get(key)

    async def aset(self, key, value, expiration=None):
        self.kv[key] = value

    async def arpush(self, key, value):
        self.lists.setdefault(key, []).append(value)


@pytest.fixture
def step_sinks(monkeypatch):
    redis = _FakeRedis()
    manager = smm.LinsightStateMessageManager.__new__(smm.LinsightStateMessageManager)
    manager._session_version_id = SVID
    manager._redis_client = redis
    manager._logger = smm.logger
    prefix = f"{manager.KEY_PREFIX}{SVID}:"
    manager._keys = {
        "session_version_info": f"{prefix}session_version_info",
        "messages": f"{prefix}messages",
        "execution_tasks": f"{prefix}execution_tasks:",
    }
    manager._last_history_db_flush = {}
    manager._pending_history = {}
    pseudo = smm.LinsightExecuteTask(id=SVID, session_version_id=SVID, task_type=ExecuteTaskTypeEnum.SINGLE, history=[])
    redis.kv[f"{prefix}execution_tasks:{SVID}"] = pseudo.model_dump()
    db_writes: list[dict] = []

    async def _update_fields_by_id(task_id, **fields):
        db_writes.append({"task_id": task_id, **fields})

    monkeypatch.setattr(smm.LinsightExecuteTaskDao, "update_fields_by_id", _update_fields_by_id)
    task = LinsightWorkflowTask.__new__(LinsightWorkflowTask)
    task._state_manager = manager
    return SimpleNamespace(task=task, redis=redis, prefix=prefix, db_writes=db_writes)


async def _feed(sinks, events):
    for event in events:
        await sinks.task._handle_exec_step(None, event, None)


def _assert_no_secret(obj):
    text = str(obj)
    assert ARG_SECRET not in text and RESULT_SECRET not in text


async def test_ac09_step_history_redis_and_ws_hold_no_memory_content(step_sinks):
    """AC-09: DB history, Redis task key and WS list carry only the redacted stand-in."""
    mapper = StreamEventMapper(svid=SVID)
    ai, tm = _memory_call()
    await _feed(step_sinks, [*_map(mapper, ai), *_map(mapper, tm)])

    history = step_sinks.db_writes[-1]["history"]
    _assert_no_secret(history)
    entry = history[0]
    assert entry["params"] == {"redacted": True, "op": "search", "item_ids": ["item-7"]}
    assert '"redacted": true' in entry["output"] and "item-7" in entry["output"]
    _assert_no_secret(step_sinks.redis.kv[f"{step_sinks.prefix}execution_tasks:{SVID}"])
    pushed = step_sinks.redis.lists[f"{step_sinks.prefix}messages"]
    assert [p["event_type"] for p in pushed] == ["task_execute_step", "task_execute_step"]
    _assert_no_secret(pushed)


async def test_ac09_out_of_order_and_subagent_frames_are_redacted(step_sinks):
    """AC-09: the result-before-call merge path and namespaced frames are covered by the same point."""
    mapper = StreamEventMapper(svid=SVID)
    ai, tm = _memory_call("call_orphan")
    assert _map(mapper, tm) == []
    events = _map(mapper, ai)
    ai2, tm2 = _memory_call("call_ns", name="memory_write", result='{"memory_tool": "memory_write", "op": "remember"}')
    events += [*_map(mapper, ai2, ("tools:x",)), *_map(mapper, tm2, ("tools:x",))]
    await _feed(step_sinks, events)

    _assert_no_secret(step_sinks.db_writes)
    _assert_no_secret(step_sinks.redis.lists)


async def test_ac09_plain_tool_steps_unchanged(step_sinks):
    """AC-09 negative control: a non-memory tool keeps its arguments and output."""
    mapper = StreamEventMapper(svid=SVID)
    ai, tm = _plain_call()
    await _feed(step_sinks, [*_map(mapper, ai), *_map(mapper, tm)])

    entry = step_sinks.db_writes[-1]["history"][0]
    assert entry["params"] == {"query": "公开问题"} and PLAIN_SECRET in entry["output"]


async def test_ac09_share_link_detail_api_returns_redacted_history(step_sinks, monkeypatch):
    """AC-09: the share-link task-detail endpoint returns the persisted (redacted) history."""
    from bisheng.linsight.api.endpoints import linsight as ep

    mapper = StreamEventMapper(svid=SVID)
    ai, tm = _memory_call()
    await _feed(step_sinks, [*_map(mapper, ai), *_map(mapper, tm)])
    stored = [{"id": SVID, "history": step_sinks.db_writes[-1]["history"]}]
    monkeypatch.setattr(ep.LinsightWorkbenchImpl, "get_execute_task_detail", AsyncMock(return_value=stored))
    owner = SimpleNamespace(user_id=1, session_id="chat-1")
    monkeypatch.setattr(ep.LinsightSessionVersionDao, "get_by_id", AsyncMock(return_value=owner))
    share = SimpleNamespace(resource_id="chat-1", meta_data=None)

    resp = await ep.get_execute_task_detail(
        session_version_id=SVID, login_user=SimpleNamespace(user_id=2), share_link=share
    )

    assert resp.status_code == 200
    _assert_no_secret(resp.data)


# --------------------------------------------------------------------------- #
# Compaction: conversation_history/*.md (sink 8)
# --------------------------------------------------------------------------- #


class _RecordingBackend:
    def __init__(self):
        self.files: dict[str, str] = {}

    def download_files(self, paths):
        return [
            FileDownloadResponse(path=p, content=self.files[p].encode(), error=None)
            if p in self.files
            else FileDownloadResponse(path=p, content=None, error="file_not_found")
            for p in paths
        ]

    async def adownload_files(self, paths):
        return self.download_files(paths)

    def write(self, path, content):
        self.files[path] = content
        return WriteResult(path=path)

    async def awrite(self, path, content):
        return self.write(path, content)

    def edit(self, path, old, new, *args, **kwargs):
        self.files[path] = new
        return EditResult(path=path, occurrences=1)

    async def aedit(self, path, old, new, *args, **kwargs):
        return self.edit(path, old, new)


class _NoopModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "memory-noop"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage("summary"))])


@pytest.fixture
def summarizer(monkeypatch):
    from deepagents.backends import StateBackend

    middleware = BishengSummarizationMiddleware(_NoopModel(), StateBackend(), usable_input=None)
    monkeypatch.setattr(middleware, "_get_thread_id", lambda: SVID)
    return middleware


def test_ac09_compaction_file_has_no_memory_content(summarizer):
    """AC-09: the compaction offload writes redacted memory calls; plain tools stay readable."""
    backend = _RecordingBackend()
    ai, tm = _memory_call()
    pai, ptm = _plain_call()
    messages = [HumanMessage("任务"), ai, tm, pai, ptm]

    path = summarizer._offload_to_backend(backend, messages)

    body = backend.files[path]
    _assert_no_secret(body)
    assert "redacted" in body and PLAIN_SECRET in body
    # the agent state itself is untouched (only the file copy is redacted)
    assert RESULT_SECRET in messages[2].content and messages[1].tool_calls[0]["args"]["query"] == ARG_SECRET


async def test_ac09_async_compaction_file_has_no_memory_content(summarizer):
    """AC-09: same for the async offload."""
    backend = _RecordingBackend()
    ai, tm = _memory_call()

    path = await summarizer._aoffload_to_backend(backend, [HumanMessage("任务"), ai, tm])

    _assert_no_secret(backend.files[path])


# --------------------------------------------------------------------------- #
# Large-result offload: large_tool_results/* (sinks 9-11)
# --------------------------------------------------------------------------- #


class _Scripted(BaseChatModel):
    replies: Any = None

    @property
    def _llm_type(self) -> str:
        return "memory-scripted"

    def bind_tools(self, *args, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=next(self.replies))])


@tool("memory_search")
def _memory_search_cjk(query: str) -> str:
    """3000 CJK chars: over a 2000-token budget, under the framework's 80000-char limit."""
    return _memory_result("记忆" * 1500)


@tool("memory_search")
def _memory_search_huge(query: str) -> str:
    """> 80000 chars: over deepagents' own FilesystemMiddleware threshold."""
    return _memory_result("x" * 90_000)


@pytest.fixture
def workspace(tmp_path):
    minio = FakeMinioStorage()
    return SimpleNamespace(minio=minio, backend=WorkspaceBackend(svid=SVID, minio=minio, file_dir=str(tmp_path)))


def _stored_text(minio) -> str:
    return "\n".join(v.decode("utf-8", "ignore") for v in minio.store.values())


def _run(memory_tool, backend, middleware):
    model = _Scripted(
        replies=iter(
            [
                AIMessage("", tool_calls=[{"name": "memory_search", "args": {"query": ARG_SECRET}, "id": "c1"}]),
                AIMessage("done"),
            ]
        )
    )
    agent = create_deep_agent(
        model=model,
        tools=[memory_tool],
        middleware=middleware,
        state_schema=DeepAgentState,
        backend=backend,
        checkpointer=InMemorySaver(),
    )
    return agent.invoke({"messages": [{"role": "user", "content": "go"}]}, {"configurable": {"thread_id": "t"}})


def test_ac09_result_budget_clips_memory_result_instead_of_offloading(workspace):
    """AC-09: the BiSheng per-result budget clips a memory result; nothing lands in the workspace."""
    result = _run(_memory_search_cjk, workspace.backend, [ToolResultBudgetMiddleware(workspace.backend, 20_000)])

    assert RESULT_SECRET not in _stored_text(workspace.minio)
    assert not any("large_tool_results" in key[1] for key in workspace.minio.store)
    tool_msg = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert tool_msg.content.startswith(SEARCH_HEADER)  # clipped in place, still readable by the model


def test_ac09_framework_offload_of_huge_memory_result_is_refused(workspace):
    """AC-09: deepagents' own 80000-char offload hits WorkspaceBackend, which refuses memory output."""
    result = _run(_memory_search_huge, workspace.backend, [])

    assert RESULT_SECRET not in _stored_text(workspace.minio)
    assert not any("large_tool_results" in key[1] for key in workspace.minio.store)
    tool_msg = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert RESULT_SECRET in tool_msg.content  # kept in context, not written out


def test_ac09_overflow_tail_clip_keeps_memory_result_out_of_workspace(workspace):
    """AC-09: the compaction-on-overflow tail clip cannot write a memory result either."""
    ai = AIMessage("", tool_calls=[{"name": "memory_search", "args": {"query": ARG_SECRET}, "id": "c9"}])
    tm = ToolMessage(content=_memory_result("y" * 40_000), tool_call_id="c9")
    _clip_overflow_tail(
        [HumanMessage("任务"), ai, tm],
        workspace.backend,
        keep=("tokens", 1000),
        max_input_tokens=None,
        token_counter=lambda msgs: sum(len(str(m.content)) for m in msgs) // 4,
        large_tool_results_prefix="/large_tool_results",
    )

    assert RESULT_SECRET not in _stored_text(workspace.minio)


async def test_ac09_workspace_write_refuses_memory_output_only_under_large_results(workspace):
    """AC-09: write/awrite refuse memory output under large_tool_results/; other content is written."""
    sync = workspace.backend.write("/large_tool_results/c1", _memory_result())
    asyn = await workspace.backend.awrite("/large_tool_results/c2", '{"memory_tool": "memory_write", "ok": true}')
    plain = await workspace.backend.awrite("/large_tool_results/c3", PLAIN_SECRET)

    assert sync.error and asyn.error and not plain.error
    stored = _stored_text(workspace.minio)
    assert RESULT_SECRET not in stored and "memory_tool" not in stored and PLAIN_SECRET in stored
