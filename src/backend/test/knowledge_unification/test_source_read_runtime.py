"""T380: target-first saved/inspection/preview reads and fail-closed drift.

覆盖 AC: AC-37, AC-68, AC-87, AC-89, AC-91, AC-92
Actual business/index rows use one native AsyncSession. Target ports are doubles
until the real Owners are delivered; they are never production composition.
"""

from dataclasses import replace

import pytest
from sqlalchemy import delete, event, update
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.resource_reference.application.source_contracts import ReferenceTargetReadFact, TransientTargetRequest
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from test.knowledge_unification import test_source_read_repository as repository_tests
from test.knowledge_unification import test_source_read_scope as scopes

source_tenant = scopes.source_tenant
source_context = scopes.source_context
read_context = repository_tests.read_context


class TargetOwner(scopes.ReadTargetOwner):
    state = "valid"
    executable = True
    incomplete = False

    async def ainspect_source_targets(self, session, scope, target_keys, *, identity):
        self.calls.append("targets")
        if self.incomplete:
            return ()
        return tuple(ReferenceTargetReadFact(key, self.state, self.executable, 101) for key in target_keys)


@pytest.fixture
async def runtime_context(read_context):
    from bisheng.resource_reference.application.source_read import ReferenceSourceReadRuntime

    ctx = read_context
    ctx.target = TargetOwner(ctx.owner.calls)
    ctx.runtime = ReferenceSourceReadRuntime(ctx.verifier, ctx.repository, {"model": ctx.target})
    await repository_tests.seed(ctx)
    return ctx


async def test_actual_owner_revalidation_runs_between_targets_and_current_index_read(runtime_context):
    ctx = runtime_context
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, scopes.REQUEST, ctx.identity)
        calls = ctx.owner.calls

        def current_index(state):
            if state.is_select and state.statement._for_update_arg is not None:
                if "business_reference_set" in str(state.statement):
                    calls.append("index")

        event.listen(session.sync_session, "do_orm_execute", current_index)
        result = await ctx.runtime.arequire_source_valid(session, scope, ctx.identity)
        assert calls[:4] == ["candidate", "targets", "root", "index"]
        assert result.snapshot == scopes.snapshot() and result.source_revision == 3 and result.root_revision == 4
        assert result.target_states[0].is_valid and not session.sync_session.identity_map


@pytest.mark.parametrize(
    "state,valid", [("deleting", False), ("invalid_deleted", False), ("invalid_legacy", False), ("valid", False)]
)
async def test_invalid_execution_is_refused_but_real_inspection_can_describe_it(runtime_context, state, valid):
    ctx = runtime_context
    ctx.target.state, ctx.target.executable = state, valid
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, scopes.REQUEST, ctx.identity)
        with pytest.raises(ResourceReferenceInvalidError):
            await ctx.runtime.arequire_source_valid(session, scope, ctx.identity)
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, replace(scopes.REQUEST, purpose="inspect"), ctx.identity)
        result = await ctx.runtime.ainspect_source(session, scope, ctx.identity)
        assert result.target_states[0].state == state and not result.target_states[0].is_valid


@pytest.mark.parametrize("purpose", ["execute", "inspect"])
async def test_inspection_and_execution_authority_cannot_be_interchanged(runtime_context, purpose):
    ctx = runtime_context
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, replace(scopes.REQUEST, purpose=purpose), ctx.identity)
        method = ctx.runtime.ainspect_source if purpose == "execute" else ctx.runtime.arequire_source_valid
        with pytest.raises(ResourceReferenceInvalidError):
            await method(session, scope, ctx.identity)
        assert "targets" not in ctx.owner.calls


