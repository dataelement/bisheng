"""One LangGraph thread per conversation on the unified runtime (F004 T025, design decision 7).

With the unified-runtime switch on for the tenant, a deep-research run uses
``thread_id = conversation id`` and the workspace ``workspace/{conversation id}``.
The thread id is stored on the run record; a record that stores nothing (written
before F004, or by a tenant on the legacy path) keeps ``thread_id =
session_version_id``.

The tests drive the REAL graph from ``create_linsight_agent`` with a scripted
model, an in-memory checkpointer and an in-memory object store.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from bisheng.linsight.domain import task_exec
from bisheng.linsight.domain import utils as linsight_utils
from bisheng.linsight.domain.models.linsight_session_version import (
    LinsightSessionVersion,
    get_run_thread_id,
    set_run_thread_id,
)
from bisheng.linsight.domain.services import agent_factory
from bisheng.linsight.domain.services.workspace_backend import WorkspaceBackend
from bisheng.linsight.domain.task_exec import LinsightWorkflowTask, TaskExecutionError

CHAT = "chat-0001"
TODOS = [{"content": "1. 收集资料", "status": "in_progress"}]


def _call(name: str, args: dict[str, Any], call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


class _RecordingModel(BaseChatModel):
    """Replays a script and keeps the message list of every call.

    A script item may also be an exception (raised) or the string ``"stop"``
    (flips the executor's termination flag and then waits to be cancelled).
    """

    script: list[Any]
    calls: int = 0
    inputs: list[list[BaseMessage]] = []
    task: Any = None

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _get_ls_params(self, stop: Any = None, **kwargs: Any) -> dict[str, str]:
        # A provider of its own (design §5 pitfall 17).
        return {"ls_provider": "f004-conversation-thread", "ls_model_name": "scripted"}

    def bind_tools(self, tools: Any, **kwargs: Any) -> _RecordingModel:
        return self

    def _next(self, messages: list[BaseMessage]) -> Any:
        self.inputs.append(list(messages))
        item = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return item

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kw: Any) -> Any:
        item = self._next(messages)
        if isinstance(item, BaseException):
            raise item
        return ChatResult(generations=[ChatGeneration(message=item)])

    async def _agenerate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kw: Any
    ) -> Any:
        item = self._next(messages)
        if isinstance(item, BaseException):
            raise item
        if item == "stop":
            self.task._is_terminated = True
            await asyncio.sleep(30)
            raise AssertionError("the stopped run was not cancelled")
        return ChatResult(generations=[ChatGeneration(message=item)])


class _MemoryObjectStore:
    """The slice of the MinIO client the workspace code uses, kept in a dict."""

    bucket = "bisheng"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.minio_client_sync = self

    async def put_object(self, bucket_name: str = None, object_name: str = None, file: bytes = b"", **_: Any) -> None:
        self.objects[object_name] = file

    def put_object_sync(self, bucket_name: str = None, object_name: str = None, file: bytes = b"", **_: Any) -> None:
        self.objects[object_name] = file

    async def get_object(self, bucket_name: str = None, object_name: str = None) -> bytes:
        return self.objects[object_name]

    def get_object_sync(self, bucket_name: str = None, object_name: str = None) -> bytes:
        return self.objects[object_name]

    def list_objects(self, bucket: str, prefix: str = "", recursive: bool = False):
        return [
            SimpleNamespace(object_name=name, size=len(data), is_dir=False)
            for name, data in sorted(self.objects.items())
            if name.startswith(prefix)
        ]

    def copy_object_sync(self, source_bucket, source_object, dest_bucket, dest_object):
        from minio.error import S3Error

        if source_object not in self.objects:
            exc = S3Error.__new__(S3Error)
            object.__setattr__(exc, "_code", "NoSuchKey")
            raise exc
        self.objects[dest_object] = self.objects[source_object]


def _version(svid: str, question: str = "q", **fields: Any) -> LinsightSessionVersion:
    return LinsightSessionVersion(id=svid, session_id=CHAT, user_id=1, tenant_id=1, question=question, **fields)


class _Env:
    """Shared fakes of one test: checkpointer, object store, versions of the conversation."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path, *, unified: bool = True) -> None:
        from bisheng.core.config.settings import LinsightConf

        self.monkeypatch = monkeypatch
        self.tmp_path = tmp_path
        self.saver = InMemorySaver()
        self.store = _MemoryObjectStore()
        self.versions: list[LinsightSessionVersion] = []  # newest first, like the DAO
        self.chat_rows: list[Any] = []
        self.switch = AsyncMock(return_value=unified)

        conf = SimpleNamespace(get_linsight_conf=lambda: LinsightConf())
        monkeypatch.setattr(agent_factory, "settings", conf)
        monkeypatch.setattr(task_exec, "settings", conf)
        monkeypatch.setattr(task_exec, "_unified_runtime_enabled", self.switch)
        monkeypatch.setattr(task_exec, "get_minio_storage", AsyncMock(return_value=self.store))
        monkeypatch.setattr(
            "bisheng.linsight.domain.services.checkpointer.make_checkpointer", lambda *a, **k: self.saver
        )
        monkeypatch.setattr(
            task_exec.LinsightSessionVersionDao,
            "get_session_versions_by_session_id",
            AsyncMock(side_effect=lambda _sid: list(self.versions)),
        )
        monkeypatch.setattr(task_exec.LinsightWorkbenchImpl, "prepare_file_list", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            linsight_utils.ChatMessageDao,
            "aget_messages_by_chat_id",
            AsyncMock(side_effect=lambda **_: list(self.chat_rows)),
        )

    def task(self) -> LinsightWorkflowTask:
        task = LinsightWorkflowTask()
        task.file_dir = str(self.tmp_path)
        task._resolve_knowledge_block = AsyncMock(return_value=None)
        task._handle_event = AsyncMock()
        return task

    async def agent(self, task: LinsightWorkflowTask, version, script: list[Any], profile: str = "planned"):
        model = _RecordingModel(script=script, inputs=[], task=task)
        self.monkeypatch.setattr(agent_factory, "_resolve_model", AsyncMock(return_value=(model, False)))
        backend = WorkspaceBackend(
            workspace_prefix=task._workspace_prefix(version), minio=self.store, file_dir=str(self.tmp_path)
        )
        agent = await agent_factory.create_linsight_agent(
            version, [], backend=backend, file_dir=str(self.tmp_path), checkpointer=self.saver, profile=profile
        )
        return agent, model

    async def start(self, version, script: list[Any]):
        """The new-turn path up to and including the agent stream, as ``_execute_workflow`` orders it."""
        task = self.task()
        task.session_version_id = version.id
        self.versions.insert(0, version)
        await task._enter_conversation_thread(version)
        await task._prepare_run_workspace(version)
        agent, model = await self.agent(task, version, script)
        return task, agent, model

    async def has_checkpoint(self, thread_id: str) -> bool:
        return await self.saver.aget_tuple({"configurable": {"thread_id": thread_id}}) is not None


def _texts(messages: list[BaseMessage]) -> str:
    return "\n".join(str(m.content) for m in messages)


def _humans(messages: list[BaseMessage]) -> list[str]:
    return [str(m.content) for m in messages if isinstance(m, HumanMessage)]


async def test_profiles_alternate_on_one_thread(monkeypatch: pytest.MonkeyPatch, tmp_path):
    env = _Env(monkeypatch, tmp_path)

    # Run 1: planned, with a plan.
    first = _version("sv-1", "第一轮问题")
    task, agent, model1 = await env.start(
        first, [_call("write_todos", {"todos": TODOS}, "c1"), AIMessage("第一轮完成")]
    )
    assert task._thread_id(first) == CHAT
    assert await task._execute_agent_tasks(agent, first) is True
    assert "第一轮问题" in _texts(model1.inputs[0])

    # Run 2: direct. It has no session version record; its thread is the conversation.
    direct_session = SimpleNamespace(id="run-2", session_id=CHAT, tenant_id=1, user_id=1, question="", api_meta=None)
    set_run_thread_id(direct_session, CHAT)
    task2 = env.task()
    agent2, model2 = await env.agent(task2, direct_session, [AIMessage("直接回答")], profile="direct")
    await agent2.ainvoke(
        {"messages": [("user", "第二轮问题")]}, config={"configurable": {"thread_id": task2._thread_id(direct_session)}}
    )
    seen2 = _texts(model2.inputs[0])
    assert "第一轮问题" in seen2 and "第一轮完成" in seen2 and "第二轮问题" in seen2

    # Run 3: planned again, on the same thread.
    third = _version("sv-3", "第三轮问题")
    task3, agent3, model3 = await env.start(third, [AIMessage("第三轮完成")])
    assert task3._thread_id(third) == CHAT
    assert await task3._execute_agent_tasks(agent3, third) is True
    seen3 = _texts(model3.inputs[0])
    for expected in ("第一轮问题", "第一轮完成", "第二轮问题", "直接回答", "第三轮问题"):
        assert expected in seen3
    # The thread already carries the conversation: no rebuilt summary on top of it.
    assert "前情回顾" not in seen3
    # The plan channel survived the direct run in between.
    state = await agent3.aget_state({"configurable": {"thread_id": CHAT}})
    assert [dict(t) for t in state.values["todos"]] == TODOS

    # Each run record names the thread it used; nothing ran on a per-version thread.
    assert get_run_thread_id(first) == CHAT and get_run_thread_id(third) == CHAT
    assert not await env.has_checkpoint("sv-1") and not await env.has_checkpoint("sv-3")


async def test_rebuild_when_no_checkpoint(monkeypatch: pytest.MonkeyPatch, tmp_path):
    env = _Env(monkeypatch, tmp_path)
    # A conversation from before the unified runtime (or one whose checkpoint expired):
    # ChatMessage rows and the latest version's workspace exist, the thread does not.
    env.chat_rows = [
        SimpleNamespace(is_bot=False, message="去年的销售额是多少"),
        SimpleNamespace(is_bot=True, message="去年销售额为 120 万"),
    ]
    old = _version("sv-old", "去年的销售额是多少")
    env.versions.append(old)
    env.store.objects["workspace/sv-old/output/report.md"] = b"# old report"
    env.store.objects["workspace/sv-old/scratch/tmp.txt"] = b"x"
    # This turn's attachment was ingested under the run's own prefix before the run started.
    env.store.objects["workspace/sv-new/uploads/new.md"] = b"new upload"

    new = _version("sv-new", "把报告改成表格")
    task, agent, model = await env.start(
        new, [_call("read_file", {"file_path": "output/report.md"}, "c1"), AIMessage("ok")]
    )

    assert task._thread_id(new) == CHAT
    assert task._workspace_prefix(new) == f"workspace/{CHAT}"
    assert env.store.objects[f"workspace/{CHAT}/output/report.md"] == b"# old report"
    assert env.store.objects[f"workspace/{CHAT}/uploads/new.md"] == b"new upload"
    assert f"workspace/{CHAT}/scratch/tmp.txt" not in env.store.objects

    assert await task._execute_agent_tasks(agent, new) is True
    first_input = _texts(model.inputs[0])
    assert "去年的销售额是多少" in first_input and "去年销售额为 120 万" in first_input
    assert "把报告改成表格" in first_input
    # The agent reads the file that came over from the latest version's workspace.
    tool_outputs = [m for m in model.inputs[1] if isinstance(m, ToolMessage)]
    assert "old report" in str(tool_outputs[-1].content)

    # The next run finds the checkpoint: no second rebuild and no second takeover.
    env.store.objects["workspace/sv-old/output/late.md"] = b"late"
    follow = _version("sv-follow", "再加一列")
    task2, agent2, model2 = await env.start(follow, [AIMessage("done")])
    assert f"workspace/{CHAT}/output/late.md" not in env.store.objects
    assert await task2._execute_agent_tasks(agent2, follow) is True
    assert len(_humans(model2.inputs[0])) == 2
    assert "前情回顾" not in _humans(model2.inputs[0])[-1]
    assert "把报告改成表格" in _humans(model2.inputs[0])[0]


async def test_legacy_run_resumes_on_svid_thread(monkeypatch: pytest.MonkeyPatch, tmp_path):
    env = _Env(monkeypatch, tmp_path)
    # A run parked on ask_user before the upgrade: its record stores no thread id and
    # its checkpoint lives on thread_id = session_version_id.
    legacy = _version("sv-legacy", "写一份报告")
    assert legacy.api_meta is None
    task = env.task()
    ask = _call("ask_user", {"reason": "需要确认", "questions": [{"question": "哪一年？", "options": ["2024"]}]}, "c1")
    agent, model = await env.agent(task, legacy, [ask, AIMessage("报告完成")])
    await agent.ainvoke({"messages": [("user", "写一份报告")]}, config={"configurable": {"thread_id": "sv-legacy"}})
    assert model.calls == 1

    # The tenant is on the unified runtime now. Resume still goes to the old thread.
    assert task._thread_id(legacy) == "sv-legacy"
    assert task._workspace_prefix(legacy) == "workspace/sv-legacy"
    await task._drive_resume(agent, legacy, "2024")
    assert model.calls == 2
    answered = [m for m in model.inputs[1] if isinstance(m, ToolMessage)]
    assert answered and "2024" in str(answered[-1].content)
    assert not await env.has_checkpoint(CHAT)
    assert legacy.api_meta is None

    # An Open API record keeps its metadata and, without a stored thread id, its svid thread.
    open_api = _version("sv-api", api_meta={"channel": "open_api_v2"})
    assert task._thread_id(open_api) == "sv-api"
    # A record that stored the conversation thread resumes there.
    set_run_thread_id(open_api, CHAT)
    assert task._thread_id(open_api) == CHAT
    assert open_api.api_meta == {"channel": "open_api_v2", "thread_id": CHAT}


async def test_next_run_after_stop_sees_history(monkeypatch: pytest.MonkeyPatch, tmp_path):
    env = _Env(monkeypatch, tmp_path)

    # Run 1 is stopped by the user while the model is producing its second reply.
    first = _version("sv-1", "第一轮问题")
    task, agent, _model = await env.start(first, [_call("ls", {"path": "/"}, "c1"), "stop"])
    assert await task._execute_agent_tasks(agent, first) is False

    # Run 2 fails on a provider error after one more tool call.
    second = _version("sv-2", "第二轮问题")
    task2, agent2, model2 = await env.start(second, [_call("ls", {"path": "/"}, "c2"), RuntimeError("provider down")])
    with pytest.raises(TaskExecutionError):
        await task2._execute_agent_tasks(agent2, second)
    assert "第一轮问题" in _texts(model2.inputs[0])

    # Run 3 still reads what both earlier runs left on the thread.
    third = _version("sv-3", "第三轮问题")
    task3, agent3, model3 = await env.start(third, [AIMessage("第三轮完成")])
    assert await task3._execute_agent_tasks(agent3, third) is True
    humans = _humans(model3.inputs[0])
    assert len(humans) == 3
    assert "第一轮问题" in humans[0] and "第二轮问题" in humans[1] and "第三轮问题" in humans[2]
    assert "前情回顾" not in _texts(model3.inputs[0])
    tool_ids = [m.tool_call_id for m in model3.inputs[0] if isinstance(m, ToolMessage)]
    assert tool_ids == ["c1", "c2"]


async def test_flag_off_keeps_svid_thread(monkeypatch: pytest.MonkeyPatch, tmp_path):
    env = _Env(monkeypatch, tmp_path, unified=False)
    env.chat_rows = [
        SimpleNamespace(is_bot=False, message="上一轮问题"),
        SimpleNamespace(is_bot=True, message="上一轮回答"),
    ]
    old = _version("sv-old")
    env.versions.append(old)
    env.store.objects["workspace/sv-old/output/report.md"] = b"# old report"

    new = _version("sv-new", "本轮问题")
    task, agent, model = await env.start(new, [AIMessage("ok")])

    assert new.api_meta is None
    assert task._thread_id(new) == "sv-new"
    assert task._workspace_prefix(new) == "workspace/sv-new"
    # Legacy cross-turn seed: previous version -> this version.
    assert env.store.objects["workspace/sv-new/output/report.md"] == b"# old report"
    assert not any(key.startswith(f"workspace/{CHAT}/") for key in env.store.objects)

    assert await task._execute_agent_tasks(agent, new) is True
    assert "上一轮回答" in _texts(model.inputs[0])
    assert await env.has_checkpoint("sv-new") and not await env.has_checkpoint(CHAT)
