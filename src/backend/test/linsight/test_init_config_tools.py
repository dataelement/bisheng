"""Linsight tool init: the code interpreter follows the user's tool selection.

Unified-resource direction (2026-06-16): task mode reuses the DAILY chat tool
selection. The code interpreter used to be gated on the daily *config* whitelist
(the admin-configured candidate list), which bound it on every task turn no
matter what the user toggled in the input bar. It is now gated on the per-turn
selection persisted in ``session_version.tools``, like every other tool.

Three behaviours are pinned:
1. Not selected -> not bound (the daily-config whitelist no longer opts it in).
2. Selected -> bound once, with the workspace dir; the generic
   ``init_by_tool_ids`` pass must not build a second, workspace-less copy.
3. ``_extract_tool_ids`` tolerates pydantic ``ToolConfig`` models as well as the
   raw dicts stored on ``session_version.tools``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.api.v1.schemas import ToolConfig
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion
from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl
from bisheng.tool.domain.models.gpts_tools import GptsToolsDao
from bisheng.tool.domain.services.executor import ToolExecutor

CODE_TOOL_ID = 6


def _session_with_tools(tool_ids: list[int] | None = None) -> LinsightSessionVersion:
    return LinsightSessionVersion(
        id="SV-1",
        session_id="chat-1",
        user_id=42,
        question="帮我写周报",
        tenant_id=7,
        tools=[{"children": [{"id": tid} for tid in (tool_ids or [100])]}],
    )


def _fake_code_tool_row() -> SimpleNamespace:
    return SimpleNamespace(id=CODE_TOOL_ID, tool_key="bisheng_code_interpreter", extra=None)


async def test_code_interpreter_skipped_when_not_selected(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """User did not toggle the code interpreter -> it must not be bound."""
    monkeypatch.setattr(GptsToolsDao, "aget_tool_by_tool_key", AsyncMock(return_value=_fake_code_tool_row()))
    init_one = AsyncMock(return_value=object())
    monkeypatch.setattr(ToolExecutor, "init_by_tool_id", init_one)
    init_many = AsyncMock(return_value=[object()])
    monkeypatch.setattr(ToolExecutor, "init_by_tool_ids", init_many)

    tools = await LinsightWorkbenchImpl.init_linsight_config_tools(
        session_version=_session_with_tools([100]), llm=object(), need_upload=True, file_dir=str(tmp_path)
    )

    init_one.assert_not_awaited()
    assert len(tools) == 1
    assert init_many.await_args.args[0] == [100]


async def test_code_interpreter_bound_once_when_selected(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Selected -> bound with the workspace dir, and never built a second time."""
    monkeypatch.setattr(GptsToolsDao, "aget_tool_by_tool_key", AsyncMock(return_value=_fake_code_tool_row()))
    code_tool = object()
    init_one = AsyncMock(return_value=code_tool)
    monkeypatch.setattr(ToolExecutor, "init_by_tool_id", init_one)
    init_many = AsyncMock(return_value=[object()])
    monkeypatch.setattr(ToolExecutor, "init_by_tool_ids", init_many)

    tools = await LinsightWorkbenchImpl.init_linsight_config_tools(
        session_version=_session_with_tools([100, CODE_TOOL_ID]),
        llm=object(),
        need_upload=True,
        file_dir=str(tmp_path),
    )

    # Built once, through the workspace-aware path, and carrying the sync path.
    init_one.assert_awaited_once()
    bound_row = init_one.await_args.kwargs["tool"]
    assert bound_row.extra["config"]["local"]["local_sync_path"] == str(tmp_path)
    assert code_tool in tools
    # The generic pass no longer sees the code-interpreter id -> no duplicate.
    assert init_many.await_args.args[0] == [100]


