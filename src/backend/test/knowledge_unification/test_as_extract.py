"""T043: stable assistant slots and caller-owned business transactions."""

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.assistant.domain.repositories.assistant_repository import AssistantRepository
from bisheng.assistant.domain.services.reference_extractor import extract_assistant_references
from bisheng.common.errcode.assistant import AssistantNotExistsError
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.database.models.assistant import Assistant, AssistantLink, AssistantStatus
from bisheng.resource_reference.application.contracts import TargetType, reference_set_digest


def identities(references):
    return {(ref.slot_key, ref.target.target_type, ref.target.target_id) for ref in references}


def test_extract_actual_model_id_and_stable_knowledge_multiselect():
    references = extract_assistant_references(model_name="0031", knowledge_ids=[20, 0, 10, 20])
    assert identities(references) == {
        ("model_name", TargetType.MODEL, "31"),
        ("knowledge_list", TargetType.KNOWLEDGE_SPACE, "10"),
        ("knowledge_list", TargetType.KNOWLEDGE_SPACE, "20"),
    }
    reordered = extract_assistant_references(model_name="31", knowledge_ids=[10, 20])
    assert reference_set_digest(references) == reference_set_digest(reordered)


def test_replacement_changes_only_selected_slots():
    old = identities(extract_assistant_references(model_name="31", knowledge_ids=[10, 20]))
    new = identities(extract_assistant_references(model_name="32", knowledge_ids=[20, 30]))
    assert old & new == {("knowledge_list", TargetType.KNOWLEDGE_SPACE, "20")}
    assert old - new == {
        ("model_name", TargetType.MODEL, "31"),
        ("knowledge_list", TargetType.KNOWLEDGE_SPACE, "10"),
    }


@pytest.mark.parametrize("model_name", [None, ""])
def test_incomplete_saved_configuration_has_empty_model_slot(model_name):
    assert extract_assistant_references(model_name=model_name, knowledge_ids=[0]) == ()


@pytest.mark.parametrize("model_name", ["display-name", "-1", "0", " 31", True])
def test_extractor_never_resolves_display_names_or_guesses_ids(model_name):
    with pytest.raises((TypeError, ValueError)):
        extract_assistant_references(model_name=model_name, knowledge_ids=[])


@pytest.mark.parametrize("knowledge_ids", [[-1], [True], ["display-name"]])
def test_extractor_rejects_invalid_knowledge_identifiers(knowledge_ids):
    with pytest.raises((TypeError, ValueError)):
        extract_assistant_references(model_name="31", knowledge_ids=knowledge_ids)


@pytest.fixture
def assistant_tenant(tenant_context):
    tenant_context(101)


@pytest.fixture
async def assistant_session(assistant_tenant):
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda conn: SQLModel.metadata.create_all(conn, tables=[Assistant.__table__, AssistantLink.__table__])
        )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


async def seed_assistant(session):
    repository = AssistantRepository()
    assistant = Assistant(id="assistant-a", tenant_id=101, name="original", model_name="31", user_id=7)
    await repository.ainsert(session, assistant)
    await repository.areplace_links(session, assistant.id, tool_ids=[1], flow_ids=["flow-a"], knowledge_ids=[10, 20])
    await session.commit()
    return repository, assistant


async def link_values(session, assistant_id="assistant-a"):
    links = (await session.exec(select(AssistantLink).where(AssistantLink.assistant_id == assistant_id))).all()
    return {(link.tool_id, link.flow_id, link.knowledge_id) for link in links}


async def test_create_flush_does_not_commit_business_or_links(assistant_session):
    repository = AssistantRepository()
    assistant = Assistant(id="assistant-a", name="original", model_name="31", user_id=7)
    await repository.ainsert(assistant_session, assistant)
    assert assistant.tenant_id == 101
    await repository.areplace_links(assistant_session, assistant.id, knowledge_ids=[10])
    assert await link_values(assistant_session) == {(0, "", 10)}
    await assistant_session.rollback()
    assert await repository.aget(assistant_session, assistant.id) is None
    assert await link_values(assistant_session) == set()


