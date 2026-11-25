"""One tool-assembly function for the direct and the planned profile (F004 T021).

Covers AC: AC-05, AC-43, AC-44, AC-45
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.tools import StructuredTool

from bisheng.citation.domain.services.citation_prompt_helper import CitationRegistryCollector
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion
from bisheng.linsight.domain.services.tool_assembly import ToolAssemblyRequest, assemble_tools
from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsDao
from bisheng.tool.domain.services.executor import ToolExecutor
from bisheng.workstation.domain.services import chat_service
from bisheng.workstation.domain.services.chat_service import _prepare_tools

CODE_KEY = "bisheng_code_interpreter"
CODE_ID = 6
CALC_ID = 100
WEB_ID = 1
BROKEN_ID = 200


def _named_tool(name: str) -> StructuredTool:
    def _run(query: str = "") -> str:
        return "[]"

    return StructuredTool.from_function(func=_run, name=name, description=f"{name} tool")


_TOOL_NAME_BY_ID = {CALC_ID: "calculator", WEB_ID: "web_search", CODE_ID: CODE_KEY, 300: "weather"}


@pytest.fixture
def tool_runtime(monkeypatch):
    """In-memory stand-ins for the tool tables and the tool executor."""
    code_row = GptsTools(id=CODE_ID, type=6, tool_key=CODE_KEY, extra=None)

    async def by_key(tool_key: str):
        return code_row if tool_key == CODE_KEY else None

    async def init_one(tool_id=None, tool=None, **_kwargs):
        if tool is not None:
            return _named_tool(tool.tool_key)
        if tool_id == BROKEN_ID:
            raise RuntimeError("Request failed: 403 - not enough quota")
        return _named_tool(_TOOL_NAME_BY_ID[tool_id])

    async def init_many(tool_ids, **_kwargs):
        return [_named_tool(_TOOL_NAME_BY_ID[tool_id]) for tool_id in tool_ids]

    async def web_search(user_id, tool_id=None):
        return _named_tool("web_search"), None

    calls = SimpleNamespace(
        init_one=AsyncMock(side_effect=init_one),
        init_many=AsyncMock(side_effect=init_many),
    )
    monkeypatch.setattr(GptsToolsDao, "aget_tool_by_tool_key", AsyncMock(side_effect=by_key))
    monkeypatch.setattr(
        GptsToolsDao,
        "aget_one_tool_type",
        AsyncMock(return_value=SimpleNamespace(id=6, tenant_id=7, extra={"type": "container"})),
    )
    monkeypatch.setattr(ToolExecutor, "_ensure_use_permission_async", AsyncMock())
    monkeypatch.setattr(ToolExecutor, "init_by_tool_id", calls.init_one)
    monkeypatch.setattr(ToolExecutor, "init_by_tool_ids", calls.init_many)
    monkeypatch.setattr(chat_service, "_build_web_search_tool", AsyncMock(side_effect=web_search))
    return calls


def _login_user(user_id: int = 42):
    return SimpleNamespace(user_id=user_id, user_name="tester")


_KB_INFO = [
    {"id": 1, "name": "org-kb", "description": "", "tags": [], "source": "organization"},
    {"id": 2, "name": "my-space", "description": "", "tags": [], "source": "space"},
]


async def test_assembly_superset_of_both_paths(tool_runtime, tmp_path):
    """The same request binds every tool either of today's two paths binds."""
    payloads = [
        {"id": CALC_ID, "tool_key": "calculator", "type": "tool"},
        {"id": WEB_ID, "tool_key": "web_search", "type": "tool"},
        {"id": CODE_ID, "tool_key": CODE_KEY, "type": "tool"},
    ]
    user = _login_user()

    daily_tools, daily_failures = await _prepare_tools(
        tool_payloads=payloads,
        login_user=user,
        ws_config=SimpleNamespace(maxTokens=1000),
        citation_collector=CitationRegistryCollector(),
        knowledge_bases_info=_KB_INFO,
    )
    session = LinsightSessionVersion(
        id="SV-1",
        session_id="chat-1",
        user_id=user.user_id,
        question="q",
        tenant_id=7,
        tools=[{"children": [{"id": CALC_ID}, {"id": WEB_ID}, {"id": CODE_ID}]}],
    )
    planned_tools = await LinsightWorkbenchImpl.init_linsight_config_tools(
        session_version=session, llm=object(), need_upload=True, file_dir=str(tmp_path)
    )
    assert daily_failures == []
    daily_names = {t.name for t in daily_tools}
    planned_names = {t.name for t in planned_tools}
    # Guard the premise: each legacy path contributes something of its own.
    assert daily_names == {"calculator", "web_search", CODE_KEY, "search_knowledge_bases"}
    assert planned_names == {"calculator", "web_search", CODE_KEY}

    tool_runtime.init_one.reset_mock()
    assembly = await assemble_tools(
        ToolAssemblyRequest(
            user_id=user.user_id,
            login_user=user,
            tool_payloads=payloads,
            knowledge_bases_info=_KB_INFO,
            kb_max_token=1000,
            citation_collector=CitationRegistryCollector(),
            file_dir=str(tmp_path),
            session_version_id="SV-1",
        )
    )

    names = [t.name for t in assembly.tools]
    assert set(names) >= daily_names | planned_names
    assert len(names) == len(set(names)), f"a tool was bound twice: {names}"
    assert assembly.failures == []
    # The deep-research capability survives: the interpreter is the workspace-bound one.
    bound_rows = [c.kwargs["tool"] for c in tool_runtime.init_one.await_args_list if c.kwargs.get("tool")]
    assert len(bound_rows) == 1
    assert bound_rows[0].extra["config"]["container"]["local_sync_path"] == str(tmp_path)
    # The daily capability survives: web results still go through the citation wrapper.
    web = next(t for t in assembly.tools if t.name == "web_search")
    assert isinstance(web, chat_service.DailyChatCitationToolWrapper)


