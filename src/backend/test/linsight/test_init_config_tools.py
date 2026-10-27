"""Task infrastructure is authorized and workspace-bound independently of UI selection."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.api.v1.schemas import ToolConfig
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion
from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsDao
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


def _fake_code_tool_row() -> GptsTools:
    return GptsTools(id=CODE_TOOL_ID, type=6, tool_key="bisheng_code_interpreter", extra=None)


@pytest.fixture(autouse=True)
def authorized_container(monkeypatch):
    monkeypatch.setattr(GptsToolsDao, "aget_tool_by_tool_key", AsyncMock(return_value=_fake_code_tool_row()))
    monkeypatch.setattr(
        GptsToolsDao,
        "aget_one_tool_type",
        AsyncMock(return_value=SimpleNamespace(id=6, tenant_id=7, extra={"type": "container"})),
    )
    monkeypatch.setattr(ToolExecutor, "_ensure_use_permission_async", AsyncMock())


async def test_code_interpreter_automatically_bound_when_not_selected(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """The hidden task capability binds alongside the selected optional tool."""
    monkeypatch.setattr(GptsToolsDao, "aget_tool_by_tool_key", AsyncMock(return_value=_fake_code_tool_row()))
    init_one = AsyncMock(return_value=object())
    monkeypatch.setattr(ToolExecutor, "init_by_tool_id", init_one)
    init_many = AsyncMock(return_value=[object()])
    monkeypatch.setattr(ToolExecutor, "init_by_tool_ids", init_many)

    tools = await LinsightWorkbenchImpl.init_linsight_config_tools(
        session_version=_session_with_tools([100]), llm=object(), need_upload=True, file_dir=str(tmp_path)
    )

    init_one.assert_awaited_once()
    assert len(tools) == 2
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
    assert bound_row.extra["config"]["container"]["local_sync_path"] == str(tmp_path)
    assert code_tool in tools
    # The generic pass no longer sees the code-interpreter id -> no duplicate.
    assert init_many.await_args.args[0] == [100]


async def test_empty_selection_binds_authorized_interpreter(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Tasks need executable infrastructure with an empty composer selection."""
    init_one = AsyncMock(return_value=object())
    monkeypatch.setattr(ToolExecutor, "init_by_tool_id", init_one)

    session = _session_with_tools()
    session.tools = []

    tools = await LinsightWorkbenchImpl.init_linsight_config_tools(
        session_version=session, llm=object(), need_upload=True, file_dir=str(tmp_path)
    )

    assert tools == [init_one.return_value]
    init_one.assert_awaited_once()


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

    monkeypatch.setattr(
        GptsToolsDao, "aget_one_tool_type", AsyncMock(return_value=SimpleNamespace(id=6, extra={"type": "e2b"}))
    )
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
    assert bound_row.extra["config"]["e2b"]["local_sync_path"] == str(tmp_path)
    assert bound_row.extra["config"]["e2b"]["workspace_prefix"] == "workspace/SV-1"