@pytest.mark.parametrize(
    "case",
    ["missing_set", "missing_guard", "raw_digest", "revision", "unready", "extractor", "business_drift", "inactive"],
)
async def test_index_defects_are_never_treated_as_an_empty_or_new_source(runtime_context, case):
    ctx = runtime_context
    async with AsyncSession(ctx.engine) as session, session.begin():
        where = (BusinessReferenceSet.tenant_id == 101, BusinessReferenceSet.source_version == "current")
        if case == "missing_set":
            await session.execute(delete(BusinessReferenceSet).where(*where))
        elif case == "missing_guard":
            await session.execute(
                delete(BusinessReferenceSet).where(
                    BusinessReferenceSet.tenant_id == 101, BusinessReferenceSet.record_kind == "root_guard"
                )
            )
        elif case in {"raw_digest", "revision"}:
            await session.execute(
                update(BusinessResourceReference)
                .where(
                    BusinessResourceReference.tenant_id == 101, BusinessResourceReference.source_version == "current"
                )
                .values(**({"target_id": "22"} if case == "raw_digest" else {"source_revision": 8}))
            )
        elif case == "business_drift":
            await session.execute(
                update(scopes.Assistant).where(scopes.Assistant.id == "assistant-a").values(model_name="22")
            )
        else:
            values = {
                "unready": {"ready": False},
                "extractor": {"extractor_version": "obsolete"},
                "inactive": {"effective": False},
            }
            await session.execute(update(BusinessReferenceSet).where(*where).values(**values[case]))
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, scopes.REQUEST, ctx.identity)
        error = ResourceReferenceInvalidError if case == "inactive" else ReferenceCoverageNotReadyError
        with pytest.raises(error):
            await ctx.runtime.arequire_source_valid(session, scope, ctx.identity)


async def test_configuration_changes_after_target_locks_refuse_before_return(runtime_context, monkeypatch):
    ctx = runtime_context
    original = ctx.owner.arevalidate_source

    async def changed(session, request, identity, expected):
        await session.execute(
            update(scopes.Assistant).where(scopes.Assistant.id == "assistant-a").values(model_name="22")
        )
        return await original(session, request, identity, expected)

    monkeypatch.setattr(ctx.owner, "arevalidate_source", changed)
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, scopes.REQUEST, ctx.identity)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await ctx.runtime.arequire_source_valid(session, scope, ctx.identity)


async def test_source_cas_change_after_target_locks_is_a_conflict(runtime_context, monkeypatch):
    ctx = runtime_context
    original = ctx.owner.arevalidate_source

    async def changed(session, request, identity, expected):
        value = await original(session, request, identity, expected)
        await session.execute(
            update(BusinessReferenceSet).where(BusinessReferenceSet.tenant_id == 101).values(source_revision=9)
        )
        await session.execute(
            update(BusinessResourceReference)
            .where(BusinessResourceReference.tenant_id == 101)
            .values(source_revision=9)
        )
        return value

    monkeypatch.setattr(ctx.owner, "arevalidate_source", changed)
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, scopes.REQUEST, ctx.identity)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await ctx.runtime.arequire_source_valid(session, scope, ctx.identity)


async def test_incomplete_target_owner_cannot_unlock_root_revalidation(runtime_context):
    ctx = runtime_context
    ctx.target.incomplete = True
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, scopes.REQUEST, ctx.identity)
        with pytest.raises(ResourceReferenceInvalidError):
            await ctx.runtime.arequire_source_valid(session, scope, ctx.identity)
        assert "root" not in ctx.owner.calls


async def test_preview_has_no_index_dependency_or_reference_writes(runtime_context):
    ctx = runtime_context
    async with AsyncSession(ctx.engine) as session, session.begin():
        await session.execute(delete(BusinessReferenceSet).where(BusinessReferenceSet.tenant_id == 101))
        await session.execute(delete(BusinessResourceReference).where(BusinessResourceReference.tenant_id == 101))
    async with AsyncSession(ctx.engine) as session, session.begin():
        request = TransientTargetRequest("workflow", "workflow-a", scopes.canonical_payload_json({"nodes": []}))
        scope = await ctx.verifier.aissue_transient_scope(session, request, ctx.identity)
        result = await ctx.runtime.arequire_transient_valid(session, scope, ctx.identity)
        assert result.snapshot.resource_id == "workflow-a" and len(result.target_states) == 1
        assert not session.new and not session.dirty and not session.deleted
        ctx.target.executable = False
        with pytest.raises(ResourceReferenceInvalidError):
            await ctx.runtime.arequire_transient_valid(session, scope, ctx.identity)
