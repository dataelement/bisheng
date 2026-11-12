"""Approved AC-93: old foreign model slots remain visible and unusable.

Native SQL paths prove exact-source retention, no new/copy binding, current
model/server ownership and sync/async read gates. No model credentials escape.
"""

from dataclasses import replace

import pytest
import sqlalchemy as sa
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import (
    ResourceReferenceConflictError,
    ResourceReferenceInvalidError,
)
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.assistant import Assistant
from bisheng.llm.application.reference_target_owner import ModelReferenceTargetOwner
from bisheng.llm.application.source_read_target_owner import ModelSourceReadTargetOwner
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.resource_reference.application.bindings import ReferenceBindings
from bisheng.resource_reference.application.contracts import (
    BindingWriteContext,
    ReferenceSpec,
    TargetKey,
    TransactionIdentity,
    VerifiedReferenceSet,
    reference_set_digest,
)
from bisheng.resource_reference.application.source_contracts import TransientTargetRequest
from bisheng.resource_reference.application.source_read import ReferenceSourceReadRuntime
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from bisheng.resource_reference.domain.repositories.source_read_repository import SourceReadRepository
from test.knowledge_unification import test_model_read_owner as reads
from test.knowledge_unification import test_model_reference_owner as models
from test.knowledge_unification import test_source_read_native as sync_reads

model_owner_tenant = models.model_owner_tenant
engine = models.engine
owner_tenant = reads.owner_tenant
knowledge_read_context = reads.knowledge_read_context
model_read_context = reads.model_read_context
source_tenant = sync_reads.source_tenant
native = sync_reads.native


def saved(source=models.SOURCE):
    return BusinessResourceReference(
        tenant_id=source.tenant_id,
        source_type=source.source_type.value,
        source_id=source.source_id,
        source_version=source.source_version,
        slot_key="model_name",
        target_type="model",
        target_id="33",
        target_tenant_id=202,
        source_revision=1,
    )


def test_exact_native_foreign_owner_fact_is_invalid_scope_and_owner_query_stays_closed(engine):
    with Session(engine) as session, session.begin():
        models.setup(session)
        session.add(saved())
        session.flush()
        owner = ModelReferenceTargetOwner(sharing=models.FrozenSharing())
        verifier = models.verify(owner)
        key = TargetKey("model", "33")
        owner.prelock_targets(session, (key,), (models.SOURCE,))
        target = verifier.verify_targets(session, models.SOURCE, (key,))[0].target
        assert target.state == "invalid_scope" and target.target_tenant_id == 202
        assert target.model_server_id == "3" and target.evidence is None and not target.new_binding_allowed
        with pytest.raises(ResourceReferenceInvalidError):
            verifier.verify_owner_targets(session, (key,))
        for source in (replace(models.SOURCE, source_id="copy"), replace(models.SOURCE, source_version="v2")):
            with pytest.raises((ResourceReferenceInvalidError, ResourceReferenceConflictError)):
                verifier.verify_targets(session, source, (key,))


@pytest.mark.parametrize("change", ["server_owner", "model_owner", "legacy", "space"])
def test_existing_slot_does_not_launder_structural_or_owner_drift(engine, change):
    with Session(engine) as session, session.begin():
        models.setup(session)
        row = saved()
        session.add(row)
        with bypass_tenant_filter():
            if change == "server_owner":
                session.exec(sa.update(LLMServer).where(LLMServer.id == 3).values(tenant_id=101))
            elif change == "model_owner":
                session.exec(sa.update(LLMModel).where(LLMModel.id == 33).values(tenant_id=101))
            elif change == "legacy":
                row.legacy_invalid_reason, row.legacy_run_id, row.legacy_evidence_key = "target_missing", "old", "proof"
            else:
                row.target_space_id = "9000"
        session.flush()
        with pytest.raises(ResourceReferenceInvalidError):
            models.verify(ModelReferenceTargetOwner()).verify_targets(
                session, models.SOURCE, (TargetKey("model", "33"),)
            )


async def test_async_native_foreign_fact_retains_actual_owner_without_sharing():
    db = await models.async_database()
    try:
        async with AsyncSession(db) as session, session.begin():
            session.add(saved())
            await session.flush()
            target = (
                await models.verify(ModelReferenceTargetOwner()).averify_targets(
                    session, models.SOURCE, (TargetKey("model", "33"),)
                )
            )[0].target
            assert target.state == "invalid_scope" and target.target_tenant_id == 202 and target.evidence is None
    finally:
        await db.dispose()


