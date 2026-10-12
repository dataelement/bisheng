"""Robot-bound tools do not depend on a sender's personal tool grants."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.assistant.domain.schemas.execution import (
    AssistantEntryPoint,
    AssistantExecutionContext,
    AssistantRobotScope,
)
from bisheng.eplus.domain.services.robot_space_retrieval import RobotToolScopeViolation
from bisheng.tool.domain.services.executor import ToolExecutor, ToolInitializationError
from test.eplus.test_eplus_tool_scope import SafeTool, _agent


def _context(entry_point, *, with_scope=True):
    return AssistantExecutionContext(
        entry_point=entry_point,
        user_id=88,
        external_user_id="raw-user-id",
        content="hello",
        robot_scope=AssistantRobotScope(bot_config_id=3, space_ids=(), scope_version=7) if with_scope else None,
    )


@pytest.fixture
def bound_tools(monkeypatch):
    links = [SimpleNamespace(tool_id=38, knowledge_id=None, flow_id=None)]
    monkeypatch.setattr(
        "bisheng.api.services.assistant_agent.AssistantLinkDao.get_assistant_link",
        AsyncMock(return_value=links),
    )

    async def load_tools(ids):
        # The robot must not load tools outside its assistant's configuration.
        assert ids == [38]
        return [SimpleNamespace(id=38, type=16)]

    monkeypatch.setattr("bisheng.tool.domain.services.executor.GptsToolsDao.aget_list_by_ids", load_tools)
    monkeypatch.setattr(
        "bisheng.tool.domain.services.executor.GptsToolsDao.aget_all_tool_type",
        AsyncMock(return_value=[SimpleNamespace(id=16, tenant_id=9)]),
    )
    monkeypatch.setattr(
        ToolExecutor, "_init_by_tool_and_type", lambda tool, tool_type, **kwargs: SafeTool(name="web_search")
    )
    monkeypatch.setattr(AssistantAgent, "wrap_citation_tool", lambda self, tool: tool)
    return links


async def test_robot_bound_search_loads_without_permission_runtime(monkeypatch, bound_tools):
    async def missing_runtime(*args, **kwargs):
        raise KeyError("Context 'permission_runtime' not found")

    monkeypatch.setattr(ToolExecutor, "_ensure_use_permission_async", missing_runtime)
    agent = _agent()
    await agent.init_tools(context=_context(AssistantEntryPoint.EPLUS))
    assert [tool.name for tool in agent.tools] == ["web_search"]


@pytest.mark.parametrize("entry_point", [None, AssistantEntryPoint.INTERNAL])
async def test_internal_assistant_still_filters_personally_denied_tools(monkeypatch, bound_tools, entry_point):
    async def denied(*args, **kwargs):
        raise PermissionError("Permission denied: use")

    monkeypatch.setattr(ToolExecutor, "_ensure_use_permission_async", denied)
    agent = _agent()
    await agent.init_tools(context=_context(entry_point) if entry_point else None)
    assert agent.tools == []


async def test_internal_assistant_does_not_fail_open_when_runtime_is_missing(monkeypatch, bound_tools):
    async def missing_runtime(*args, **kwargs):
        raise KeyError("Context 'permission_runtime' not found")

    monkeypatch.setattr(ToolExecutor, "_ensure_use_permission_async", missing_runtime)
    with pytest.raises(KeyError, match="permission_runtime"):
        await _agent().init_tools(context=_context(AssistantEntryPoint.INTERNAL))


async def test_invalid_robot_scope_is_rejected_before_loading_tools(monkeypatch, bound_tools):
    async def unexpected_load(*args, **kwargs):
        pytest.fail("Tools must not be loaded before the robot scope is validated")

    monkeypatch.setattr(ToolExecutor, "init_by_tool_ids", unexpected_load)
    with pytest.raises(RobotToolScopeViolation, match="robot scope"):
        await _agent().init_tools(context=_context(AssistantEntryPoint.EPLUS, with_scope=False))


async def test_robot_bound_tools_cannot_bypass_knowledge_scope(monkeypatch, bound_tools):
    monkeypatch.setattr(ToolExecutor, "_ensure_use_permission_async", AsyncMock())
    monkeypatch.setattr(
        ToolExecutor,
        "_init_by_tool_and_type",
        lambda *args, **kwargs: SimpleNamespace(
            name="knowledge_api", tool_instance=SimpleNamespace(endpoint="/api/v1/knowledge/42/search")
        ),
    )
    with pytest.raises(RobotToolScopeViolation, match="knowledge endpoint"):
        await _agent().init_tools(context=_context(AssistantEntryPoint.EPLUS))


async def test_robot_bound_tools_still_report_invalid_tool_configuration(monkeypatch, bound_tools):
    def invalid_configuration(*args, **kwargs):
        raise ValueError("invalid search configuration")

    monkeypatch.setattr(ToolExecutor, "_init_by_tool_and_type", invalid_configuration)
    with pytest.raises(ToolInitializationError, match="invalid search configuration"):
        await _agent().init_tools(context=_context(AssistantEntryPoint.EPLUS))


async def test_robot_bound_tools_still_require_a_visible_tool_type(monkeypatch, bound_tools):
    monkeypatch.setattr(
        "bisheng.tool.domain.services.executor.GptsToolsDao.aget_all_tool_type",
        AsyncMock(return_value=[]),
    )
    with pytest.raises(ValueError, match="Tool type with id 16 not found"):
        await _agent().init_tools(context=_context(AssistantEntryPoint.EPLUS))
