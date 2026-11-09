"""Complete native business/RRT/confirmation transactions on real model SQL."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.assistant.domain.services.reference_extractor import extract_assistant_references
from bisheng.common.errcode.knowledge import ResourceReferenceConflictError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import management_tenant_scope
from bisheng.database.models.assistant import Assistant
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.llm.application.model_deletion import ModelDeletionApplication
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.permission.application.model_sharing_projection import ModelSharingProjectionApplication
from bisheng.permission.domain.models import PermissionProjectionOperation, PermissionProjectionTuple
from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository
from bisheng.resource_reference.application.contracts import SourceKey, SourceType, reference_set_digest
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from bisheng.resource_reference.domain.repositories.coverage_repository import CoverageRepository
from test.knowledge_unification import test_model_delete_plan_application as actual
from test.knowledge_unification.test_model_share_projection_deferred import Marker
from test.knowledge_unification.test_model_sharing_projection import Client

model_owner_tenant = actual.model_owner_tenant
removal_session = actual.removal_session
impact = actual.impact
ready = actual.ready


@pytest.fixture
async def business(ready, monkeypatch):
    from bisheng.llm.domain.services.context_window import ContextWindowService

    monkeypatch.setattr(ContextWindowService, "invalidate", AsyncMock())
    session, references, plans = ready
    await session.commit()
    metadata = sa.MetaData()
    for model in (PermissionProjectionOperation, PermissionProjectionTuple):
        model.__table__.to_metadata(metadata).c.id.type = sa.Integer()
    async with session.bind.begin() as connection:
        await connection.run_sync(metadata.create_all)

    def physical_begin(connection):
        connection.exec_driver_sql("BEGIN")

    sa.event.listen(session.bind.sync_engine, "begin", physical_begin)

    def coverage(active):
        ledger = actual.native.SqlLedger(active)
        return CoverageRepository(ledger, global_port=ledger)

    references.coverage_factory = coverage
    active = [0]

    @asynccontextmanager
    async def factory():
        active[0] += 1
        try:
            async with AsyncSession(session.bind, expire_on_commit=False) as current:
                yield current
        finally:
            active[0] -= 1

    client = Client((), active)

    async def sharing(*, scope):
        return ModelSharingProjectionApplication(
            client=client, marker=Marker(), scope=scope, repository=ProjectionRepository(factory)
        )

    application = ModelDeletionApplication(
        references=references, plans=plans, session_factory=factory, sharing_factory=sharing
    )
    try:
        yield factory, application, references, plans, client
    finally:
        sa.event.remove(session.bind.sync_engine, "begin", physical_begin)


async def confirmation(factory, references, plans, user, *, server_id=1, request=None):
    async with factory() as session:
        async with session.begin():
            precheck = actual.application(references, plans)
            if request is None:
                result = await precheck.aplan_server_delete(session, identity=user, server_id=server_id)
            else:
                result = await precheck.aplan_removed_update(session, identity=user, server=request)
    return {"confirmation_id": result.confirmation.confirmation_id, "plan_digest": result.confirmation.plan_digest}


async def records(factory, model):
    async with factory() as session:
        return tuple((await session.execute(sa.select(*model.__table__.c).order_by(model.__table__.c.id))).all())


@pytest.mark.parametrize("server_id", [1, 5])
async def test_ordinary_native_delete_and_same_body_replay_have_one_actual_business_mutation(business, server_id):
    factory, app, _, _, client = business
    async with factory() as session:
        async with session.begin():
            await session.execute(
                sa.delete(BusinessResourceReference).where(BusinessResourceReference.tenant_id == 101)
            )
    with actual.native.actor() as user:
        actual.web(user)
        result = await app.adelete_server(identity=user, server_id=server_id)
        replay = await app.adelete_server(identity=user, server_id=server_id)
    assert result == replay and result["deleted_server"] is True
    async with factory() as session:
        assert await session.get(LLMServer, server_id) is None
        tombstones = (await session.execute(sa.select(ResourceReferenceTombstone))).scalars().all()
        assert len(tombstones) == (5 if server_id == 1 else 0)
        assert all(row.stage == "deleted" and row.operation_id == result["operation_id"] for row in tombstones)
    assert client.writes == []


async def test_ordinary_references_refuse_before_preparation_or_business_or_sharing(business):
    factory, app, _, _, client = business
    before = await records(factory, LLMModel)
    with actual.native.actor() as user:
        actual.web(user)
        with pytest.raises(ResourceReferenceConflictError) as failure:
            await app.adelete_server(identity=user, server_id=1)
    assert "same" not in json.dumps(failure.value.kwargs)
    assert await records(factory, LLMModel) == before
    assert not await records(factory, KnowledgeOperationPlan)
    assert not await records(factory, ResourceReferenceTombstone)
    assert client.writes == []


async def test_force_keeps_saved_source_and_brr_bytes_and_actual_source_validation_refuses_execution(business):
    factory, app, references, plans, _ = business
    # Replace the impact-only seed with a genuine persisted assistant slot and
    # its exact extractor digest/root guard before exercising real execution.
    async with factory() as session:
        async with session.begin():
            await session.run_sync(lambda current: Assistant.__table__.create(current.connection(), checkfirst=True))
            await session.execute(
                sa.delete(BusinessResourceReference).where(BusinessResourceReference.tenant_id == 101)
            )
            await session.execute(sa.delete(BusinessReferenceSet).where(BusinessReferenceSet.tenant_id == 101))
            assistant = Assistant(id="same", name="private-saved-name", tenant_id=101, user_id=7, model_name="11")
            session.add(assistant)
            slots = extract_assistant_references(model_name=assistant.model_name, knowledge_ids=())
            session.add(
                BusinessReferenceSet(
                    tenant_id=101,
                    source_type="assistant",
                    source_id="same",
                    source_version="current",
                    source_revision=3,
                    extractor_version="assistant-v1",
                    digest=reference_set_digest(slots),
                    ready=True,
                    effective=True,
                )
            )
            session.add(
                references.runtime.repository._new_guard(SourceKey(101, SourceType.ASSISTANT, "same", "current"), 4)
            )
            session.add(
                BusinessResourceReference(
                    tenant_id=101,
                    source_type="assistant",
                    source_id="same",
                    source_version="current",
                    slot_key="model_name",
                    target_type="model",
                    target_id="11",
                    target_tenant_id=101,
                    source_revision=3,
                )
            )
    before = await records(factory, BusinessResourceReference)
    before_source = await records(factory, Assistant)
    with actual.native.actor() as user:
        actual.web(user)
        control = await confirmation(factory, references, plans, user)
        result = await app.adelete_server(identity=user, server_id=1, force=True, **control)
        user.token_version = 4
        user._runtime_credential_reference = {**user._runtime_credential_reference, "token_version": 4}
        assert await app.adelete_server(identity=user, server_id=1, force=True, **control) == result
        async with factory() as session:
            with pytest.raises(ResourceReferenceInvalidError):
                await references.runtime.arequire_source_valid(
                    session, SourceKey(101, SourceType.ASSISTANT, "same", "current"), references=slots
                )
    assert await records(factory, BusinessResourceReference) == before
    assert await records(factory, Assistant) == before_source


@pytest.mark.parametrize("subjects", [(), tuple(range(100, 151))])
async def test_root_shared_provider_has_complete_actual_projection_before_sql_delete(business, subjects):
    factory, app, references, plans, client = business
    client.rows = {(f"tenant:{value}", "shared_with", "llm_server:2") for value in subjects}
    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        control = await confirmation(factory, references, plans, user, server_id=2)
        result = await app.adelete_server(identity=user, server_id=2, **control)
        assert result["removed_model_ids"] == [22]
        assert not client.rows and len(client.writes) == (len(subjects) + 49) // 50
        async with factory() as session:
            root = await session.get(LLMServer, 2)
            assert root is None
