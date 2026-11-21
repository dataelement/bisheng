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
from bisheng.common.dependencies.user_deps import UserPayload
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
    agent.login_user = UserPayload(user_id=150041, user_name="actor", tenant_id=1, user_role=[])
    from sqlmodel.ext.asyncio.session import AsyncSession

    agent.reference_session = AsyncSession()
    agent._source_links = tuple(_links())
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
        SimpleNamespace(id=_ALLOWED_KB, type=KnowledgeTypeEnum.NORMAL.value, name="allowed", tenant_id=1),
        SimpleNamespace(id=_FORBIDDEN_KB, type=KnowledgeTypeEnum.NORMAL.value, name="forbidden", tenant_id=1),
    ]


async def _run_init_tools(agent, *, usable_ids):
    init_knowledge_tool = AsyncMock(
        side_effect=lambda user_id, knowledge_id, **kw: SimpleNamespace(name=f"kb_{knowledge_id}")
    )
    with (
        patch(
            "bisheng.database.models.assistant.AssistantLinkDao.get_assistant_link",
            AsyncMock(side_effect=AssertionError("must consume the admitted snapshot links")),
        ) as independent_links,
        patch(
            "bisheng.knowledge.domain.models.knowledge.KnowledgeDao.get_list_by_ids",
            return_value=_knowledge_rows(),
        ),
        patch("bisheng.core.context.tenant.get_current_tenant_id", return_value=1),
        patch(
            "bisheng.knowledge.domain.services.space_flow_retrieval.abuild_scoped_login_user",
            AsyncMock(side_effect=lambda user_id, tenant_id: SimpleNamespace(user_id=user_id)),
        ) as identity_builder,
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
        try:
            await agent.init_tools()
        finally:
            await agent.reference_session.close()
        independent_links.assert_not_awaited()
        identity_builder.assert_awaited_once_with(
            agent.invoke_user_id if agent.assistant.knowledge_auth else agent.assistant.user_id,
            agent.assistant.tenant_id,
        )
    for call in init_knowledge_tool.await_args_list:
        assert call.kwargs["reference_session"] is agent.reference_session
        assert call.kwargs["login_user"] is agent.login_user
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
    assert usable_filter.await_args.args[0].user_id == agent.invoke_user_id


async def test_toggle_on_asks_about_ordinary_knowledge_bases_only():
    agent = _agent(knowledge_auth=True)
    _, usable_filter = await _run_init_tools(agent, usable_ids={_ALLOWED_KB, _FORBIDDEN_KB})

    asked_for = usable_filter.await_args.args[1]
    assert sorted(asked_for) == [_ALLOWED_KB, _FORBIDDEN_KB]
    assert _SPACE not in asked_for


async def test_toggle_off_still_requires_author_current_use_permission():
    agent = _agent(knowledge_auth=False)
    built_for, usable_filter = await _run_init_tools(agent, usable_ids=set())

    assert built_for == []
    usable_filter.assert_awaited_once()
    assert usable_filter.await_args.args[0].user_id == agent.assistant.user_id


@pytest.mark.parametrize(
    ("action_map", "expected"),
    [
        ({_ALLOWED_KB: {"visible"}, _FORBIDDEN_KB: set()}, {_ALLOWED_KB}),
        ({_ALLOWED_KB: {"edit"}, _FORBIDDEN_KB: {"visible"}}, {_FORBIDDEN_KB}),
        ({_ALLOWED_KB: {"use"}}, set()),
        ({}, set()),
    ],
)
async def test_the_filter_keeps_only_canonical_legacy_use_authority(action_map, expected):
    # F118 AC-35/36/37/66/68/79/82/83 maps legacy KB retrieval/use to
    # canonical visible. Edit-only and raw unnormalized use cannot grant it.
    with patch(
        "bisheng.knowledge.domain.services.knowledge_permission_service."
        "KnowledgePermissionService.get_knowledge_action_map_async",
        AsyncMock(return_value=action_map),
    ) as permission_map:
        user = SimpleNamespace(user_id=150041)
        usable = await KnowledgeRag.afilter_usable_knowledge_ids(
            user,
            [_ALLOWED_KB, _FORBIDDEN_KB],
        )
    permission_map.assert_awaited_once_with(user, [_ALLOWED_KB, _FORBIDDEN_KB], ["visible"])
    assert usable == expected


async def test_the_filter_admits_nothing_without_an_identity():
    """A vanished user must not fall through to "everything is usable"."""
    assert await KnowledgeRag.afilter_usable_knowledge_ids(None, [_ALLOWED_KB]) == set()
