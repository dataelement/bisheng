"""T378: only the scope's original source/target may consume frozen legacy proof.

覆盖 AC: AC-89, AC-91, AC-93
"""

from dataclasses import replace

import pytest
from sqlalchemy import select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun
from bisheng.resource_reference.application.contracts import TargetKey
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from test.knowledge_unification import test_source_read_repository as repository_tests
from test.knowledge_unification import test_source_read_scope as scopes

source_tenant = scopes.source_tenant
source_context = scopes.source_context
read_context = repository_tests.read_context


@pytest.fixture
async def legacy_context(read_context, monkeypatch):
    from bisheng.knowledge.application.reference_read_legacy_evidence import KnowledgeReferenceReadLegacyEvidence

    ctx = read_context
    monkeypatch.setattr(
        scopes.tenant_filter,
        "_tenant_aware_tables",
        scopes.tenant_filter._tenant_aware_tables | {KnowledgeUnificationRun.__tablename__},
    )
    await repository_tests.seed(ctx, tenant_id=1)
    async with ctx.engine.begin() as connection:
        await connection.run_sync(lambda conn: KnowledgeUnificationRun.__table__.create(conn))
    async with AsyncSession(ctx.engine) as session, session.begin():
        with bypass_tenant_filter():
            await session.execute(
                update(BusinessResourceReference)
                .where(BusinessResourceReference.tenant_id == 1, BusinessResourceReference.source_version == "current")
                .values(
                    target_tenant_id=None,
                    legacy_invalid_reason="target_missing",
                    legacy_run_id="run-original",
                    legacy_evidence_key="source-model",
                )
            )
            for tenant_id, digest in ((1, "a" * 64), (202, "c" * 64)):
                session.add(
                    KnowledgeUnificationRun(
                        tenant_id=tenant_id,
                        run_id="run-original",
                        phase="verified",
                        baseline_hash=digest,
                        plan_hash="b" * 64,
                        baseline_ref={"object_key": f"{tenant_id}/baseline", "sha256": digest},
                        plan_ref={"object_key": f"{tenant_id}/plan", "sha256": "b" * 64},
                    )
                )
    ctx.legacy = KnowledgeReferenceReadLegacyEvidence(ctx.verifier)
    return ctx


async def proof(ctx, session, scope):
    return await ctx.legacy.aresolve(
        session,
        scope,
        TargetKey("model", "11"),
        run_id="run-original",
        evidence_key="source-model",
        identity=ctx.identity,
    )


async def test_cross_source_legacy_uses_its_exact_original_tenant_without_identity_map(legacy_context):
    ctx = legacy_context
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, replace(scopes.REQUEST, purpose="inspect"), ctx.identity)
        evidence = await proof(ctx, session, scope)
        assert evidence.run_id == "run-original" and evidence.baseline_hash == "a" * 64
        assert not session.sync_session.identity_map and not session.new and not session.dirty
    async with ctx.engine.connect() as connection:
        rows = (
            await connection.execute(
                select(BusinessResourceReference.__table__).where(
                    BusinessResourceReference.tenant_id == 1, BusinessResourceReference.source_version == "current"
                )
            )
        ).all()
        assert len(rows) == 1 and rows[0].target_tenant_id is None


@pytest.mark.parametrize("case", ["scope_copy", "identity", "target", "run", "key", "unmarked"])
async def test_legacy_evidence_cannot_be_borrowed_or_rebound(legacy_context, case):
    ctx = legacy_context
    if case == "unmarked":
        async with AsyncSession(ctx.engine) as session, session.begin():
            await session.execute(
                update(BusinessResourceReference)
                .where(BusinessResourceReference.tenant_id == 1)
                .values(target_tenant_id=1, legacy_invalid_reason=None, legacy_run_id=None, legacy_evidence_key=None)
            )
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, scopes.REQUEST, ctx.identity)
        if case == "scope_copy":
            scope = replace(scope)
        elif case == "identity":
            ctx.identity.credential = "another principal"
        with pytest.raises(ResourceReferenceInvalidError):
            await ctx.legacy.aresolve(
                session,
                scope,
                TargetKey("model", "22" if case == "target" else "11"),
                run_id="other-run" if case == "run" else "run-original",
                evidence_key="other-key" if case == "key" else "source-model",
                identity=ctx.identity,
            )


@pytest.mark.parametrize("case", ["preparing", "failed", "absolute_path", "wrong_hash", "wrong_origin"])
async def test_only_the_original_frozen_descriptor_can_supply_proof(legacy_context, case):
    ctx = legacy_context
    values = (
        {"phase": case}
        if case in {"preparing", "failed"}
        else {"baseline_ref": {"object_key": "/tmp/local-baseline", "sha256": "a" * 64}}
        if case == "absolute_path"
        else {"plan_ref": {"object_key": "1/plan", "sha256": "c" * 64}}
        if case == "wrong_hash"
        else {"origin": "empty_tenant"}
    )
    async with AsyncSession(ctx.engine) as session, session.begin():
        await session.execute(
            update(KnowledgeUnificationRun).where(KnowledgeUnificationRun.tenant_id == 1).values(**values)
        )
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, scopes.REQUEST, ctx.identity)
        with pytest.raises(ReferenceCoverageNotReadyError):
            await proof(ctx, session, scope)


async def test_unconfigured_extra_original_slots_are_not_silently_selected(legacy_context):
    ctx = legacy_context
    async with AsyncSession(ctx.engine) as session, session.begin():
        row = repository_tests.reference(1)
        row.slot_key = "unknown-slot"
        row.legacy_invalid_reason, row.legacy_run_id, row.legacy_evidence_key = (
            "target_missing",
            "run-original",
            "other-proof",
        )
        session.add(row)
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, scopes.REQUEST, ctx.identity)
        with pytest.raises(ResourceReferenceInvalidError):
            await proof(ctx, session, scope)
