"""F132 T004 / V3 spike: where does a memory tool's args and result land in task mode?

Experimental code — delete after Wave 11. Each test feeds one ``memory_search``
call (args carry ``ARG_SECRET``, the result carries ``RESULT_SECRET``) through one
real code path and asserts which sink receives the raw text. A passing test here
means "the sink DOES receive raw memory content today", i.e. a redaction point is
needed there.
"""

from __future__ import annotations

from typing import Any

import pytest
from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.backends.protocol import EditResult, FileDownloadResponse, WriteResult
from deepagents.graph import DeepAgentState
from deepagents.middleware._overflow_clip import _clip_overflow_tail
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from bisheng.linsight.domain.models.linsight_execute_task import ExecuteTaskTypeEnum
from bisheng.linsight.domain.services import state_message_manager as smm
from bisheng.linsight.domain.services.context_budget import (
    BishengSummarizationMiddleware,
    ToolResultBudgetMiddleware,
)
from bisheng.linsight.domain.services.stream_event_mapper import StreamEventMapper
from bisheng.linsight.domain.task_exec import LinsightWorkflowTask
from bisheng_langchain.linsight.event import ExecStep

SVID = "sv-memory-spike"
ARG_SECRET = "ARG_SECRET_用户偏好查询"
RESULT_SECRET = "RESULT_SECRET_用户住在台北"


def _call_and_result(call_id: str = "call_m1"):
    ai = AIMessage(
        "",
        tool_calls=[{"name": "memory_search", "args": {"query": ARG_SECRET}, "id": call_id}],
    )
    tm = ToolMessage(content=f'{{"items": [{{"id": 7, "content": "{RESULT_SECRET}"}}]}}', tool_call_id=call_id)
    return ai, tm


def _map(mapper: StreamEventMapper, msg, ns=None) -> list:
    return mapper.normalize("messages", (msg, {}), namespace=ns)


# --------------------------------------------------------------------------- #
# 1. Step-event mapping (stream_event_mapper) — the single upstream of DB/Redis/WS
# --------------------------------------------------------------------------- #


def test_mapper_start_and_end_frames_carry_raw_args_and_result():
    mapper = StreamEventMapper(svid=SVID)
    ai, tm = _call_and_result()

    start = _map(mapper, ai)
    end = _map(mapper, tm)

    assert len(start) == 1 and isinstance(start[0], ExecStep)
    assert start[0].status == "start"
    assert start[0].step_type == "tool"  # memory_search matches no _KNOWLEDGE_TOOL_HINTS
    assert start[0].task_id == SVID  # session pseudo task row (id == svid)
    assert start[0].params == {"query": ARG_SECRET}  # stream_event_mapper.py:662

    assert len(end) == 1 and end[0].status == "end"
    assert end[0].params == {"query": ARG_SECRET}  # _build_end_step :711 re-emits params
    assert RESULT_SECRET in end[0].output  # :700 output = ToolMessage text (<=8000 chars)
    # start and end share one minted call_id -> upserted into ONE history entry
    assert start[0].call_id == end[0].call_id
    assert start[0].call_id.startswith("call_m1#")


def test_mapper_subagent_namespace_also_carries_raw_content():
    """A researcher subagent calling memory_search goes through the same frames."""
    mapper = StreamEventMapper(svid=SVID)
    ai, tm = _call_and_result("call_sub")
    ns = ("tools:abc",)
    start = _map(mapper, ai, ns)
    end = _map(mapper, tm, ns)
    assert start[0].params == {"query": ARG_SECRET}
    assert start[0].extra_info.get("namespace") == "tools:abc"
    assert RESULT_SECRET in end[0].output


def test_mapper_orphan_end_buffered_then_merged_with_raw_content():
    """End-before-start reordering path (:686-690 buffer, :671-673 merge)."""
    mapper = StreamEventMapper(svid=SVID)
    ai, tm = _call_and_result("call_orphan")
    assert _map(mapper, tm) == []
    events = _map(mapper, ai)
    assert [e.status for e in events] == ["start", "end"]
    assert RESULT_SECRET in events[1].output and events[1].params == {"query": ARG_SECRET}


def test_mapper_streamed_chunk_args_do_not_reach_params_for_plain_tools():
    """Streaming providers: only the first chunk carries name+id, args arrive later.

    The start frame is built from the argless first chunk; arg reassembly only
    enriches ``task`` delegations. So for a plain tool streamed in chunks the
    persisted ``params`` is ``{}`` — the raw args then live only in the
    checkpoint thread. The result still lands in ``output``.
    """
    mapper = StreamEventMapper(svid=SVID)
    first = AIMessageChunk(
        content="", tool_call_chunks=[{"name": "memory_search", "args": "", "id": "call_s", "index": 0}]
    )
    rest = AIMessageChunk(
        content="", tool_call_chunks=[{"name": None, "args": f'{{"query": "{ARG_SECRET}"}}', "id": None, "index": 0}]
    )
    start = _map(mapper, first)
    more = _map(mapper, rest)
    end = _map(mapper, ToolMessage(content=RESULT_SECRET, tool_call_id="call_s"))
    assert start[0].params == {}
    assert more == []
    assert end[0].params == {} and RESULT_SECRET in end[0].output


# --------------------------------------------------------------------------- #
# 2. Executor dispatch: one ExecStep -> DB history + Redis task key + Redis WS list
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


