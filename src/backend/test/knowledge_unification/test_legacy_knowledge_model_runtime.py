"""Real SQL source admission, visible invalidity and lawful explicit repair."""

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.knowledge.application.model_reference import KnowledgeModelReferenceApplication as App
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.services.model_reference_extractor import legacy_knowledge_model_version
from bisheng.resource_reference.application.contracts import reference_set_digest
from bisheng.resource_reference.application.source_contracts import SourceReadRequest
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from test.knowledge_unification import test_kn_model_source as original

store, tenant, business, admission = original.store, original.tenant, original.business, original.admission


async def legacy(context, *, proof=True):
    async with context.sessions() as session, session.begin():
        await session.execute(sa.update(Knowledge).where(Knowledge.id == 40).values(model="bge-large-zh"))
        await session.execute(
            sa.delete(BusinessResourceReference).where(BusinessResourceReference.source_type == "knowledge")
        )
        if proof:
            await session.execute(
                sa.update(BusinessReferenceSet)
                .where(BusinessReferenceSet.record_kind == "source")
                .values(
                    extractor_version=legacy_knowledge_model_version("bge-large-zh"), digest=reference_set_digest(())
                )
            )


async def test_retained_source_can_be_inspected_but_never_executes_or_falls_back(admission):
    context, runtime, source, _ = admission
    await legacy(context)
    async with context.sessions() as session:
        snapshot = await source.aresolve_source(
            session, SourceReadRequest("knowledge", "40", purpose="inspect"), context.user
        )
        assert snapshot.invalid_reason == "knowledge_legacy_model_name_unresolved" and not snapshot.references
        assert "bge-large-zh" in snapshot.payload_json
        with pytest.raises(ResourceReferenceInvalidError):
            await runtime.arequire(40, login_user=context.user, session=session)


async def test_explicit_authorized_reconfiguration_replaces_invalid_raw_name(admission):
    context, runtime, _, _ = admission
    await legacy(context)
    async with context.sessions() as session:
        prepared = await App.aprepare_model_change(
            session, 40, 12, login_user=context.user, operation_id="repair-legacy"
        )
        await App.aapply_model_change(session, prepared)
        await session.commit()
    async with context.sessions() as session:
        value = await runtime.arequire(40, login_user=context.user, session=session)
        assert value.model_id == 12


async def test_unregistered_legacy_name_is_inspectable_without_reference_receipt(admission):
    context, _, source, _ = admission
    await legacy(context, proof=False)
    async with context.sessions() as session:
        snapshot = await source.aresolve_source(
            session, SourceReadRequest("knowledge", "40", purpose="inspect"), context.user
        )
        assert snapshot.invalid_reason == "knowledge_legacy_model_name_unresolved"
        assert not snapshot.references
        assert (
            await source.arevalidate_source(
                session, SourceReadRequest("knowledge", "40", purpose="inspect"), context.user, snapshot
            )
            == snapshot
        )