async def test_no_tools_selected_binds_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Empty selection short-circuits: not even the code interpreter binds."""
    init_one = AsyncMock(return_value=object())
    monkeypatch.setattr(ToolExecutor, "init_by_tool_id", init_one)

    session = _session_with_tools()
    session.tools = []

    tools = await LinsightWorkbenchImpl.init_linsight_config_tools(
        session_version=session, llm=object(), need_upload=True, file_dir=str(tmp_path)
    )

    assert tools == []
    init_one.assert_not_awaited()


def test_extract_tool_ids_tolerates_pydantic_models():
    """Daily config tools come back as ToolConfig models, not raw dicts."""
    model_tools = [ToolConfig(id=1, name="grp", children=[{"id": 11}, {"id": 12}])]
    assert LinsightWorkbenchImpl._extract_tool_ids(model_tools) == [11, 12]
    # raw-dict shape (session_version.tools / linsight config) still works
    assert LinsightWorkbenchImpl._extract_tool_ids([{"children": [{"id": 21}]}]) == [21]


# Legacy local_file tools (list_files / read_text_file / add_text_to_file / ...)
# are retired in task mode: deepagents' FilesystemMiddleware already provides
# ls/read_file/write_file/edit_file over the same WorkspaceBackend, so injecting
# the old ones duplicated the file toolset and confused the model.
_LEGACY_LOCAL_FILE_TOOL_NAMES = {
    "list_files",
    "get_file_details",
    "search_files",
    "read_text_file",
    "add_text_to_file",
    "replace_file_lines",
}


async def test_init_linsight_tools_drops_legacy_local_file_tools():
    """init_linsight_tools must not surface the retired local_file tools."""
    from bisheng.tool.domain.services.tool import ToolServices

    tools = await ToolServices.init_linsight_tools(root_path="/tmp/linsight-test")
    names = {t.name for t in tools}

    assert not (names & _LEGACY_LOCAL_FILE_TOOL_NAMES), (
        f"legacy local_file tools must be removed, found: {names & _LEGACY_LOCAL_FILE_TOOL_NAMES}"
    )
    # Knowledge retrieval is NOT provided by deepagents — it must stay.
    assert "search_knowledge_base" in names


async def test_get_linsight_tools_drops_file_operation_group():
    """The frontend tool tree must no longer advertise the legacy file-op group."""
    from bisheng.tool.domain.services.tool import ToolServices

    groups = await ToolServices.get_linsight_tools()
    child_keys = {child.tool_key for grp in groups for child in (grp.children or [])}

    assert not (child_keys & _LEGACY_LOCAL_FILE_TOOL_NAMES)
    assert "search_knowledge_base" in child_keys


async def test_e2b_file_list_honours_autopush_ceiling(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """E2bCodeExecutor reads every file_list entry fully into worker memory and
    pushes it into the sandbox up front; E2B's own contract caps that at
    SIZE_AUTOPUSH. The dual-track ingest keeps originals up to 50MB because
    LocalExecutor serves those for free — so the ceiling belongs on this side only.
    """
    from bisheng_langchain.gpts.tools.code_interpreter.e2b_executor import SIZE_AUTOPUSH

    (tmp_path / "uploads").mkdir()
    (tmp_path / "uploads" / "small.xlsx").write_bytes(b"x" * 1024)
    (tmp_path / "uploads" / "huge.xlsx").write_bytes(b"x" * (SIZE_AUTOPUSH + 1))

    monkeypatch.setattr(GptsToolsDao, "aget_tool_by_tool_key", AsyncMock(return_value=_fake_code_tool_row()))
    init_one = AsyncMock(return_value=object())
    monkeypatch.setattr(ToolExecutor, "init_by_tool_id", init_one)
    monkeypatch.setattr(ToolExecutor, "init_by_tool_ids", AsyncMock(return_value=[]))

    await LinsightWorkbenchImpl.init_linsight_config_tools(
        session_version=_session_with_tools([CODE_TOOL_ID]),
        llm=object(),
        need_upload=True,
        file_dir=str(tmp_path),
    )

    bound_row = init_one.await_args.kwargs["tool"]
    pushed = {entry.path for entry in bound_row.extra["config"]["e2b"]["file_list"]}
    assert "./uploads/small.xlsx" in pushed
    assert "./uploads/huge.xlsx" not in pushed
    # LocalExecutor still reaches the big one through the shared directory.
    assert bound_row.extra["config"]["local"]["local_sync_path"] == str(tmp_path)
