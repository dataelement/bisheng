"""T045: real assistant CRUD and references form one SQL transaction."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, delete, insert, select, update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.api.services import assistant as assistant_module
from bisheng.api.services.assistant import AssistantService
from bisheng.api.v1.schemas import AssistantUpdateReq
from bisheng.assistant.domain.repositories.assistant_repository import AssistantRepository
from bisheng.assistant.domain.services.reference_extractor import (
    ASSISTANT_REFERENCE_EXTRACTOR_VERSION,
    extract_assistant_references,
)
from bisheng.common.errcode.knowledge import (
    KnowledgeProcessingConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.database.models.assistant import Assistant, AssistantLink, AssistantStatus
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.resource_reference.application.contracts import (
    DeletionEvidence,
    SourceKey,
    TargetLockReceipt,
    TransactionIdentity,
)
from bisheng.resource_reference.application.target_state import resolve_target_state
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository

metadata = MetaData()
targets = Table(
    "test_assistant_targets",
    metadata,
    Column("kind", String, primary_key=True),
    Column("id", Integer, primary_key=True),
    Column("tenant_id", Integer, nullable=False),
    Column("stage", String, nullable=False),
)


class SqlTargetOwner:
    """The verifier calls this Owner; test callers never mint capabilities."""

    def lock_and_verify(self, session, target_keys, source_key, operation):
        raise AssertionError("assistant async writes must not fall back to synchronous verification")

    async def alock_and_verify(self, session, target_keys, source_key, operation):
        receipts = []
        for key in target_keys:
            row = (
                await session.execute(
                    select(targets)
                    .where(targets.c.kind == key.target_type.value, targets.c.id == int(key.target_id))
                    .with_for_update()
                )
            ).one_or_none()
            if row is None or row.tenant_id != source_key.tenant_id:
                raise ResourceReferenceInvalidError(reason="test_target_not_found")
            deletion = (
                DeletionEvidence(f"target-{key.target_id}", key, row.tenant_id, row.stage)
                if row.stage != "valid"
                else None
            )
            observed = resolve_target_state(
                key,
                exists=row.stage != "deleted",
                target_tenant_id=row.tenant_id,
                target_space_id=key.target_id if key.target_type == "knowledge_space" else None,
                model_server_id="7" if key.target_type == "model" else None,
                target_revision="r1",
                deletion_evidence=deletion,
            )
            receipts.append(TargetLockReceipt(source_key, observed, TransactionIdentity.capture(session), self))
        return tuple(receipts)


def source_key(assistant_id="assistant-a"):
    return SourceKey(101, "assistant", assistant_id, "current")


@pytest.fixture
def assistant_tenant(tenant_context):
    tenant_context(101)


@pytest.fixture
async def assistant_business(tmp_path, assistant_tenant, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'assistant.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda conn: SQLModel.metadata.create_all(
                conn,
                tables=[
                    Assistant.__table__,
                    AssistantLink.__table__,
                    Knowledge.__table__,
                    BusinessReferenceSet.__table__,
                    BusinessResourceReference.__table__,
                    ResourceReferenceTombstone.__table__,
                ],
            )
        )
        await connection.run_sync(metadata.create_all)
        await connection.execute(
            insert(targets),
            [
                {"kind": kind, "id": target_id, "tenant_id": 101, "stage": "valid"}
                for kind, ids in (("model", [1, 2]), ("knowledge_space", [10, 20]))
                for target_id in ids
            ],
        )
    async with AsyncSession(engine) as session, session.begin():
        session.add_all(
            [
                Knowledge(id=target_id, tenant_id=101, user_id=9, name=f"space-{target_id}", type=3)
                for target_id in (10, 20)
            ]
        )

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    owner = SqlTargetOwner()
    verifier = ReferenceTargetVerifier({"model": owner, "knowledge_space": owner})
    repository = ReferenceRepository(verifier=verifier)
    runtime = ReferenceBindingRuntime(repository, verifier)
    monkeypatch.setattr(assistant_module, "get_async_db_session", sessions, raising=False)
    monkeypatch.setattr(
        assistant_module, "get_reference_binding_runtime", AsyncMock(return_value=runtime), raising=False
    )
    monkeypatch.setattr(assistant_module, "require_business_action", AsyncMock())
    monkeypatch.setattr(assistant_module, "check_business_action", AsyncMock(return_value=True))
    monkeypatch.setattr(assistant_module, "resolve_permission_actor", AsyncMock(return_value=object()))
    monkeypatch.setattr(assistant_module.telemetry_service, "log_event", AsyncMock())
    monkeypatch.setattr(assistant_module.telemetry_service, "log_event_sync", MagicMock())
    monkeypatch.setattr(AssistantService, "judge_name_repeat", MagicMock(return_value=False))
    monkeypatch.setattr(AssistantService, "create_assistant_hook_async", AsyncMock())
    monkeypatch.setattr(AssistantService, "update_assistant_hook", MagicMock(return_value=True))
    monkeypatch.setattr(AssistantService, "delete_assistant_hook", MagicMock(return_value=True))
    monkeypatch.setattr(AssistantService, "get_link_info", MagicMock(return_value=([], [], [])))
    monkeypatch.setattr(
        assistant_module.LLMService,
        "get_assistant_llm",
        AsyncMock(return_value=SimpleNamespace(llm_list=[SimpleNamespace(default=True, model_id=1)])),
    )
    permission_adapter = SimpleNamespace(
        load_permission_record=AsyncMock(return_value=object()), project_delete=AsyncMock()
    )
    monkeypatch.setattr(assistant_module, "get_f048_resource_adapter", AsyncMock(return_value=permission_adapter))
    monkeypatch.setattr(
        assistant_module.AssistantDao,
        "get_one_assistant",
        MagicMock(side_effect=AssertionError("legacy independent-session read")),
    )
    for name in ("create_assistant", "update_assistant", "delete_assistant"):
        monkeypatch.setattr(
            assistant_module.AssistantDao, name, MagicMock(side_effect=AssertionError("legacy committing DAO write"))
        )
    for name in ("update_assistant_knowledge", "update_assistant_tool", "update_assistant_flow"):
        monkeypatch.setattr(
            assistant_module.AssistantLinkDao,
            name,
            MagicMock(side_effect=AssertionError("legacy committing link DAO write")),
        )

    async def old_read(assistant_id):
        async with sessions() as session:
            return await AssistantRepository().aget(session, assistant_id)

    monkeypatch.setattr(assistant_module.AssistantDao, "aget_one_assistant", old_read)
    context = SimpleNamespace(
        engine=engine,
        sessions=sessions,
        runtime=runtime,
        repository=repository,
        user=SimpleNamespace(user_id=7, tenant_id=101),
        request=MagicMock(),
        permission_adapter=permission_adapter,
    )
    yield context
    await engine.dispose()


async def seed(context, *, knowledge_ids=(10,)):
    async with context.sessions() as session:
        repository = AssistantRepository()
        assistant = Assistant(id="assistant-a", tenant_id=101, name="original", model_name="1", user_id=7)
        await repository.ainsert(session, assistant)

        async def lock_root(active_session):
            return await repository.aget(active_session, assistant.id, for_update=True)

        prepared = await context.runtime.aprepare_source_bindings(
            session,
            source_key(),
            extract_assistant_references(model_name="1", knowledge_ids=knowledge_ids),
            extractor_version=ASSISTANT_REFERENCE_EXTRACTOR_VERSION,
            lock_source_root=lock_root,
            new_source=True,
        )
        await repository.areplace_links(session, assistant.id, knowledge_ids=knowledge_ids)
        await context.runtime.aapply_source_bindings(session, prepared)
        await session.commit()


async def inspect_business(context, assistant_id="assistant-a"):
    async with context.sessions() as session:
        assistant = await AssistantRepository().aget(session, assistant_id)
        links = await AssistantRepository().alist_links(session, assistant_id) if assistant else ()
        references = (await session.execute(select(BusinessResourceReference))).scalars().all()
        source = await context.repository.aget_source_set(session, source_key(assistant_id))
        return assistant, links, references, source


async def stage(context, kind, target_id, value):
    async with context.sessions() as session:
        await session.execute(
            update(targets).where(targets.c.kind == kind, targets.c.id == target_id).values(stage=value)
        )
        await session.commit()


async def test_create_binds_the_default_model_in_the_same_transaction(assistant_business):
    context = assistant_business
    await AssistantService.create_assistant(
        context.request, context.user, Assistant(id="assistant-a", name="new", user_id=7)
    )
    assistant, _, references, source = await inspect_business(context)
    assert assistant.model_name == "1"
    assert {(ref.slot_key, ref.target_id) for ref in references} == {("model_name", "1")}
    assert source.effective


async def test_binding_failure_rolls_back_new_assistant(assistant_business, monkeypatch):
    context = assistant_business
    monkeypatch.setattr(
        context.runtime, "aapply_source_bindings", AsyncMock(side_effect=RuntimeError("binding failed"))
    )
    with pytest.raises(RuntimeError, match="binding failed"):
        await AssistantService.create_assistant(
            context.request, context.user, Assistant(id="assistant-a", name="new", user_id=7)
        )
    assistant, links, references, source = await inspect_business(context)
    assert assistant is None and links == () and references == [] and source is None


async def test_creation_projection_failure_does_not_commit_business_or_references(assistant_business, monkeypatch):
    context = assistant_business
    monkeypatch.setattr(
        AssistantService, "create_assistant_hook_async", AsyncMock(side_effect=RuntimeError("projection failed"))
    )
    with pytest.raises(RuntimeError, match="projection failed"):
        await AssistantService.create_assistant(
            context.request, context.user, Assistant(id="assistant-a", name="new", user_id=7)
        )
    assistant, links, references, source = await inspect_business(context)
    assert assistant is None and links == () and references == [] and source is None


async def test_update_failure_rolls_back_model_and_knowledge_selection(assistant_business, monkeypatch):
    context = assistant_business
    await seed(context)
    monkeypatch.setattr(
        context.runtime, "aapply_source_bindings", AsyncMock(side_effect=RuntimeError("binding failed"))
    )
    with pytest.raises(RuntimeError, match="binding failed"):
        await AssistantService.update_assistant(
            context.request,
            context.user,
            AssistantUpdateReq(id="assistant-a", name="changed", model_name="2", knowledge_list=[20], temperature=1),
        )
    assistant, links, references, _ = await inspect_business(context)
    assert (assistant.name, assistant.model_name) == ("original", "1")
    assert [link.knowledge_id for link in links] == [10]
    assert {(ref.slot_key, ref.target_id) for ref in references} == {("model_name", "1"), ("knowledge_list", "10")}


async def test_configuration_drift_requires_explicit_reconciliation(assistant_business):
    context = assistant_business
    await seed(context)
    async with context.sessions() as session:
        await session.execute(
            update(Assistant).where(Assistant.tenant_id == 101, Assistant.id == "assistant-a").values(model_name="2")
        )
        await session.commit()
    with pytest.raises(ReferenceCoverageNotReadyError):
        await AssistantService.update_prompt("assistant-a", "changed", context.user)
    assistant, _, references, _ = await inspect_business(context)
    assert assistant.model_name == "2" and assistant.prompt == ""
    assert {ref.target_id for ref in references} == {"1", "10"}


async def test_partial_invalid_repair_saves_but_still_cannot_execute(assistant_business):
    context = assistant_business
    await seed(context)
    await stage(context, "model", 1, "deleted")
    await stage(context, "knowledge_space", 10, "deleted")
    await AssistantService.update_assistant(
        context.request, context.user, AssistantUpdateReq(id="assistant-a", model_name="2", temperature=1)
    )
    assistant, links, references, source = await inspect_business(context)
    assert assistant.model_name == "2" and source.effective
    assert [link.knowledge_id for link in links] == [10]
    assert {ref.target_id for ref in references} == {"2", "10"}
    async with context.sessions() as session:
        with pytest.raises(ResourceReferenceInvalidError):
            await context.runtime.arequire_source_valid(session, source_key())


async def test_new_deleted_selection_is_refused_without_changing_business(assistant_business):
    context = assistant_business
    await seed(context)
    await stage(context, "knowledge_space", 20, "deleted")
    with pytest.raises(ResourceReferenceInvalidError):
        await AssistantService.update_assistant(
            context.request,
            context.user,
            AssistantUpdateReq(id="assistant-a", model_name="1", knowledge_list=[20], temperature=1),
        )
    _, links, references, _ = await inspect_business(context)
    assert [link.knowledge_id for link in links] == [10]
    assert {ref.target_id for ref in references} == {"1", "10"}


async def test_soft_delete_releases_source_only_after_business_save(assistant_business):
    context = assistant_business
    await seed(context)
    await AssistantService.delete_assistant(context.request, context.user, "assistant-a")
    assistant, links, references, source = await inspect_business(context)
    assert assistant.is_delete == 1 and len(links) == 1
    assert not source.effective and references == []


async def test_deleting_target_fences_source_delete_and_projection(assistant_business):
    context = assistant_business
    await seed(context)
    await stage(context, "model", 1, "deleting")
    with pytest.raises(KnowledgeProcessingConflictError):
        await AssistantService.delete_assistant(context.request, context.user, "assistant-a")
    assistant, _, references, source = await inspect_business(context)
    assert assistant.is_delete == 0 and source.effective and len(references) == 2
    context.permission_adapter.project_delete.assert_not_awaited()


@pytest.mark.parametrize("setter", ["prompt", "flow", "tool"])
async def test_deleting_target_also_fences_nonreference_setters(assistant_business, setter):
    context = assistant_business
    await seed(context)
    await stage(context, "model", 1, "deleting")
    with pytest.raises(KnowledgeProcessingConflictError):
        if setter == "prompt":
            await AssistantService.update_prompt("assistant-a", "changed", context.user)
        elif setter == "flow":
            await AssistantService.update_flow_list("assistant-a", ["flow-new"], context.user)
        else:
            await AssistantService.update_tool_list("assistant-a", [5], context.user)
    assistant, links, _, _ = await inspect_business(context)
    assert assistant.prompt == "" and [(link.knowledge_id, link.tool_id, link.flow_id) for link in links] == [
        (10, 0, "")
    ]


async def test_offline_retains_bindings_and_invalid_publish_keeps_original_error(assistant_business, monkeypatch):
    context = assistant_business
    await seed(context)
    await AssistantService.update_status(context.request, context.user, "assistant-a", AssistantStatus.OFFLINE.value)
    _, _, references, source = await inspect_business(context)
    assert source.effective and len(references) == 2
    await stage(context, "model", 1, "deleted")
    initialize = AsyncMock()
    monkeypatch.setattr(
        assistant_module, "AssistantAgent", MagicMock(return_value=SimpleNamespace(init_assistant=initialize))
    )
    with pytest.raises(ResourceReferenceInvalidError):
        await AssistantService.update_status(context.request, context.user, "assistant-a", AssistantStatus.ONLINE.value)
    initialize.assert_not_awaited()
    assistant, _, references, source = await inspect_business(context)
    assert assistant.status == AssistantStatus.OFFLINE.value and source.effective and len(references) == 2


async def mark_online(context):
    async with context.sessions() as session:
        await session.execute(
            update(Assistant)
            .where(Assistant.tenant_id == 101, Assistant.id == "assistant-a")
            .values(status=AssistantStatus.ONLINE.value)
        )
        await session.commit()


@pytest.mark.parametrize(
    "case,error",
    [
        ("deleted_model", ResourceReferenceInvalidError),
        ("missing_index", ReferenceCoverageNotReadyError),
        ("configuration_drift", ReferenceCoverageNotReadyError),
        ("deleting_model", KnowledgeProcessingConflictError),
    ],
)
async def test_repeated_online_still_checks_current_source_and_targets(assistant_business, monkeypatch, case, error):
    context = assistant_business
    await seed(context)
    await mark_online(context)
    if case in {"deleted_model", "deleting_model"}:
        await stage(context, "model", 1, "deleted" if case == "deleted_model" else "deleting")
    else:
        async with context.sessions() as session:
            if case == "configuration_drift":
                await session.execute(
                    update(Assistant)
                    .where(Assistant.tenant_id == 101, Assistant.id == "assistant-a")
                    .values(model_name="2")
                )
            else:
                for model in (BusinessResourceReference, BusinessReferenceSet):
                    await session.execute(
                        delete(model).where(
                            model.tenant_id == 101, model.source_type == "assistant", model.source_id == "assistant-a"
                        )
                    )
            await session.commit()
    initialize = AsyncMock(side_effect=AssertionError("repeated ONLINE must not initialize the Agent"))
    monkeypatch.setattr(
        assistant_module, "AssistantAgent", MagicMock(return_value=SimpleNamespace(init_assistant=initialize))
    )
    with pytest.raises(error):
        await AssistantService.update_status(context.request, context.user, "assistant-a", AssistantStatus.ONLINE.value)
    initialize.assert_not_awaited()
    assistant, _, references, source = await inspect_business(context)
    assert assistant.status == AssistantStatus.ONLINE.value
    if case == "missing_index":
        assert source is None and not references
    else:
        assert source.source_revision == 1 and {row.target_id for row in references} == {"1", "10"}


async def test_valid_repeated_online_revalidates_without_initialization_or_revision_changes(
    assistant_business, monkeypatch
):
    context = assistant_business
    await seed(context)
    await mark_online(context)
    initialize = AsyncMock(side_effect=AssertionError("repeated ONLINE must not initialize the Agent"))
    monkeypatch.setattr(
        assistant_module, "AssistantAgent", MagicMock(return_value=SimpleNamespace(init_assistant=initialize))
    )
    assert await AssistantService.update_status(
        context.request, context.user, "assistant-a", AssistantStatus.ONLINE.value
    )
    initialize.assert_not_awaited()
    assistant, _, references, source = await inspect_business(context)
    assert assistant.status == AssistantStatus.ONLINE.value and source.source_revision == 1 and len(references) == 2
    async with context.sessions() as session:
        assert (await context.repository.aget_root_guard(session, source_key())).source_revision == 1
    AssistantService.update_assistant_hook.assert_not_called()
    assistant_module.telemetry_service.log_event.assert_not_awaited()


@pytest.mark.parametrize("already_offline", [True, False])
async def test_offline_does_not_require_deleted_targets_to_be_executable(
    assistant_business, monkeypatch, already_offline
):
    context = assistant_business
    await seed(context)
    if not already_offline:
        await mark_online(context)
    await stage(context, "model", 1, "deleted")
    initialize = AsyncMock(side_effect=AssertionError("OFFLINE must not initialize the Agent"))
    monkeypatch.setattr(
        assistant_module, "AssistantAgent", MagicMock(return_value=SimpleNamespace(init_assistant=initialize))
    )
    assert await AssistantService.update_status(
        context.request, context.user, "assistant-a", AssistantStatus.OFFLINE.value
    )
    initialize.assert_not_awaited()
    assistant, _, references, source = await inspect_business(context)
    assert assistant.status == AssistantStatus.OFFLINE.value and source.effective and len(references) == 2
    assert source.source_revision == (1 if already_offline else 2)