async def test_configuration_and_all_link_changes_rollback_together(assistant_session):
    repository, _ = await seed_assistant(assistant_session)
    assistant = await repository.aget(assistant_session, "assistant-a", for_update=True)
    assistant.name, assistant.model_name = "changed", "32"
    await repository.asave(assistant_session, assistant)
    await repository.areplace_links(
        assistant_session, assistant.id, tool_ids=[2], flow_ids=["flow-b"], knowledge_ids=[20, 30]
    )
    # A binding-store failure is handled by the owning use case, not an inner commit.
    await assistant_session.rollback()
    current = await repository.aget(assistant_session, "assistant-a")
    assert (current.name, current.model_name) == ("original", "31")
    assert await link_values(assistant_session) == {(1, "", 0), (0, "flow-a", 0), (0, "", 10), (0, "", 20)}


async def test_none_retains_links_empty_clears_only_requested_kind(assistant_session):
    repository, _ = await seed_assistant(assistant_session)
    # Legacy knowledge links can carry a flow_id; these are not standalone flows.
    assistant_session.add(
        AssistantLink(assistant_id="assistant-a", knowledge_id=30, flow_id="legacy-flow", tenant_id=101)
    )
    await assistant_session.commit()
    await repository.areplace_links(assistant_session, "assistant-a", flow_ids=[], knowledge_ids=None)
    assert await link_values(assistant_session) == {(1, "", 0), (0, "", 10), (0, "", 20), (0, "legacy-flow", 30)}
    await repository.areplace_links(assistant_session, "assistant-a", knowledge_ids=[20, 20, 0])
    assert await link_values(assistant_session) == {(1, "", 0), (0, "", 20)}


async def test_offline_and_soft_delete_are_caller_owned_changes(assistant_session):
    repository, _ = await seed_assistant(assistant_session)
    assistant = await repository.aget(assistant_session, "assistant-a", for_update=True)
    assistant.status = AssistantStatus.OFFLINE.value
    await repository.asave(assistant_session, assistant)
    assert len(await repository.alist_links(assistant_session, assistant.id)) == 4
    await repository.asoft_delete(assistant_session, assistant)
    assert assistant.is_delete == 1
    await assistant_session.rollback()
    assert (await repository.aget(assistant_session, "assistant-a")).is_delete == 0
    assert len(await repository.alist_links(assistant_session, "assistant-a")) == 4


async def test_locking_read_refreshes_identity_map(assistant_session):
    repository, assistant = await seed_assistant(assistant_session)
    await assistant_session.execute(
        Assistant.__table__.update().where(Assistant.id == assistant.id).values(model_name="32")
    )
    assert assistant.model_name == "31"
    current = await repository.aget(assistant_session, assistant.id, for_update=True)
    assert current.model_name == "32"


async def test_cross_tenant_create_and_link_writes_are_refused(assistant_session):
    repository, assistant = await seed_assistant(assistant_session)
    with pytest.raises(AssistantNotExistsError):
        await repository.ainsert(assistant_session, Assistant(id="forged", tenant_id=202, user_id=7))
    token = set_current_tenant_id(202)
    try:
        with pytest.raises(AssistantNotExistsError):
            await repository.areplace_links(assistant_session, assistant.id, knowledge_ids=[])
        with pytest.raises(AssistantNotExistsError):
            await repository.asave(assistant_session, assistant)
    finally:
        current_tenant_id.reset(token)
    assert await link_values(assistant_session) == {(1, "", 0), (0, "flow-a", 0), (0, "", 10), (0, "", 20)}


async def test_link_write_requires_existing_root(assistant_session):
    with pytest.raises(AssistantNotExistsError):
        await AssistantRepository().areplace_links(assistant_session, "missing", knowledge_ids=[10])
    assert await link_values(assistant_session, "missing") == set()
