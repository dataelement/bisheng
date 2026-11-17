"""The two profiles of the unified agent factory (F004 T019/T020).

``create_linsight_agent(profile=...)`` builds both answer modes from one factory:

- ``planned`` (default, deep research): ``write_todos`` and the planning prompt;
- ``direct`` (daily chat): no ``write_todos``, a lean prompt with no plan step.

Everything else the user selected (tools, knowledge bases, web search, skills,
code execution, memory, ``ask_user``) must be bound the same way in both, and
the prompt must only name tools that are bound (linsight/AGENTS.md lockstep).
These tests drive the REAL graph with a scripted model and read what the model
was actually given: the bound tool names and the assembled system message.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from bisheng.linsight.domain.services import agent_factory
from bisheng.linsight.domain.services.base_prompt import (
    LINSIGHT_BASE_PROMPT_ZH,
    LINSIGHT_DIRECT_BASE_PROMPT_ZH,
    with_base_prompt,
)
from bisheng.linsight.domain.services.workspace_backend import WorkspaceBackend

PLAN_WORDS = ("write_todos", "待办", "【规划】")
FILE_TOOLS = {"ls", "read_file", "write_file", "edit_file", "glob", "grep"}


class _ScriptedModel(BaseChatModel):
    """Answers "done" (or a script) and records what each model call received."""

    script: list[AIMessage] = Field(default_factory=lambda: [AIMessage(content="done")])
    calls: int = 0
    bound_tool_names: list[str] = Field(default_factory=list)
    system_texts: list[str] = Field(default_factory=list)
    inputs: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _get_ls_params(self, stop: Any = None, **kwargs: Any) -> dict[str, str]:
        # Own provider: the factory registers a process-wide harness profile per
        # provider (design §5 pitfall 17).
        return {"ls_provider": "f004-agent-factory-profiles", "ls_model_name": "scripted"}

    def bind_tools(self, tools: Any, **kwargs: Any) -> _ScriptedModel:
        names = []
        for item in tools:
            name = getattr(item, "name", None)
            if name is None and isinstance(item, dict):
                name = item.get("name") or item.get("function", {}).get("name")
            names.append(str(name))
        self.bound_tool_names = names
        return self

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        self.inputs.append(list(messages))
        self.system_texts.append(
            "".join(
                "".join(b.get("text", "") for b in m.content_blocks) for m in messages if isinstance(m, SystemMessage)
            )
        )
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


@tool
def search_knowledge_base(query: str, knowledge_id: str) -> str:
    """Search a knowledge base."""
    return "kb"


@tool
def web_search(query: str) -> str:
    """Search the web."""
    return "web"


@tool
def bisheng_code_interpreter(code: str) -> str:
    """Run python code."""
    return "ran"


@tool
def memory_search(query: str) -> str:
    """Search the user's long-term memory."""
    return "memory"


@tool
def user_selected_tool(text: str) -> str:
    """A tool the user ticked in the tool picker."""
    return "ok"


ALL_BUSINESS_TOOLS = [search_knowledge_base, web_search, bisheng_code_interpreter, memory_search, user_selected_tool]
OPEN_API = {"channel": "open_api_v2"}


async def _run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    *,
    profile: str | None,
    tools: list | None = None,
    api_meta: dict | None = None,
    skills: bool = False,
    memory_prompt: str | None = None,
    checkpointer=None,
    thread_id: str = "t-profiles",
    script: list[AIMessage] | None = None,
) -> _ScriptedModel:
    """Build the real graph for ``profile`` and run one user turn."""
    from bisheng.core.config.settings import LinsightConf

    model = _ScriptedModel(script=script) if script else _ScriptedModel()
    monkeypatch.setattr(agent_factory, "_resolve_model", AsyncMock(return_value=(model, False)))
    monkeypatch.setattr(agent_factory, "settings", SimpleNamespace(get_linsight_conf=lambda: LinsightConf()))
    session = SimpleNamespace(
        id="sv-pf", session_id="chat-pf", tenant_id=1, user_id=1, question="q", api_meta=api_meta, skills=[]
    )
    backend = WorkspaceBackend(svid="sv-pf", minio=_MemoryObjectStore(), file_dir=str(tmp_path))
    kwargs: dict[str, Any] = {}
    if profile is not None:
        kwargs["profile"] = profile
    if skills:
        (tmp_path / "skills").mkdir(exist_ok=True)
    agent = await agent_factory.create_linsight_agent(
        session,
        list(tools or []),
        backend=backend,
        file_dir=str(tmp_path),
        skills_present=skills,
        memory_prompt=memory_prompt,
        checkpointer=checkpointer,
        **kwargs,
    )
    await agent.ainvoke(
        {"messages": [("user", "你好")]}, config={"configurable": {"thread_id": thread_id}, "recursion_limit": 40}
    )
    return model


