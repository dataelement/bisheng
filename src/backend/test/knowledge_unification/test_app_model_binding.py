"""Actual APP whole-source admission and final cached model identity. 覆盖 AC: AC-37, AC-68, AC-71, AC-87, AC-89, AC-91, AC-92."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.app_publish import composition
from bisheng.app_publish.application.reference_access import get_hosted_app_reference_runtime
from bisheng.app_publish.domain.services import capability_bus_service as bus
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.llm.domain.services.model_catalog import ResolvedModel
from bisheng.resource_reference.application.contracts import SourceType
from bisheng.resource_reference.application.source_contracts import SourceReadRequest
from test.knowledge_unification import test_app_snapshot as fixtures

ctx = fixtures.ctx
resolving = fixtures.resolving
application = fixtures.application
writing = fixtures.writing


def resolved(model_id=11, server_id=1):
    return ResolvedModel(model_id, server_id, "alpha", "own", "openai", "own/alpha")


async def admitted(context, session, *, purpose="execute"):
    composition.register()
    runtime = await get_hosted_app_reference_runtime()
    request = SourceReadRequest(SourceType.HOSTED_APP_VERSION, "actual-app", purpose=purpose)
    scope = await runtime.verifier.aissue_scope(session, request, context.identity)
    result = (
        await runtime.arequire_source_valid(session, scope, context.identity)
        if purpose == "execute"
        else await runtime.ainspect_source(session, scope, context.identity)
    )
    return runtime, result.snapshot


async def test_runtime_exposes_its_exact_registered_source_owner(writing):
    composition.register()
    runtime = await get_hosted_app_reference_runtime()
    assert runtime.source_owner is runtime.verifier._owners[SourceType.HOSTED_APP_VERSION]


async def test_candidate_or_inspection_is_not_model_execution_admission(writing):
    composition.register()
    runtime = await get_hosted_app_reference_runtime()
    async with AsyncSession(writing.engine) as session, session.begin():
        candidate = await runtime.source_owner.aresolve_source(
            session, SourceReadRequest(SourceType.HOSTED_APP_VERSION, "actual-app"), writing.identity
        )
        with pytest.raises(ResourceReferenceInvalidError):
            await runtime.source_owner.assert_model_binding_current(
                session, candidate, writing.identity, "alpha", resolved()
            )
        _, snapshot = await admitted(writing, session, purpose="inspect")
        with pytest.raises(ResourceReferenceInvalidError):
            await runtime.source_owner.assert_model_binding_current(
                session, snapshot, writing.identity, "alpha", resolved()
            )


async def test_same_source_alias_uses_original_complete_plan_after_full_core_admission(writing):
    async with AsyncSession(writing.engine) as session, session.begin():
        runtime, snapshot = await admitted(writing, session)
        assert (
            await runtime.source_owner.assert_model_binding_current(
                session, snapshot, writing.identity, "own/alpha", resolved()
            )
            is None
        )
        assert (
            await runtime.source_owner.assert_model_binding_current(
                session, snapshot, writing.identity, "alpha", resolved()
            )
            is None
        )


@pytest.mark.parametrize("model_id,server_id", [(13, 1), (11, 2)])
async def test_cached_gateway_actual_id_or_server_mismatch_is_never_called(writing, model_id, server_id):
    async with AsyncSession(writing.engine) as session, session.begin():
        runtime, snapshot = await admitted(writing, session)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await runtime.source_owner.assert_model_binding_current(
                session, snapshot, writing.identity, "alpha", resolved(model_id, server_id)
            )


async def test_model_proof_cannot_cross_transaction_or_original_identity(writing):
    async with AsyncSession(writing.engine) as session:
        async with session.begin():
            runtime, snapshot = await admitted(writing, session)
            with pytest.raises(ResourceReferenceInvalidError):
                await runtime.source_owner.assert_model_binding_current(
                    session, snapshot, writing.identity.model_copy(), "alpha", resolved()
                )
        async with session.begin():
            with pytest.raises(ResourceReferenceInvalidError):
                await runtime.source_owner.assert_model_binding_current(
                    session, snapshot, writing.identity, "alpha", resolved()
                )


@pytest.fixture
async def capability_bus(writing, monkeypatch):
    @asynccontextmanager
    async def factory():
        async with AsyncSession(writing.engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(bus, "get_async_db_session", factory)
    # A saved version must consume its frozen index, never old independent DAO/name readers.
    monkeypatch.setattr(bus, "_resolve_knowledge_refs", AsyncMock(side_effect=AssertionError("free resolution")))
    composition.register()
    return writing


async def test_actual_adapter_checks_final_cached_model_with_real_full_source(capability_bus):
    adapter = bus.HostedAppDeclarationAdapter()
    assert await adapter.assert_model_binding(capability_bus.identity, "own/alpha", resolved()) is None
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await adapter.assert_model_binding(capability_bus.identity, "alpha", resolved(13))


async def test_effective_declaration_uses_original_principal_and_frozen_ids(capability_bus):
    declaration = await bus.load_effective_declaration("actual-app", principal=capability_bus.identity)
    assert declaration.version_id == fixtures.fixtures.VERSION
    assert declaration.knowledge_whitelist == [7]
    assert declaration.model_names == frozenset({"alpha"})
    with pytest.raises(ResourceReferenceInvalidError):
        await bus.load_effective_declaration("actual-app", principal=capability_bus.identity.model_copy())


async def test_whole_source_bad_knowledge_blocks_model_and_retrieval_before_io(capability_bus, monkeypatch):
    from bisheng.knowledge.domain.services.retrieval_facade_service import RetrievalFacadeService

    retrieval = AsyncMock()
    monkeypatch.setattr(RetrievalFacadeService, "retrieve", retrieval)
    async with AsyncSession(capability_bus.engine) as session, session.begin():
        await session.execute(sa.delete(Knowledge).where(Knowledge.id == 7))
    with pytest.raises(BaseErrorCode):
        await bus.HostedAppDeclarationAdapter().assert_model_binding(capability_bus.identity, "alpha", resolved())
    with pytest.raises(BaseErrorCode):
        await bus.CapabilityBusService.retrieve(
            app_id="actual-app", principal=capability_bus.identity, access_user_id=4, query="question"
        )
    retrieval.assert_not_awaited()


async def test_broken_whitelist_never_silently_drops_a_saved_reference():
    declaration = bus.EffectiveDeclaration(
        "app", 101, "actual-version", knowledge=(bus.DeclaredKnowledge("7", 7, reason=bus.REASON_REVOKED),)
    )
    with pytest.raises(ResourceReferenceInvalidError):
        _ = declaration.knowledge_whitelist


@pytest.mark.parametrize("knowledge_type", [0, 1, 3])
async def test_actual_retrieval_keeps_access_user_narrowing_and_legacy_kinds(
    capability_bus, monkeypatch, knowledge_type
):
    from bisheng.knowledge.domain.schemas.retrieval_facade import RetrievalIdentity
    from bisheng.knowledge.domain.services.retrieval_facade_service import RetrievalFacadeService

    async with AsyncSession(capability_bus.engine) as session, session.begin():
        await session.execute(sa.update(Knowledge).where(Knowledge.id == 7).values(type=knowledge_type))
    access_identity = object()
    from_user = AsyncMock(return_value=access_identity)
    retrieval = AsyncMock(return_value=object())
    record = AsyncMock()
    monkeypatch.setattr(RetrievalIdentity, "from_user", from_user)
    monkeypatch.setattr(RetrievalFacadeService, "retrieve", retrieval)
    monkeypatch.setattr(bus.CapabilityBusService, "_record", record)
    result = await bus.CapabilityBusService.retrieve(
        app_id="actual-app", principal=capability_bus.identity, access_user_id=44, query="question", knowledge_ids=[7]
    )
    assert result is retrieval.return_value
    from_user.assert_awaited_once_with(44, 101)
    assert retrieval.await_args.args[0] is access_identity
    assert retrieval.await_args.args[1].whitelist == [7]
    assert retrieval.await_args.args[1].knowledge_ids == [7]
    with pytest.raises(BaseErrorCode):
        await bus.CapabilityBusService.retrieve(
            app_id="actual-app",
            principal=capability_bus.identity,
            access_user_id=44,
            query="question",
            knowledge_ids=[8],
        )
    assert retrieval.await_count == 1