async def test_assembly_accepts_the_planned_selection_shape(tool_runtime, tmp_path):
    """A tool tree (deep-research selection) and flat payloads select the same tools."""
    assembly = await assemble_tools(
        ToolAssemblyRequest(
            user_id=42,
            login_user=_login_user(),
            tool_tree=[{"children": [{"id": CALC_ID}, {"id": WEB_ID}, {"id": CODE_ID}, {"id": CALC_ID}]}],
            file_dir=str(tmp_path),
            session_version_id="SV-1",
        )
    )

    assert sorted(t.name for t in assembly.tools) == sorted(["calculator", "web_search", CODE_KEY])
    assert assembly.failures == []


async def test_kb_scope_limited_to_permitted(tool_runtime, monkeypatch):
    """The knowledge tool searches only the selected bases, as the requesting user."""
    from bisheng.workstation.domain.services.workstation_service import WorkStationService

    captured = {}

    async def query(question, use_knowledge_param, max_token, login_user):
        captured.update(param=use_knowledge_param, login_user=login_user)
        # The retrieval layer rejects the base this user may not read.
        return "", [], [{"id": 1, "name": "org-kb", "error": "no permission"}]

    monkeypatch.setattr(WorkStationService, "queryChunksFromDB", AsyncMock(side_effect=query))
    monkeypatch.setattr(chat_service, "cache_citation_registry_items", AsyncMock())
    user = _login_user(user_id=77)

    assembly = await assemble_tools(
        ToolAssemblyRequest(
            user_id=user.user_id,
            login_user=user,
            knowledge_bases_info=_KB_INFO,
            citation_collector=CitationRegistryCollector(),
        )
    )

    assert [t.name for t in assembly.tools] == ["search_knowledge_bases"]
    # 999 was never selected by the user; the model cannot widen the scope.
    output = await assembly.tools[0].ainvoke({"knowledge_base_ids": ["1", "999"], "query": "policy"})

    param = captured["param"]
    assert list(param.organization_knowledge_ids) == [1]
    assert list(param.knowledge_space_ids) == []
    assert captured["login_user"] is user
    assert "no permission" in json.dumps(json.loads(output), ensure_ascii=False)


