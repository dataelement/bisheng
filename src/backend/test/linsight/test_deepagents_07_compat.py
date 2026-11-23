"""deepagents 0.7 compatibility of the task-mode agent (F004 T004, AC-07).

deepagents 0.7 made planning opt-in and changed what two file tools print:

- ``TodoListMiddleware`` is no longer part of the default stack, so ``write_todos``
  and the ``todos`` state channel exist only when the factory adds it;
- ``read_file`` prints a ``@@ lines a-b of n @@`` header instead of ``cat -n``
  line numbers;
- ``ls`` on an empty directory prints ``No files found`` instead of ``[]``.

These tests drive the REAL graph built by ``create_linsight_agent`` with a
scripted model, so they fail if a later upgrade drops the plan channel again or
if one of BiSheng's middlewares starts mangling the new tool output.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from bisheng.linsight.domain.services import agent_factory
from bisheng.linsight.domain.services.stream_event_mapper import StreamEventMapper
from bisheng.linsight.domain.services.workspace_backend import WorkspaceBackend
from bisheng_langchain.linsight.event import GenerateSubTask, TaskEnd, TaskStart

TODOS_V1 = [
    {"content": "1. 收集资料", "status": "in_progress"},
    {"content": "2. 写报告", "status": "pending"},
]
TODOS_V2 = [
    {"content": "1. 收集资料", "status": "completed"},
    {"content": "2. 写报告", "status": "in_progress"},
]


def _call(name: str, args: dict[str, Any], call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


class _ScriptedModel(BaseChatModel):
    """Replays a fixed list of replies and records which tools were bound."""

    script: list[AIMessage]
    calls: int = 0
    bound_tool_names: list[str] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _get_ls_params(self, stop: Any = None, **kwargs: Any) -> dict[str, str]:
        # A provider of its own: create_linsight_agent registers a process-wide
        # harness profile per provider, and other test modules build plain deep
        # agents from a same-named "_ScriptedModel" class.
        return {"ls_provider": "f004-deepagents-07-compat", "ls_model_name": "scripted"}

    def bind_tools(self, tools: Any, **kwargs: Any) -> _ScriptedModel:
        names = []
        for tool in tools:
            name = getattr(tool, "name", None)
            if name is None and isinstance(tool, dict):
                name = tool.get("name") or tool.get("function", {}).get("name")
            names.append(str(name))
        self.bound_tool_names = names
        return self

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        reply = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=reply)])


class _MemoryObjectStore:
    """The slice of the MinIO client ``WorkspaceBackend`` uses, kept in a dict."""

    bucket = "bisheng"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.minio_client_sync = self

    async def put_object(self, bucket_name: str, object_name: str, file: bytes, **_: Any) -> None:
        self.objects[object_name] = file

    def put_object_sync(self, bucket_name: str, object_name: str, file: bytes, **_: Any) -> None:
        self.objects[object_name] = file

    async def get_object(self, bucket_name: str, object_name: str) -> bytes:
        return self.objects[object_name]

    def get_object_sync(self, bucket_name: str, object_name: str) -> bytes:
        return self.objects[object_name]

    def list_objects(self, bucket: str, prefix: str = "", recursive: bool = False):
        return [
            SimpleNamespace(object_name=name, size=len(data), is_dir=False)
            for name, data in sorted(self.objects.items())
            if name.startswith(prefix)
        ]


async def _run(
    monkeypatch: pytest.MonkeyPatch, tmp_path, script: list[AIMessage]
) -> tuple[_ScriptedModel, list[tuple], dict]:
    """Build the real task-mode graph around ``script`` and stream it to the end.

    Returns the model, every ``(namespace, mode, chunk)`` item of the stream, and
    the tool outputs keyed by tool-call id.
    """
    from bisheng.core.config.settings import LinsightConf

    model = _ScriptedModel(script=script)
    monkeypatch.setattr(agent_factory, "_resolve_model", AsyncMock(return_value=(model, False)))
    monkeypatch.setattr(agent_factory, "settings", SimpleNamespace(get_linsight_conf=lambda: LinsightConf()))
    session = SimpleNamespace(id="sv-07", session_id="chat-07", tenant_id=1, user_id=1, question="q", api_meta=None)

    backend = WorkspaceBackend(svid="sv-07", minio=_MemoryObjectStore(), file_dir=str(tmp_path))
    agent = await agent_factory.create_linsight_agent(session, [], backend=backend, file_dir=str(tmp_path))

    items: list[tuple] = []
    outputs: dict[str, Any] = {}
    async for namespace, mode, chunk in agent.astream(
        {"messages": [("user", "写一份报告")]},
        config={"configurable": {"thread_id": "t-07"}, "recursion_limit": 40},
        stream_mode=["updates"],
        subgraphs=True,
    ):
        items.append((namespace, mode, chunk))
        if not isinstance(chunk, dict):
            continue
        for delta in chunk.values():
            if not isinstance(delta, dict):
                continue
            for message in delta.get("messages") or []:
                if isinstance(message, ToolMessage):
                    outputs[message.tool_call_id] = message
    return model, items, outputs


def _todo_deltas(items: list[tuple]) -> list[tuple[str, Any]]:
    found = []
    for namespace, _mode, chunk in items:
        if namespace or not isinstance(chunk, dict):
            continue
        for node, delta in chunk.items():
            if isinstance(delta, dict) and delta.get("todos") is not None:
                found.append((node, delta["todos"]))
    return found


async def test_planned_graph_has_write_todos(monkeypatch: pytest.MonkeyPatch, tmp_path):
    model, _items, outputs = await _run(
        monkeypatch, tmp_path, [_call("write_todos", {"todos": TODOS_V1}, "c1"), AIMessage(content="done")]
    )

    assert "write_todos" in model.bound_tool_names
    # 0.7 added a ``delete`` file tool. The workspace backend does not implement it
    # (the inherited one deletes on the worker's disk, not in the object store), so
    # the factory must not offer it.
    file_tools = {"ls", "read_file", "write_file", "edit_file", "glob", "grep"}
    assert file_tools <= set(model.bound_tool_names)
    assert "delete" not in model.bound_tool_names
    assert outputs["c1"].status != "error"


async def test_todos_delta_shape(monkeypatch: pytest.MonkeyPatch, tmp_path):
    _model, items, _outputs = await _run(
        monkeypatch,
        tmp_path,
        [
            _call("write_todos", {"todos": TODOS_V1}, "c1"),
            _call("write_todos", {"todos": TODOS_V2}, "c2"),
            AIMessage(content="done"),
        ],
    )

    deltas = _todo_deltas(items)
    assert [node for node, _todos in deltas] == ["tools", "tools"]
    assert [[dict(t) for t in todos] for _node, todos in deltas] == [TODOS_V1, TODOS_V2]

    # The production mapper turns those deltas into the task-panel events unchanged.
    mapper = StreamEventMapper(svid="sv-07")
    events = []
    for namespace, mode, chunk in items:
        events.extend(mapper.normalize(mode, chunk, namespace or None))
    generated = [e for e in events if isinstance(e, GenerateSubTask)]
    assert [t["name"] for t in generated[0].subtask] == ["1. 收集资料", "2. 写报告"]
    assert [e.name for e in events if isinstance(e, TaskStart)] == ["1. 收集资料", "2. 写报告"]
    assert [(e.name, e.status) for e in events if isinstance(e, TaskEnd)] == [("1. 收集资料", "success")]


async def test_read_file_format_consumers(monkeypatch: pytest.MonkeyPatch, tmp_path):
    _model, _items, outputs = await _run(
        monkeypatch,
        tmp_path,
        [
            _call("write_file", {"file_path": "scratch/a.txt", "content": "第一行\nsecond line\n"}, "c1"),
            _call("read_file", {"file_path": "scratch/a.txt"}, "c2"),
            AIMessage(content="done"),
        ],
    )

    assert outputs["c1"].status != "error"
    shown = outputs["c2"]
    assert shown.status != "error"
    # BiSheng's guards sit between the tool and the model. Whatever header the
    # framework prints, they must hand the file's text through untouched: no
    # binary/mojibake replacement, no offload stub.
    assert isinstance(shown.content, str)
    assert "第一行" in shown.content and "second line" in shown.content
    assert "[System]" not in shown.content
    assert "large_tool_results" not in shown.content


async def test_empty_ls_consumers(monkeypatch: pytest.MonkeyPatch, tmp_path):
    _model, _items, outputs = await _run(
        monkeypatch,
        tmp_path,
        [
            _call("ls", {"path": "scratch/empty"}, "c1"),
            _call("ls", {"path": "scratch/empty"}, "c2"),
            _call("ls", {"path": "scratch/empty"}, "c3"),
            AIMessage(content="done"),
        ],
    )

    # An empty listing is a normal answer. It must not be marked as an error —
    # the tool-loop breaker counts error results, and three in a row would start
    # nudging the model about a failure that did not happen.
    for call_id in ("c1", "c2", "c3"):
        assert outputs[call_id].status != "error"
        assert isinstance(outputs[call_id].content, str)
        assert "[System]" not in outputs[call_id].content
