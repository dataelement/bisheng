from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.assistant.domain.schemas.execution import (
    AssistantEntryPoint,
    AssistantExecutionContext,
    AssistantRobotScope,
)
from bisheng.eplus.domain.services.robot_space_retrieval import (
    RobotToolScopeViolation,
    assert_eplus_tool_scope,
    flow_uses_bisheng_knowledge,
)


class _Args(BaseModel):
    query: str


class SafeTool(BaseTool):
    name: str = "weather"
    description: str = "weather"
    args_schema: type[BaseModel] = _Args

    def _run(self, query: str):
        return query


def _agent() -> AssistantAgent:
    agent = object.__new__(AssistantAgent)
    agent.assistant = SimpleNamespace(
        id="assistant-1",
        name="assistant",
        tenant_id=9,
        user_id=1,
        knowledge_auth=True,
    )
    agent.invoke_user_id = 88
    agent.llm = object()
    agent.knowledge_retriever = {"max_content": 15000, "sort_by_source_and_index": False}
    agent.citation_registry_collector = SimpleNamespace(clear=lambda: None, list_items=list)
    return agent


def _context() -> AssistantExecutionContext:
    return AssistantExecutionContext(
        entry_point=AssistantEntryPoint.EPLUS,
        user_id=88,
        external_user_id="raw-user-id",
        content="hello",
        robot_scope=AssistantRobotScope(bot_config_id=3, space_ids=(11, 12), scope_version=7),
    )


async def test_eplus_replaces_assistant_link_knowledge_but_keeps_safe_external_tools():
    agent = _agent()
    safe_tool = SafeTool()
    robot_tool = SafeTool(name="eplus_robot_knowledge", description="robot knowledge")
    links = [
        SimpleNamespace(tool_id=5, knowledge_id=None, flow_id=None),
        SimpleNamespace(tool_id=None, knowledge_id=999, flow_id=None),
    ]

    with (
        patch(
            "bisheng.api.services.assistant_agent.AssistantLinkDao.get_assistant_link",
            AsyncMock(return_value=links),
        ),
        patch(
            "bisheng.api.services.assistant_agent.ToolExecutor.init_by_tool_ids",
            AsyncMock(return_value=[safe_tool]),
        ),
        patch(
            "bisheng.api.services.assistant_agent.ToolExecutor.init_knowledge_tool",
            AsyncMock(),
        ) as original_knowledge,
        patch(
            "bisheng.eplus.domain.services.robot_space_retrieval.RobotSpaceRetrievalPolicy.build_tool",
            AsyncMock(return_value=robot_tool),
        ) as build_robot_tool,
        patch.object(AssistantAgent, "wrap_citation_tool", lambda self, tool: tool),
        patch.object(AssistantAgent, "_resolve_kb_name_by_id", staticmethod(lambda ids: {})),
    ):
        await agent.init_tools(context=_context())

    assert [tool.name for tool in agent.tools] == ["weather", "eplus_robot_knowledge"]
    original_knowledge.assert_not_awaited()
    assert build_robot_tool.await_args.kwargs["expected_scope"].space_ids == (11, 12)


def test_explicit_bisheng_knowledge_api_tool_is_rejected_but_normal_tool_is_retained():
    safe = SimpleNamespace(name="erp", tool_instance=SimpleNamespace(endpoint="https://erp.example/api/search"))
    bypass = SimpleNamespace(
        name="knowledge_api",
        tool_instance=SimpleNamespace(endpoint="/api/v1/knowledge/42/search"),
    )

    assert assert_eplus_tool_scope(safe) is safe
    with pytest.raises(RobotToolScopeViolation, match="knowledge endpoint"):
        assert_eplus_tool_scope(bypass)


@pytest.mark.parametrize(
    ("flow_data", "expected"),
    [
        ({"nodes": [{"data": {"type": "knowledge_retriever"}}]}, True),
        ({"nodes": [{"data": {"type": "rag"}}]}, True),
        ({"nodes": [{"data": {"type": "http_request"}}]}, False),
    ],
)
def test_flow_knowledge_nodes_are_detected_for_fail_closed_guard(flow_data, expected):
    assert flow_uses_bisheng_knowledge(flow_data) is expected


async def test_eplus_context_without_robot_scope_fails_closed():
    agent = _agent()
    context = AssistantExecutionContext(
        entry_point=AssistantEntryPoint.EPLUS,
        user_id=88,
        external_user_id="raw-user-id",
        content="hello",
    )
    with (
        patch(
            "bisheng.api.services.assistant_agent.AssistantLinkDao.get_assistant_link",
            AsyncMock(return_value=[]),
        ),
        pytest.raises(RobotToolScopeViolation, match="robot scope"),
    ):
        await agent.init_tools(context=context)