async def test_direct_has_no_todos(monkeypatch: pytest.MonkeyPatch, tmp_path):
    model = await _run(monkeypatch, tmp_path, profile="direct", tools=ALL_BUSINESS_TOOLS, skills=True)

    assert "write_todos" not in model.bound_tool_names
    system_text = model.system_texts[0]
    for word in PLAN_WORDS:
        assert word not in system_text, word
    # The lean prompt is not the planning one with a line removed.
    assert "深度研究任务智能体" not in system_text
    assert "第 0 步" not in system_text
    assert system_text.count(LINSIGHT_DIRECT_BASE_PROMPT_ZH) == 1
    assert LINSIGHT_BASE_PROMPT_ZH not in system_text
    assert system_text.count(agent_factory._LINSIGHT_LANGUAGE_DIRECTIVE_ZH) == 1

    # Without a skills block the language directive is the tail, as in planned.
    bare = await _run(monkeypatch, tmp_path, profile="direct")
    assert bare.system_texts[0].rstrip().endswith(agent_factory._LINSIGHT_LANGUAGE_DIRECTIVE_ZH.rstrip())


async def test_planned_has_todos(monkeypatch: pytest.MonkeyPatch, tmp_path):
    explicit = await _run(monkeypatch, tmp_path, profile="planned", tools=ALL_BUSINESS_TOOLS)
    default = await _run(monkeypatch, tmp_path, profile=None, tools=ALL_BUSINESS_TOOLS)

    for model in (explicit, default):
        assert "write_todos" in model.bound_tool_names
        assert "1. 【规划】调用 write_todos" in model.system_texts[0]
        assert model.system_texts[0].count(LINSIGHT_BASE_PROMPT_ZH) == 1
    # Omitting the argument is the planned profile, byte for byte.
    assert default.system_texts[0] == explicit.system_texts[0]
    assert default.bound_tool_names == explicit.bound_tool_names
    assert inspect.signature(agent_factory.create_linsight_agent).parameters["profile"].default == "planned"


async def test_unknown_profile_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path):
    with pytest.raises(ValueError, match="profile"):
        await _run(monkeypatch, tmp_path, profile="fast")


@pytest.mark.parametrize(
    "tools,skills,memory_prompt",
    [
        ([], False, None),
        ([search_knowledge_base], False, None),
        ([web_search], False, None),
        ([bisheng_code_interpreter], True, None),
        ([memory_search], False, "MEMORY-BLOCK-F132"),
        (ALL_BUSINESS_TOOLS, True, "MEMORY-BLOCK-F132"),
    ],
)
async def test_same_business_tools_in_both_profiles(
    monkeypatch: pytest.MonkeyPatch, tmp_path, tools, skills, memory_prompt
):
    direct = await _run(
        monkeypatch, tmp_path, profile="direct", tools=tools, skills=skills, memory_prompt=memory_prompt
    )
    planned = await _run(
        monkeypatch, tmp_path, profile="planned", tools=tools, skills=skills, memory_prompt=memory_prompt
    )

    # The plan tool is the only difference between the two bound tool sets.
    assert set(planned.bound_tool_names) - set(direct.bound_tool_names) == {"write_todos"}
    assert set(direct.bound_tool_names) - set(planned.bound_tool_names) == set()
    for name in [t.name for t in tools]:
        assert name in direct.bound_tool_names, name
    # Workspace files (AC-46), delegation and the deliverable tools in both.
    assert FILE_TOOLS | {"task", "export_docx", "export_pdf", "check_html"} <= set(direct.bound_tool_names)
    assert "delete" not in direct.bound_tool_names

    # Prompt <-> tool lockstep on the direct prompt: a conditional tool is named
    # IFF it is bound.
    system_text = direct.system_texts[0]
    for name in ("search_knowledge_base", "bisheng_code_interpreter", "data-analyst"):
        bound = name in direct.bound_tool_names or (name == "data-analyst" and bisheng_code_interpreter in tools)
        assert (name in system_text) is bound, name
    # Skills (AC-45) and memory (AC-48) reach the model in both profiles.
    for model in (direct, planned):
        assert ("可用技能" in model.system_texts[0]) is skills
        assert ("MEMORY-BLOCK-F132" in model.system_texts[0]) is bool(memory_prompt)
    # Citation rules follow the same gate in both.
    citable = search_knowledge_base in tools or web_search in tools
    for model in (direct, planned):
        assert (agent_factory._LINSIGHT_CITATION_TAIL_ZH in model.system_texts[0]) is citable


async def test_ask_user_in_both_profiles(monkeypatch: pytest.MonkeyPatch, tmp_path):
    for profile in ("direct", "planned"):
        model = await _run(monkeypatch, tmp_path, profile=profile, tools=ALL_BUSINESS_TOOLS)
        assert "ask_user" in model.bound_tool_names, profile
        assert "ask_user(reason, questions)" in model.system_texts[0], profile
        assert "# 如何填写 ask_user" in model.system_texts[0], profile