async def test_container_binds_workspace_without_e2b_file_list(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Container copy-in happens at run(); do not pre-scan file_list (AC-11)."""
    from bisheng_langchain.gpts.tools.code_interpreter.e2b_executor import SIZE_AUTOPUSH

    (tmp_path / "skills" / "demo").mkdir(parents=True)
    (tmp_path / "skills" / "demo" / "SKILL.md").write_text("hi")
    (tmp_path / "uploads").mkdir()
    (tmp_path / "uploads" / "huge.bin").write_bytes(b"x" * (SIZE_AUTOPUSH + 1))

    row = GptsTools(
        id=CODE_TOOL_ID,
        tool_key="bisheng_code_interpreter",
        type=6,
        extra=json.dumps({"type": "container"}),
    )
    monkeypatch.setattr(GptsToolsDao, "aget_tool_by_tool_key", AsyncMock(return_value=row))
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
    container = bound_row.extra["config"]["container"]
    assert container["local_sync_path"] == str(tmp_path)
    assert container["keep_session"] is True
    assert "workspace_prefix" in container
    assert "file_list" not in bound_row.extra["config"].get("e2b", {})
    tool = ToolExecutor._init_preset_tool(bound_row, SimpleNamespace(extra=None))
    assert "skills/" in tool.description
    assert tool.executor.local_sync_path == str(tmp_path)
    assert row.extra == json.dumps({"type": "container"})


async def test_empty_tool_extra_falls_back_to_category_container(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Built-in-tool UI writes type.extra and NULLs the row; Linsight must still isolate."""
    row = GptsTools(
        id=CODE_TOOL_ID,
        tool_key="bisheng_code_interpreter",
        extra=None,
        type=CODE_TOOL_ID,
    )
    monkeypatch.setattr(GptsToolsDao, "aget_tool_by_tool_key", AsyncMock(return_value=row))
    monkeypatch.setattr(
        GptsToolsDao,
        "aget_one_tool_type",
        AsyncMock(return_value=SimpleNamespace(id=CODE_TOOL_ID, extra=json.dumps({"type": "container"}))),
    )
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
    assert bound_row.extra["type"] == "container"
    assert "file_list" not in bound_row.extra["config"].get("e2b", {})
    assert bound_row.extra["config"]["container"]["local_sync_path"] == str(tmp_path)


async def test_tool_row_extra_wins_over_category(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """A non-empty tool row is exclusive, same as parse_preset_tool_params."""
    row = GptsTools(
        id=CODE_TOOL_ID,
        tool_key="bisheng_code_interpreter",
        extra=json.dumps({"type": "e2b"}),
        type=CODE_TOOL_ID,
    )
    monkeypatch.setattr(GptsToolsDao, "aget_tool_by_tool_key", AsyncMock(return_value=row))
    monkeypatch.setattr(
        GptsToolsDao,
        "aget_one_tool_type",
        AsyncMock(return_value=SimpleNamespace(id=CODE_TOOL_ID, extra=json.dumps({"type": "container"}))),
    )
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
    assert bound_row.extra["type"] == "e2b"
    # E2B pre-scans its copy-in set using the tool-level configuration.
    assert "file_list" in bound_row.extra["config"]["e2b"]


@pytest.mark.parametrize("executor_type", ["local", "container", "e2b"])
@pytest.mark.parametrize("explicit", [False, True])
async def test_permission_denial_preserves_optional_tools(monkeypatch, tmp_path, explicit, executor_type):
    monkeypatch.setattr(
        GptsToolsDao,
        "aget_one_tool_type",
        AsyncMock(return_value=SimpleNamespace(id=6, tenant_id=7, extra={"type": executor_type})),
    )
    monkeypatch.setattr(ToolExecutor, "_ensure_use_permission_async", AsyncMock(side_effect=PermissionError("denied")))
    init_one = AsyncMock()
    monkeypatch.setattr(ToolExecutor, "init_by_tool_id", init_one)
    other = object()
    monkeypatch.setattr(ToolExecutor, "init_by_tool_ids", AsyncMock(return_value=[other]))
    session = _session_with_tools([100, CODE_TOOL_ID] if explicit else [100])
    if explicit:
        with pytest.raises(PermissionError):
            await LinsightWorkbenchImpl.init_linsight_config_tools(session, object(), True, str(tmp_path))
    else:
        assert await LinsightWorkbenchImpl.init_linsight_config_tools(session, object(), True, str(tmp_path)) == [other]
    init_one.assert_not_awaited()


async def test_initialization_failure_surfaces_before_model_execution(monkeypatch, tmp_path):
    monkeypatch.setattr(ToolExecutor, "init_by_tool_id", AsyncMock(side_effect=RuntimeError("sandbox unavailable")))
    with pytest.raises(RuntimeError, match="sandbox unavailable"):
        await LinsightWorkbenchImpl.init_linsight_config_tools(_session_with_tools(), object(), True, str(tmp_path))


@pytest.mark.parametrize("executor_type", ["local", None, ""])
@pytest.mark.parametrize("selected", [[], [CODE_TOOL_ID], [100, CODE_TOOL_ID]])
async def test_local_executor_binds_task_workspace(monkeypatch, tmp_path, executor_type, selected):
    from bisheng_langchain.gpts.tools.code_interpreter.local_executor import LocalExecutor

    extra = {"type": executor_type} if executor_type is not None else {}
    category = SimpleNamespace(id=6, tenant_id=7, extra=extra)
    monkeypatch.setattr(GptsToolsDao, "aget_one_tool_type", AsyncMock(return_value=category))
    init_one = AsyncMock(side_effect=lambda tool, **kwargs: ToolExecutor._init_preset_tool(tool, category))
    monkeypatch.setattr(ToolExecutor, "init_by_tool_id", init_one)
    init_many = AsyncMock(return_value=[])
    monkeypatch.setattr(ToolExecutor, "init_by_tool_ids", init_many)
    session = _session_with_tools()
    session.tools = [{"children": [{"id": tid} for tid in selected]}]

    tools = await LinsightWorkbenchImpl.init_linsight_config_tools(session, object(), True, str(tmp_path))

    init_one.assert_awaited_once()
    assert len(tools) == 1
    assert isinstance(tools[0].executor, LocalExecutor)
    assert tools[0].executor.local_sync_path == str(tmp_path)
    assert tools[0].executor.workspace_prefix == "workspace/SV-1"
    assert init_one.await_args.kwargs["tool"].extra["config"] == {
        "local": {"local_sync_path": str(tmp_path), "workspace_prefix": "workspace/SV-1"}
    }
    assert category.extra == extra
    if 100 in selected:
        assert init_many.await_args.args[0] == [100]
    else:
        init_many.assert_not_awaited()


async def test_local_workspace_binding_preserves_admin_options(monkeypatch, tmp_path):
    extra = {
        "type": "local",
        "config": {
            "local": {
                "local_sync_path": "/previous/task",
                "workspace_prefix": "workspace/previous",
                "timeout": 90,
            }
        },
    }
    row = GptsTools(id=CODE_TOOL_ID, type=6, tool_key="bisheng_code_interpreter", extra=json.dumps(extra))
    monkeypatch.setattr(GptsToolsDao, "aget_tool_by_tool_key", AsyncMock(return_value=row))
    init_one = AsyncMock(return_value=object())
    monkeypatch.setattr(ToolExecutor, "init_by_tool_id", init_one)

    # Local execution uses the workspace directly, including large input files.
    def unexpected_scan(*args, **kwargs):
        pytest.fail("Local initialization should use the task directory directly")

    monkeypatch.setattr("bisheng.linsight.domain.services.workbench_impl.os.walk", unexpected_scan)

    await LinsightWorkbenchImpl._init_bisheng_code_tool([], str(tmp_path), 42, "current")

    assert init_one.await_args.kwargs["tool"].extra["config"] == {
        "local": {
            "local_sync_path": str(tmp_path),
            "workspace_prefix": "workspace/current",
            "timeout": 90,
        }
    }
    assert json.loads(row.extra) == extra


async def test_unknown_executor_type_reports_configuration_error(monkeypatch, tmp_path):
    from bisheng.common.errcode.sandbox import SandboxConfigurationError

    monkeypatch.setattr(
        GptsToolsDao, "aget_one_tool_type", AsyncMock(return_value=SimpleNamespace(id=6, extra={"type": "unknown"}))
    )
    with pytest.raises(SandboxConfigurationError):
        await LinsightWorkbenchImpl.init_linsight_config_tools(_session_with_tools(), object(), True, str(tmp_path))


async def test_missing_interpreter_keeps_optional_tools(monkeypatch, tmp_path):
    monkeypatch.setattr(GptsToolsDao, "aget_tool_by_tool_key", AsyncMock(return_value=None))
    other = object()
    monkeypatch.setattr(ToolExecutor, "init_by_tool_ids", AsyncMock(return_value=[other]))
    assert await LinsightWorkbenchImpl.init_linsight_config_tools(
        _session_with_tools(), object(), True, str(tmp_path)
    ) == [other]


def test_task_metadata_uses_host_runner_credentials(monkeypatch, tmp_path):
    from bisheng.common.services.config_service import settings
    from bisheng.core.config.settings import SandboxConf

    monkeypatch.setattr(
        "bisheng.tool.domain.services.executor.settings",
        SimpleNamespace(
            sandbox_conf=SandboxConf(endpoints=["http://trusted:8080"], token="host-only"),
            get_minio_conf=settings.get_minio_conf,
        ),
    )
    row = GptsTools(
        tool_key="bisheng_code_interpreter",
        extra={
            "type": "container",
            "config": {
                "container": {
                    "local_sync_path": str(tmp_path),
                    "endpoints": ["http://untrusted:8080"],
                    "token": "task-value",
                }
            },
        },
    )
    tool = ToolExecutor._init_preset_tool(row, SimpleNamespace(extra=None))
    assert tool.executor.endpoints == ["http://trusted:8080"]
    assert tool.executor.token == "host-only"
