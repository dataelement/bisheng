"""T315: new knowledge selections need their own visible-resource decision.

覆盖 AC: AC-37, AC-79, AC-83, AC-87, AC-88, AC-91
The SQL target Owner proves existence; it does not authorize the configuring user.
"""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, update

from bisheng.api.services import assistant as assistant_module
from bisheng.api.services.assistant import AssistantService
from bisheng.api.v1.schemas import AssistantUpdateReq
from bisheng.assistant.domain.repositories.assistant_repository import AssistantRepository
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.common.errcode.open_api import PersonalTokenDataScopeError
from bisheng.knowledge.domain.models.knowledge import Knowledge
from test.knowledge_unification import test_as_bindings as bindings

assistant_tenant = bindings.assistant_tenant
assistant_business = bindings.assistant_business


@pytest.fixture
async def knowledge_selection(assistant_business, monkeypatch):
    context = assistant_business
    async with context.engine.begin() as connection:
        await connection.run_sync(lambda conn: Knowledge.__table__.create(conn, checkfirst=True))
    async with context.sessions() as session:
        for knowledge_id in (10, 20):
            if await session.get(Knowledge, knowledge_id) is None:
                session.add(Knowledge(id=knowledge_id, tenant_id=101, user_id=9, name=f"space-{knowledge_id}", type=3))
        await session.commit()
    await bindings.seed(context)
    context.knowledge_decision = AsyncMock()

    async def authorize(user, *, resource_type, resource_id, action):
        if resource_type == "assistant":
            return
        await context.knowledge_decision(user, resource_type=resource_type, resource_id=resource_id, action=action)

    monkeypatch.setattr(assistant_module, "require_business_action", authorize)
    return context


async def set_kind(context, kind):
    async with context.sessions() as session:
        await session.execute(update(Knowledge).where(Knowledge.tenant_id == 101, Knowledge.id == 20).values(type=kind))
        await session.commit()


async def add_selection(context):
    await AssistantService.update_assistant(
        context.request,
        context.user,
        AssistantUpdateReq(id="assistant-a", name="changed", model_name="2", knowledge_list=[10, 20], temperature=1),
    )


async def assert_unchanged(context):
    assistant, links, references, source = await bindings.inspect_business(context)
    assert (assistant.name, assistant.model_name) == ("original", "1")
    assert [row.knowledge_id for row in links] == [10]
    assert {row.target_id for row in references} == {"1", "10"} and source.source_revision == 1


@pytest.mark.parametrize("kind", [0, 1, 3])
async def test_same_tenant_hidden_new_target_rolls_back_the_complete_save(knowledge_selection, kind):
    context = knowledge_selection
    await set_kind(context, kind)
    context.knowledge_decision.side_effect = UnAuthorizedError()
    with pytest.raises(UnAuthorizedError):
        await add_selection(context)
    await assert_unchanged(context)


@pytest.mark.parametrize(
    "kind,resource_type", [(0, "knowledge_library"), (1, "knowledge_library"), (3, "knowledge_space")]
)
async def test_new_selection_uses_its_actual_business_permission_kind(knowledge_selection, kind, resource_type):
    context = knowledge_selection
    await set_kind(context, kind)

    async def allow_exact_kind(user, **decision):
        if decision != {"resource_type": resource_type, "resource_id": 20, "action": "visible"}:
            raise UnAuthorizedError()
        assert user is context.user

    context.knowledge_decision.side_effect = allow_exact_kind
    await add_selection(context)
    context.knowledge_decision.assert_awaited_once()
    _, links, references, _ = await bindings.inspect_business(context)
    assert {row.knowledge_id for row in links} == {10, 20}
    assert {row.target_id for row in references} == {"2", "10", "20"}


async def test_new_target_credential_narrowing_error_is_not_laundered(knowledge_selection):
    context = knowledge_selection
    failure = PersonalTokenDataScopeError()
    context.knowledge_decision.side_effect = failure
    with pytest.raises(PersonalTokenDataScopeError) as caught:
        await add_selection(context)
    assert caught.value is failure
    await assert_unchanged(context)


async def test_old_hidden_slot_can_stay_or_be_removed_without_a_new_gate(knowledge_selection):
    context = knowledge_selection
    context.knowledge_decision.side_effect = UnAuthorizedError()
    for knowledge_ids in ([10], []):
        await AssistantService.update_assistant(
            context.request,
            context.user,
            AssistantUpdateReq(id="assistant-a", model_name="2", knowledge_list=knowledge_ids, temperature=1),
        )
    context.knowledge_decision.assert_not_awaited()
    _, links, references, _ = await bindings.inspect_business(context)
    assert not links and {row.target_id for row in references} == {"2"}


async def test_old_deleted_slot_does_not_block_an_unrelated_partial_repair(knowledge_selection):
    context = knowledge_selection
    await bindings.stage(context, "knowledge_space", 10, "deleted")
    async with context.sessions() as session:
        await session.execute(delete(Knowledge).where(Knowledge.tenant_id == 101, Knowledge.id == 10))
        await session.commit()
    context.knowledge_decision.side_effect = UnAuthorizedError()
    await AssistantService.update_assistant(
        context.request, context.user, AssistantUpdateReq(id="assistant-a", model_name="2", temperature=1)
    )
    context.knowledge_decision.assert_not_awaited()
    assistant, links, references, _ = await bindings.inspect_business(context)
    assert assistant.model_name == "2" and [row.knowledge_id for row in links] == [10]
    assert {row.target_id for row in references} == {"2", "10"}
    async with context.sessions() as session:
        with pytest.raises(ResourceReferenceInvalidError):
            await context.runtime.arequire_source_valid(session, bindings.source_key())


@pytest.mark.parametrize("kind", [2, 99])
async def test_unsupported_actual_knowledge_kind_cannot_be_selected(knowledge_selection, kind):
    context = knowledge_selection
    await set_kind(context, kind)
    with pytest.raises(ResourceReferenceInvalidError):
        await add_selection(context)
    await assert_unchanged(context)


async def test_missing_actual_knowledge_row_is_not_authorized_by_id_alone(knowledge_selection):
    context = knowledge_selection
    async with context.sessions() as session:
        await session.execute(delete(Knowledge).where(Knowledge.tenant_id == 101, Knowledge.id == 20))
        await session.commit()
    with pytest.raises(ResourceReferenceInvalidError):
        await add_selection(context)
    await assert_unchanged(context)


async def test_actual_kind_locking_read_uses_the_current_database_value(knowledge_selection):
    context = knowledge_selection
    async with context.sessions() as session:
        row = await session.get(Knowledge, 20)
        assert row.type == 3
        await session.execute(Knowledge.__table__.update().where(Knowledge.id == 20).values(type=1))
        assert row.type == 3
        assert await AssistantRepository().alock_knowledge_kinds(session, (20,)) == {20: 1}