async def test_unattended_has_no_ask_user(monkeypatch: pytest.MonkeyPatch, tmp_path):
    for profile in ("direct", "planned"):
        model = await _run(
            monkeypatch,
            tmp_path,
            profile=profile,
            tools=ALL_BUSINESS_TOOLS,
            api_meta={**OPEN_API, "instructions": "CALLER-INSTRUCTIONS"},
        )
        assert "ask_user" not in model.bound_tool_names, profile
        system_text = model.system_texts[0]
        assert "ask_user" not in system_text, profile
        # The static language tail lists "questions to the user" among the things
        # written in the user's language; the profile's own prompt must not.
        own_prompt = system_text.split(agent_factory._LINSIGHT_LANGUAGE_DIRECTIVE_ZH)[0]
        assert "向用户的提问" not in own_prompt, profile
        assert "所做假设" in system_text, profile
        assert "CALLER-INSTRUCTIONS" in system_text, profile


async def test_profiles_share_one_state_schema(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Design decision 1 / spike S6: the direct graph keeps the ``todos`` channel,
    so one checkpoint thread can go planned -> direct -> planned."""
    saver = InMemorySaver()
    todos = [{"content": "1. 收集资料", "status": "in_progress"}]
    plan_call = AIMessage(
        content="", tool_calls=[{"name": "write_todos", "args": {"todos": todos}, "id": "c1", "type": "tool_call"}]
    )

    await _run(
        monkeypatch,
        tmp_path,
        profile="planned",
        checkpointer=saver,
        thread_id="t-alt",
        script=[plan_call, AIMessage(content="第一轮完成")],
    )
    direct = await _run(monkeypatch, tmp_path, profile="direct", checkpointer=saver, thread_id="t-alt")
    planned = await _run(monkeypatch, tmp_path, profile="planned", checkpointer=saver, thread_id="t-alt")

    def texts(messages: list[BaseMessage]) -> list[str]:
        return [m.content for m in messages if isinstance(m.content, str)]

    assert "第一轮完成" in texts(direct.inputs[0])
    assert texts(planned.inputs[0]).count("done") == 1

    from bisheng.core.config.settings import LinsightConf

    monkeypatch.setattr(agent_factory, "_resolve_model", AsyncMock(return_value=(_ScriptedModel(), False)))
    monkeypatch.setattr(agent_factory, "settings", SimpleNamespace(get_linsight_conf=lambda: LinsightConf()))
    session = SimpleNamespace(id="sv-pf", session_id="chat-pf", tenant_id=1, user_id=1, question="q", api_meta=None)
    agent = await agent_factory.create_linsight_agent(session, [], checkpointer=saver, profile="direct")
    assert "todos" in agent.channels
    state = await agent.aget_state({"configurable": {"thread_id": "t-alt"}})
    assert [dict(t) for t in state.values["todos"]] == todos


@pytest.mark.parametrize("unattended", [False, True])
def test_direct_prompt_follows_the_bound_tools(unattended):
    """Pure prompt builder: every conditional line is driven by a bound tool name."""
    build = agent_factory._build_direct_system_prompt
    bare = build(set(FILE_TOOLS) | ({"ask_user"} if not unattended else set()), unattended=unattended)
    for name in (
        "search_knowledge_base",
        "bisheng_code_interpreter",
        "export_docx",
        "export_pdf",
        "check_html",
        "task(",
        "data-analyst",
        "可用技能",
        "write_todos",
    ):
        assert name not in bare, name
    assert ("ask_user" in bare) is (not unattended)

    full = build(
        set(FILE_TOOLS)
        | {"search_knowledge_base", "bisheng_code_interpreter", "export_docx", "export_pdf", "check_html", "task"}
        | ({"ask_user"} if not unattended else set()),
        skills_present=True,
        unattended=unattended,
        has_data_analyst=True,
    )
    for name in (
        "search_knowledge_base",
        "bisheng_code_interpreter",
        "export_docx",
        "export_pdf",
        "check_html",
        'subagent_type="general-purpose"',
        'subagent_type="data-analyst"',
        "可用技能",
    ):
        assert name in full, name
    for word in PLAN_WORDS:
        assert word not in full, word
    assert ("ask_user" in full) is (not unattended)
    assert "__" not in full


def test_base_prompt_per_profile():
    assert with_base_prompt("主提示词") == f"主提示词\n\n{LINSIGHT_BASE_PROMPT_ZH}"
    assert with_base_prompt("主提示词", profile="planned") == f"主提示词\n\n{LINSIGHT_BASE_PROMPT_ZH}"
    assert with_base_prompt("主提示词", profile="direct") == f"主提示词\n\n{LINSIGHT_DIRECT_BASE_PROMPT_ZH}"
    assert "第 0 步" not in LINSIGHT_DIRECT_BASE_PROMPT_ZH
    assert "ask_user" not in LINSIGHT_DIRECT_BASE_PROMPT_ZH