async def test_exec_step_reaches_db_history_redis_task_key_and_ws_list(monkeypatch):
    mapper = StreamEventMapper(svid=SVID)
    ai, tm = _call_and_result()
    events = [*_map(mapper, ai), *_map(mapper, tm)]

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
    for event in events:
        await task._handle_exec_step(None, event, None)  # task_exec.py:1912-1924

    # (a) MySQL/DM8: linsight_execute_task.history of the pseudo task row
    last_history = db_writes[-1]["history"]
    assert db_writes[-1]["task_id"] == SVID
    assert len(last_history) == 1  # start+end upserted into one entry
    assert last_history[0]["params"] == {"query": ARG_SECRET}
    assert RESULT_SECRET in last_history[0]["output"]
    # (b) Redis task key linsight_tasks:{svid}:execution_tasks:{task_id} (1h TTL)
    cached = redis.kv[f"{prefix}execution_tasks:{SVID}"]
    assert RESULT_SECRET in cached["history"][0]["output"]
    # (c) Redis list linsight_tasks:{svid}:messages -> WS task-message-stream -> browser
    pushed = redis.lists[f"{prefix}messages"]
    assert [p["event_type"] for p in pushed] == ["task_execute_step", "task_execute_step"]
    assert pushed[0]["data"]["params"] == {"query": ARG_SECRET}
    assert RESULT_SECRET in pushed[1]["data"]["output"]


# --------------------------------------------------------------------------- #
# 3. Context compaction: conversation_history/{thread_id}.md
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
        return "v3-noop"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage("summary"))])


def test_compaction_offload_writes_raw_args_and_result_to_workspace(monkeypatch):
    middleware = BishengSummarizationMiddleware(_NoopModel(), StateBackend(), usable_input=None)
    monkeypatch.setattr(middleware, "_get_thread_id", lambda: SVID)
    backend = _RecordingBackend()
    ai, tm = _call_and_result()

    path = middleware._offload_to_backend(backend, [HumanMessage("任务"), ai, tm])

    assert path == f"/conversation_history/{SVID}.md"
    body = backend.files[path]
    assert RESULT_SECRET in body  # ToolMessage content
    assert ARG_SECRET in body  # AIMessage tool_calls args (get_buffer_string xml format)


# --------------------------------------------------------------------------- #
# 4. Large-result offload: large_tool_results/<tool_call_id>
# --------------------------------------------------------------------------- #


class _Scripted(BaseChatModel):
    replies: Any = None

    @property
    def _llm_type(self) -> str:
        return "v3-scripted"

    def bind_tools(self, *args, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=next(self.replies))])


def _run(memory_tool, middleware_factory):
    backend = StateBackend()
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
        middleware=middleware_factory(backend),
        state_schema=DeepAgentState,
        backend=backend,
        checkpointer=InMemorySaver(),
    )
    return agent.invoke({"messages": [{"role": "user", "content": "go"}]}, {"configurable": {"thread_id": "t"}})


def _file_text(entry) -> str:
    content = entry.get("content") if isinstance(entry, dict) else getattr(entry, "content", entry)
    return "\n".join(content) if isinstance(content, list) else str(content)


@tool("memory_search")
def _memory_search_cjk(query: str) -> str:
    """3000 CJK chars: over a 2000-token budget, under the framework's 80000-char limit."""
    return RESULT_SECRET + "记忆" * 1500


@tool("memory_search")
def _memory_search_huge(query: str) -> str:
    """> 80000 chars: over deepagents' own FilesystemMiddleware threshold."""
    return RESULT_SECRET + "x" * 90_000


def test_bisheng_result_budget_offloads_memory_result_to_workspace_file():
    result = _run(_memory_search_cjk, lambda backend: [ToolResultBudgetMiddleware(backend, 20_000)])
    assert "/large_tool_results/c1" in result["files"]
    assert RESULT_SECRET in _file_text(result["files"]["/large_tool_results/c1"])


def test_framework_filesystem_middleware_offloads_huge_memory_result_without_budget():
    """No ToolResultBudgetMiddleware (unknown window): deepagents' 20000-token default still fires."""
    result = _run(_memory_search_huge, lambda backend: [])
    assert "/large_tool_results/c1" in result["files"]
    assert RESULT_SECRET in _file_text(result["files"]["/large_tool_results/c1"])


def test_overflow_tail_clip_offloads_trailing_memory_result():
    """Summarization-on-overflow path (deepagents _overflow_clip): no tool-name filter except read_file."""
    backend = _RecordingBackend()
    ai = AIMessage("", tool_calls=[{"name": "memory_search", "args": {"query": ARG_SECRET}, "id": "c9"}])
    tm = ToolMessage(content=RESULT_SECRET + "y" * 40_000, tool_call_id="c9")
    _, replaced = _clip_overflow_tail(
        [HumanMessage("任务"), ai, tm],
        backend,
        keep=("tokens", 1000),
        max_input_tokens=None,
        token_counter=lambda msgs: sum(len(str(m.content)) for m in msgs) // 4,
        large_tool_results_prefix="/large_tool_results",
    )
    assert replaced, "trailing memory result should have been offloaded"
    assert RESULT_SECRET in backend.files["/large_tool_results/c9"]


@pytest.mark.parametrize("name", ["memory_search", "memory_write"])
def test_memory_tools_are_not_in_any_existing_exclusion_list(name):
    from deepagents.middleware.filesystem import TOOLS_EXCLUDED_FROM_EVICTION

    from bisheng.linsight.domain.services.agent_factory import _SUBAGENT_TOOL_DENY
    from bisheng.linsight.domain.services.context_budget import _SEARCH_TOOLS

    assert name not in TOOLS_EXCLUDED_FROM_EVICTION
    assert name not in _SEARCH_TOOLS
    # memory tools would be inherited by the researcher subagent (blacklist)
    assert name not in _SUBAGENT_TOOL_DENY
