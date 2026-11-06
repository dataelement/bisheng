"""Actual APP whole-source admission and final cached model identity. 覆盖 AC: AC-37, AC-68, AC-71, AC-87, AC-89, AC-91, AC-92."""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.app_publish import composition
from bisheng.app_publish.application.reference_access import get_hosted_app_reference_runtime
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
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