async def test_single_tool_failure_isolated(tool_runtime, tmp_path):
    """One tool that cannot initialise leaves the others bound and is reported."""
    assembly = await assemble_tools(
        ToolAssemblyRequest(
            user_id=42,
            login_user=_login_user(),
            tool_payloads=[
                {"id": CALC_ID, "tool_key": "calculator", "type": "tool"},
                {"id": BROKEN_ID, "tool_key": "broken_api", "type": "tool"},
                {"id": WEB_ID, "tool_key": "web_search", "type": "tool"},
            ],
            citation_collector=CitationRegistryCollector(),
            file_dir=str(tmp_path),
            session_version_id="SV-1",
        )
    )

    assert sorted(t.name for t in assembly.tools) == sorted(["calculator", "web_search", CODE_KEY])
    assert [f["tool_key"] for f in assembly.failures] == ["broken_api"]
    assert assembly.failures[0]["error"]

    events = assembly.failure_events()
    assert len(events) == 1
    assert events[0]["type"] == "tool_call"
    data = events[0]["data"]
    assert data["tool_name"] == "broken_api"
    assert data["error"] == assembly.failures[0]["error"]
    assert data["tool_call_id"]


async def test_workspace_interpreter_failure_isolated(tool_runtime, tmp_path):
    """A sandbox that cannot start is reported; the selected tools still bind."""

    async def init_one(tool_id=None, tool=None, **_kwargs):
        if tool is not None:
            raise RuntimeError("sandbox unavailable")
        return _named_tool(_TOOL_NAME_BY_ID[tool_id])

    tool_runtime.init_one.side_effect = init_one
    assembly = await assemble_tools(
        ToolAssemblyRequest(
            user_id=42,
            login_user=_login_user(),
            tool_payloads=[{"id": CALC_ID, "tool_key": "calculator", "type": "tool"}],
            file_dir=str(tmp_path),
            session_version_id="SV-1",
        )
    )

    assert [t.name for t in assembly.tools] == ["calculator"]
    assert [f["tool_key"] for f in assembly.failures] == [CODE_KEY]
    assert assembly.failures[0]["error"]


async def test_independent_tools_initialise_concurrently(tool_runtime):
    """Every independent initialisation is in flight before any of them returns."""
    started = 0
    all_started = asyncio.Event()

    async def init_one(tool_id=None, tool=None, **_kwargs):
        nonlocal started
        started += 1
        if started == 3:
            all_started.set()
        await asyncio.wait_for(all_started.wait(), timeout=2)
        return _named_tool(_TOOL_NAME_BY_ID[tool_id])

    tool_runtime.init_one.side_effect = init_one
    payloads = [
        {"id": CALC_ID, "tool_key": "calculator", "type": "tool"},
        {"id": 300, "tool_key": "weather", "type": "tool"},
        {"id": CODE_ID, "tool_key": CODE_KEY, "type": "tool"},
    ]

    assembly = await assemble_tools(ToolAssemblyRequest(user_id=42, login_user=_login_user(), tool_payloads=payloads))
    assert [t.name for t in assembly.tools] == ["calculator", "weather", CODE_KEY]
    assert assembly.failures == []

    # The daily entry point shares the implementation, so it is concurrent too,
    # and it keeps the order the user selected the tools in.
    started = 0
    all_started.clear()
    tools, failures = await _prepare_tools(
        tool_payloads=payloads,
        login_user=_login_user(),
        ws_config=SimpleNamespace(maxTokens=1000),
        citation_collector=CitationRegistryCollector(),
    )
    assert [t.name for t in tools] == ["calculator", "weather", CODE_KEY]
    assert failures == []


async def test_daily_entry_point_keeps_its_failure_shape(tool_runtime):
    """`_prepare_tools` still returns (tools, failures) in today's shape."""
    tools, failures = await _prepare_tools(
        tool_payloads=[
            {"id": BROKEN_ID, "tool_key": "broken_api", "type": "tool"},
            {"id": CALC_ID, "tool_key": "calculator", "type": "tool"},
            {"id": 9, "tool_key": "kb", "type": "knowledge"},
        ],
        login_user=MagicMock(user_id=42),
        ws_config=SimpleNamespace(maxTokens=1000),
        citation_collector=CitationRegistryCollector(),
    )

    assert [t.name for t in tools] == ["calculator"]
    assert len(failures) == 1
    assert failures[0]["tool_key"] == "broken_api"
    assert failures[0]["tool_type"] == "tool"
    assert failures[0]["display_name"] == "broken_api"
    # The text the daily SSE loop shows today for a tool that cannot start.
    assert "Tool execution failed." in failures[0]["error"]
