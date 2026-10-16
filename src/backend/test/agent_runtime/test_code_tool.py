"""F078 T11: build the code interpreter bound to an agent workspace."""

from types import SimpleNamespace

import pytest

import bisheng.agent_runtime.domain.services.code_tool as code_tool_module
from bisheng.agent_runtime.domain.services.code_tool import CodeToolStatus, abuild_workspace_code_tool
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum


@pytest.fixture
def built(monkeypatch):
    """Capture the tool row ToolExecutor receives instead of building a real tool."""
    calls = {}

    async def _init_by_tool_id(*, tool, app_id, app_name, app_type, user_id, **kwargs):
        calls["tool"] = tool
        calls["user_id"] = user_id
        calls["app_type"] = app_type
        return SimpleNamespace(name="bisheng_code_interpreter")

    monkeypatch.setattr(code_tool_module.ToolExecutor, "init_by_tool_id", _init_by_tool_id)
    return calls


def _row(extra=None, type_id=5):
    return SimpleNamespace(id=9, tool_key="bisheng_code_interpreter", extra=extra, type=type_id)


def _patch_lookup(monkeypatch, row, type_extra=None):
    async def _by_key(tool_key):
        return row

    async def _tool_type(tool_type_id):
        return SimpleNamespace(id=tool_type_id, extra=type_extra)

    monkeypatch.setattr(code_tool_module.GptsToolsDao, "aget_tool_by_tool_key", _by_key)
    monkeypatch.setattr(code_tool_module.GptsToolsDao, "aget_one_tool_type", _tool_type)


async def _build(tmp_path):
    return await abuild_workspace_code_tool(
        file_dir=str(tmp_path),
        workspace_prefix="workspace/agent/c1/wf-n1",
        user_id=7,
        app_type=ApplicationTypeEnum.WORKFLOW,
        app_id="flow-1",
        app_name="Flow",
    )


class TestBuildWorkspaceCodeTool:
    async def test_missing_tool_row_means_not_configured(self, monkeypatch, tmp_path, built):
        _patch_lookup(monkeypatch, None)
        result = await _build(tmp_path)
        assert result.status is CodeToolStatus.MISSING
        assert result.tool is None
        assert built == {}

    async def test_empty_extra_still_builds_the_local_default(self, monkeypatch, tmp_path, built):
        _patch_lookup(monkeypatch, _row(extra=None), type_extra=None)
        result = await _build(tmp_path)
        assert result.status is CodeToolStatus.READY
        local = built["tool"].extra["config"]["local"]
        assert local["local_sync_path"] == str(tmp_path)
        assert local["workspace_prefix"] == "workspace/agent/c1/wf-n1"
        assert built["user_id"] == 7
        assert built["app_type"] is ApplicationTypeEnum.WORKFLOW

    async def test_e2b_copy_in_list_includes_skills(self, monkeypatch, tmp_path, built):
        (tmp_path / "skills" / "docx").mkdir(parents=True)
        (tmp_path / "skills" / "docx" / "SKILL.md").write_text("x")
        _patch_lookup(monkeypatch, _row(extra='{"type": "e2b", "config": {"e2b": {}}}'))
        result = await _build(tmp_path)
        assert result.status is CodeToolStatus.READY
        paths = [entry.path for entry in built["tool"].extra["config"]["e2b"]["file_list"]]
        assert "./skills/docx/SKILL.md" in paths

    async def test_container_gets_the_workspace_prefix(self, monkeypatch, tmp_path, built):
        _patch_lookup(monkeypatch, _row(extra='{"type": "container"}'))
        await _build(tmp_path)
        container = built["tool"].extra["config"]["container"]
        assert container["local_sync_path"] == str(tmp_path)
        assert container["workspace_prefix"] == "workspace/agent/c1/wf-n1"

    async def test_build_failure_is_reported_not_raised(self, monkeypatch, tmp_path):
        _patch_lookup(monkeypatch, _row(extra=None))

        async def _boom(**kwargs):
            raise PermissionError("Permission denied: use")

        monkeypatch.setattr(code_tool_module.ToolExecutor, "init_by_tool_id", _boom)
        result = await _build(tmp_path)
        assert result.status is CodeToolStatus.ERROR
        assert result.tool is None
        assert "Permission denied" in result.reason
