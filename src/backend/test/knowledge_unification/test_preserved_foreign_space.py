"""Preserve exact saved foreign space slots as invalid without granting access."""

from dataclasses import replace

import pytest
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import ResourceReferenceConflictError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.knowledge.application.reference_target_owner import KnowledgeReferenceTargetOwner
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.resource_reference.application.contracts import TargetKey
from bisheng.resource_reference.application.source_contracts import TransientTargetRequest
from bisheng.resource_reference.application.source_read import ReferenceSourceReadRuntime
from bisheng.resource_reference.domain.repositories.source_read_repository import SourceReadRepository
from test.knowledge_unification import test_knowledge_read_owner as reads
from test.knowledge_unification import test_knowledge_reference_owner as targets

owner_tenant = targets.owner_tenant
engine = targets.engine
knowledge_read_context = reads.knowledge_read_context


@pytest.mark.parametrize("owner_id", [1, 202])
def test_native_exact_saved_foreign_space_is_invalid_and_new_or_copy_queries_fail(engine, owner_id):
    with Session(engine) as session, session.begin():
        with bypass_tenant_filter():
            session.add(Knowledge(id=30, tenant_id=owner_id, user_id=11, name="retained", type=3, is_shared=False))
        key = TargetKey("knowledge_space", "30")
        targets.original(session, key, target_tenant_id=owner_id, space_id="30")
        owner = KnowledgeReferenceTargetOwner()
        verifier = targets.verifier(owner)
        owner.prelock_targets(session, (key,), (targets.SOURCE,))
        result = verifier.verify_targets(session, targets.SOURCE, (key,))[0].target
        assert result.state == "invalid_scope" and result.target_tenant_id == owner_id
        assert result.target_space_id == "30" and not result.new_binding_allowed and result.evidence is None
        for source in (None, replace(targets.SOURCE, source_id="copy"), replace(targets.SOURCE, source_version="new")):
            with pytest.raises((ResourceReferenceInvalidError, ResourceReferenceConflictError)):
                if source is None:
                    verifier.verify_owner_targets(session, (key,))
                else:
                    verifier.verify_targets(session, source, (key,))


async def test_native_read_preserves_owner_and_denies_execution_and_unsaved_preview(knowledge_read_context):
    ctx = knowledge_read_context
    ref = reads.spec("knowledge_space", 30)
    await reads.configure(ctx, (ref,), cached_owners={ref.target: 1}, cached_spaces={ref.target: "30"})
    async with AsyncSession(ctx.engine) as session, session.begin():
        with bypass_tenant_filter():
            session.add(Knowledge(id=30, tenant_id=1, user_id=7, name="retained", type=3))
    runtime = ReferenceSourceReadRuntime(
        ctx.verifier, SourceReadRepository(ctx.verifier), {"knowledge_space": ctx.knowledge}
    )
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, reads.REQUEST, ctx.identity)
        fact = (await ctx.knowledge.ainspect_source_targets(session, scope, (ref.target,), identity=ctx.identity))[0]
        assert fact.state == "invalid_scope" and not fact.is_valid and fact.target_tenant_id == 1
        with pytest.raises(ResourceReferenceInvalidError):
            await runtime.arequire_source_valid(session, scope, ctx.identity)
        preview = await ctx.verifier.aissue_transient_scope(
            session, TransientTargetRequest("workflow", "workflow-a", reads.payload((ref,))), ctx.identity
        )
        with pytest.raises(ResourceReferenceInvalidError):
            await ctx.knowledge.ainspect_transient_targets(session, preview, (ref.target,), identity=ctx.identity)
