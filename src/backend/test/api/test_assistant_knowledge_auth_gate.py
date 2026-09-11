"""用户知识库权限校验 must gate ordinary knowledge bases, not only spaces.

The toggle only ever reached the knowledge-space branch of the assistant's tool
setup. An ordinary knowledge base went straight to a retriever built off the
bound id, with no permission read anywhere on the path, so a user who was
granted the assistant and nothing else could still search knowledge bases they
had no access to — while the workflow retrieval node, given the same toggle and
the same knowledge base, filtered by the runtime user's `use` action.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum

_ALLOWED_KB = 11
_FORBIDDEN_KB = 12
_SPACE = 13


def _agent(*, knowledge_auth: bool) -> AssistantAgent:
    """An agent with only the attributes init_tools reads — no real __init__."""
    agent = object.__new__(AssistantAgent)
    agent.assistant = SimpleNamespace(
        id="assistant-1",
        name="assistant",
        tenant_id=1,
        user_id=1,  # the author
        knowledge_auth=knowledge_auth,
    )
    agent.invoke_user_id = 150041  # the runtime user, granted the assistant only
    agent.llm = object()
    agent.knowledge_retriever = {"max_content": 15000}
    agent.citation_registry_collector = SimpleNamespace(clear=lambda: None, list_items=list)
    return agent


def _links():
    return [
        SimpleNamespace(tool_id=None, knowledge_id=_ALLOWED_KB),
        SimpleNamespace(tool_id=None, knowledge_id=_FORBIDDEN_KB),
    ]


def _knowledge_rows():
    return [
        SimpleNamespace(id=_ALLOWED_KB, type=KnowledgeTypeEnum.NORMAL.value, name="allowed"),
        SimpleNamespace(id=_FORBIDDEN_KB, type=KnowledgeTypeEnum.NORMAL.value, name="forbidden"),
    ]


async def _run_init_tools(agent, *, usable_ids):
    init_knowledge_tool = AsyncMock(
        side_effect=lambda user_id, knowledge_id, **kw: SimpleNamespace(name=f"kb_{knowledge_id}")
    )
    with (
        patch(
            "bisheng.api.services.assistant_agent.AssistantLinkDao.get_assistant_link",
            AsyncMock(return_value=_links()),
        ),
        patch(
            "bisheng.knowledge.domain.models.knowledge.KnowledgeDao.get_list_by_ids",
            return_value=_knowledge_rows(),
        ),
        patch(
            "bisheng.knowledge.domain.services.space_flow_retrieval.abuild_scoped_login_user",
            AsyncMock(return_value=SimpleNamespace(user_id=150041)),
        ),
        patch.object(
            KnowledgeRag,
            "afilter_usable_knowledge_ids",
            AsyncMock(return_value=set(usable_ids)),
        ) as usable_filter,
        patch(
            "bisheng.api.services.assistant_agent.ToolExecutor.init_knowledge_tool",
            init_knowledge_tool,
        ),
        patch.object(AssistantAgent, "wrap_citation_tool", lambda self, tool: tool),
        patch.object(AssistantAgent, "_resolve_kb_name_by_id", staticmethod(lambda ids: {})),
    ):
        await agent.init_tools()
    built_for = [
        call.kwargs.get("knowledge_id", call.args[1] if len(call.args) > 1 else None)
        for call in init_knowledge_tool.await_args_list
    ]
    return built_for, usable_filter


async def test_toggle_on_drops_a_knowledge_base_the_runtime_user_cannot_use():
    agent = _agent(knowledge_auth=True)
    built_for, usable_filter = await _run_init_tools(agent, usable_ids={_ALLOWED_KB})

    assert built_for == [_ALLOWED_KB]
    assert _FORBIDDEN_KB not in built_for
    usable_filter.assert_awaited_once()


async def test_toggle_on_asks_about_ordinary_knowledge_bases_only():
    agent = _agent(knowledge_auth=True)
    _, usable_filter = await _run_init_tools(agent, usable_ids={_ALLOWED_KB, _FORBIDDEN_KB})

    asked_for = usable_filter.await_args.args[1]
    assert sorted(asked_for) == [_ALLOWED_KB, _FORBIDDEN_KB]
    assert _SPACE not in asked_for


async def test_toggle_off_leaves_the_previous_behaviour_alone():
    agent = _agent(knowledge_auth=False)
    built_for, usable_filter = await _run_init_tools(agent, usable_ids=set())

    assert built_for == [_ALLOWED_KB, _FORBIDDEN_KB]
    usable_filter.assert_not_awaited()


@pytest.mark.parametrize(
    ("action_map", "expected"),
    [
        ({_ALLOWED_KB: {"use"}, _FORBIDDEN_KB: set()}, {_ALLOWED_KB}),
        ({_ALLOWED_KB: {"edit"}, _FORBIDDEN_KB: {"use"}}, {_FORBIDDEN_KB}),
        ({}, set()),
    ],
)
async def test_the_filter_keeps_only_the_use_action(action_map, expected):
    with patch(
        "bisheng.knowledge.domain.services.knowledge_permission_service."
        "KnowledgePermissionService.get_knowledge_action_map_async",
        AsyncMock(return_value=action_map),
    ):
        usable = await KnowledgeRag.afilter_usable_knowledge_ids(
            SimpleNamespace(user_id=150041),
            [_ALLOWED_KB, _FORBIDDEN_KB],
        )
    assert usable == expected


async def test_the_filter_admits_nothing_without_an_identity():
    """A vanished user must not fall through to "everything is usable"."""
    assert await KnowledgeRag.afilter_usable_knowledge_ids(None, [_ALLOWED_KB]) == set()