async def test_native_read_details_classify_but_execution_and_preview_refuse(model_read_context):
    ctx = model_read_context
    ref = reads.knowledge.spec("model", 33)
    await reads.knowledge.configure(ctx, (ref,), cached_owners={ref.target: 202})
    ctx.sharing.error = AssertionError("foreign servers cannot enter Root sharing")
    runtime = ReferenceSourceReadRuntime(ctx.verifier, SourceReadRepository(ctx.verifier), {"model": ctx.model})
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, reads.knowledge.REQUEST, ctx.identity)
        fact = (await ctx.model.ainspect_source_targets(session, scope, (ref.target,), identity=ctx.identity))[0]
        assert fact.state == "invalid_scope" and not fact.is_valid and fact.target_tenant_id == 202
        with pytest.raises(ResourceReferenceInvalidError):
            await runtime.arequire_source_valid(session, scope, ctx.identity)
        preview = await ctx.verifier.aissue_transient_scope(
            session, TransientTargetRequest("workflow", "workflow-a", reads.knowledge.payload((ref,))), ctx.identity
        )
        with pytest.raises(ResourceReferenceInvalidError):
            await ctx.model.ainspect_transient_targets(session, preview, (ref.target,), identity=ctx.identity)


def test_sync_native_read_also_classifies_without_loading_foreign_configuration(native):
    ctx = native
    from sqlmodel import SQLModel

    with ctx.engine.begin() as conn:
        SQLModel.metadata.create_all(conn, tables=models.TABLES)
    with Session(ctx.engine) as session, session.begin():
        models.setup(session)
        session.exec(sa.update(Assistant).where(Assistant.id == "assistant-a").values(model_name="33"))
        session.exec(sa.update(BusinessResourceReference).values(target_id="33", target_tenant_id=202))
        ref = ReferenceSpec("model_name", TargetKey("model", "33"))
        session.exec(
            sa.update(BusinessReferenceSet)
            .where(BusinessReferenceSet.record_kind == "source")
            .values(digest=reference_set_digest((ref,)))
        )
    from bisheng.resource_reference.application.source_verification import SourceReadVerifier

    ctx.verifier = SourceReadVerifier({"assistant": ctx.owner}, sync_reads.NativeIdentity())
    target = ModelSourceReadTargetOwner(ctx.verifier)
    runtime = ReferenceSourceReadRuntime(ctx.verifier, SourceReadRepository(ctx.verifier), {"model": target})
    with Session(ctx.engine) as session:
        scope = ctx.verifier.issue_scope(session, sync_reads.scopes.REQUEST, ctx.identity)
        fact = target.inspect_source_targets(session, scope, (ref.target,), identity=ctx.identity)[0]
        assert fact.state == "invalid_scope" and fact.target_tenant_id == 202 and not fact.is_valid
        with pytest.raises(ResourceReferenceInvalidError):
            runtime.require_source_valid(session, scope, ctx.identity)


def test_native_binding_retains_same_slot_rejects_new_slot_and_allows_removal(engine):
    with engine.begin() as conn:
        BusinessReferenceSet.__table__.create(conn, checkfirst=True)
    with Session(engine) as session, session.begin():
        models.setup(session)
        source = models.SOURCE
        old = ReferenceSpec("model_name", TargetKey("model", "33"))
        session.add(saved())
        for version, kind in (("__root__", "root_guard"), ("current", "source")):
            session.add(
                BusinessReferenceSet(
                    tenant_id=101,
                    source_type="assistant",
                    source_id="a1",
                    source_version=version,
                    record_kind=kind,
                    source_revision=1,
                    extractor_version="test-v1",
                    digest=reference_set_digest((old,)),
                    ready=kind == "source",
                    effective=kind == "source",
                )
            )
        session.flush()
        verifier = models.verify(ModelReferenceTargetOwner())
        repo = ReferenceRepository(verifier=verifier)
        bindings = ReferenceBindings(repo, verifier)

        def verified(refs, revision):
            receipts = verifier.verify_targets(session, source, (old.target,))
            context = BindingWriteContext(
                source,
                revision,
                revision,
                (old.target,),
                reference_set_digest((old,)),
                receipts,
                TransactionIdentity.capture(session),
            )
            return VerifiedReferenceSet(refs, "test-v1", context)

        kept = bindings.replace_source_bindings(session, source, 1, 2, verified((old,), 1), True)
        assert kept.retained_invalid == 1 and kept.added == kept.removed == 0
        with pytest.raises(ResourceReferenceInvalidError) as exc:
            bindings.replace_source_bindings(
                session, source, 2, 3, verified((ReferenceSpec("new", old.target),), 2), True
            )
        assert exc.value.kwargs["reason"] == "new_invalid_reference"
        removed = bindings.replace_source_bindings(session, source, 2, 3, verified((), 2), True)
        assert removed.removed == 1 and not repo.list_source_references(session, source)
