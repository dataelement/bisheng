"""T366: every assistant execution consumes one authorized persisted snapshot."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.assistant.application.execution_admission import AssistantExecutionAdmission
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.database.models.assistant import Assistant, AssistantLinkDao
from bisheng.permission.application.identity import (
    get_current_permission_actor,
    reset_current_permission_actor,
    set_current_permission_actor,
)
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.resource_reference.application.contracts import SourceKey
from bisheng.resource_reference.application.source_contracts import (
    AuthorizedSourceSnapshot,
    SourceReferenceReadResult,
    canonical_payload_json,
    payload_digest,
)

REAL_INIT_TOOLS = AssistantAgent.init_tools


def source_result(**changes):
    row = Assistant(
        id="assistant-a", tenant_id=101, user_id=8, model_name="7", name="persisted", temperature=0.4
    ).model_dump(mode="json")
    row.update(changes)
    payload = canonical_payload_json({"assistant": row, "links": []})
    snapshot = AuthorizedSourceSnapshot(
        SourceKey(101, "assistant", "assistant-a", "current"), (), "assistant-v1", payload_digest(payload), payload
    )
    return SourceReferenceReadResult(snapshot, (), 3, 4)


@pytest.fixture
def runtime_agent(monkeypatch):
    user = UserPayload(user_id=9, user_name="caller", tenant_id=101, user_role=[])
    prepare = AsyncMock(return_value=source_result())
    monkeypatch.setattr(AssistantExecutionAdmission, "prepare", prepare)
    llm = AsyncMock()
    tools = AsyncMock()
    init = AsyncMock()
    monkeypatch.setattr(AssistantAgent, "init_llm", llm)
    monkeypatch.setattr(AssistantAgent, "init_tools", tools)
    monkeypatch.setattr(AssistantAgent, "init_agent", init)
    agent = AssistantAgent(
        Assistant(id="assistant-a", tenant_id=1, model_name="evil", name="untrusted"), "chat", 9, login_user=user
    )
    agent.fake_callback = AsyncMock()
    agent.trim_messages = AsyncMock(side_effect=lambda messages: messages)
    agent.record_chat_history = AsyncMock()
    agent.agent = SimpleNamespace(ainvoke=AsyncMock(return_value={"messages": [AIMessage(content="ok")]}))
    return agent, user, prepare, llm, tools, init


async def test_init_uses_persisted_full_snapshot_and_original_identity(runtime_agent):
    agent, user, prepare, llm, tools, init = runtime_agent
    await agent.init_assistant()
    prepare.assert_awaited_once_with(user, "assistant-a", session=None)
    assert agent.assistant.name == "persisted" and agent.assistant.model_name == "7"
    assert agent.assistant.tenant_id == 101 and agent.assistant.temperature == 0.4
    assert agent.login_user is user
    llm.assert_awaited_once()
    tools.assert_awaited_once()
    init.assert_awaited_once()


async def test_id_only_constructor_never_recovers_an_ordinary_person(monkeypatch):
    agent = AssistantAgent(Assistant(id="assistant-a", tenant_id=101), "", 9)
    prepare = AsyncMock()
    llm = AsyncMock()
    monkeypatch.setattr(AssistantExecutionAdmission, "prepare", prepare)
    monkeypatch.setattr(agent, "init_llm", llm)
    monkeypatch.setattr(agent, "init_tools", AsyncMock())
    monkeypatch.setattr(agent, "init_agent", AsyncMock())
    with pytest.raises(ResourceReferenceInvalidError):
        await agent.init_assistant()
    prepare.assert_not_awaited()
    llm.assert_not_awaited()


async def test_run_revalidates_each_cached_execution_and_keeps_principal(runtime_agent):
    agent, user, prepare, _llm, _tools, _init = runtime_agent
    actor = PermissionActor(subject_type="service_account", subject_id=77, tenant_id=101)
    token = set_current_permission_actor(actor)

    async def current(identity, assistant_id, *, session):
        assert identity is user and get_current_permission_actor() is actor
        return source_result()

    prepare.side_effect = current
    try:
        await agent.init_assistant()
        assert (await agent.run("first"))[-1].content == "ok"
        assert (await agent.run("second"))[-1].content == "ok"
        assert prepare.await_count == 3
        assert agent.agent.ainvoke.await_count == 2
    finally:
        reset_current_permission_actor(token)


async def test_configuration_change_rejects_cache_before_provider_or_callback(runtime_agent):
    agent, _user, prepare, _llm, _tools, _init = runtime_agent
    await agent.init_assistant()
    prepare.return_value = source_result(system_prompt="new persisted prompt")
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await agent.run("never invoke")
    agent.agent.ainvoke.assert_not_awaited()
    agent.fake_callback.assert_not_awaited()


async def test_stream_revalidates_before_producing_any_chunk(runtime_agent):
    agent, _user, prepare, _llm, _tools, _init = runtime_agent
    await agent.init_assistant()
    prepare.side_effect = ResourceReferenceInvalidError()
    with pytest.raises(ResourceReferenceInvalidError):
        async for _chunk in agent.astream("never invoke"):
            pytest.fail("invalid source produced a chunk")
    assert prepare.await_count == 2
    agent.fake_callback.assert_not_awaited()


async def test_borrowed_publish_session_and_runtime_override_remain_separate(monkeypatch):
    user = UserPayload(user_id=9, user_name="caller", tenant_id=101, user_role=[])
    session = object()
    persisted = source_result()
    prepare = AsyncMock(return_value=persisted)
    monkeypatch.setattr(AssistantExecutionAdmission, "prepare", prepare)
    agent = AssistantAgent(
        Assistant(id="assistant-a"), "", 9, login_user=user, reference_session=session, runtime_temperature=0.9
    )
    for name in ("init_llm", "init_tools", "init_agent"):
        monkeypatch.setattr(agent, name, AsyncMock())
    await agent.init_assistant()
    assert agent.assistant.temperature == 0.9
    assert json.loads(persisted.snapshot.payload_json)["assistant"]["temperature"] == 0.4
    prepare.assert_awaited_once_with(user, "assistant-a", session=session)


async def test_tool_links_use_snapshot_instead_of_independent_dao_read(runtime_agent, monkeypatch):
    agent, _user, _prepare, _llm, _tools, _init = runtime_agent
    await agent.init_assistant()
    dao = AsyncMock(side_effect=AssertionError("independent links read"))
    monkeypatch.setattr(AssistantLinkDao, "get_assistant_link", dao)
    await REAL_INIT_TOOLS(agent)
    dao.assert_not_awaited()
