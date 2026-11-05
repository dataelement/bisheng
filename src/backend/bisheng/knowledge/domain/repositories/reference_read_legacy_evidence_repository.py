"""Frozen legacy provenance for one issued source read scope, without ORM loads."""

from dataclasses import fields

from sqlalchemy import select

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun
from bisheng.knowledge.domain.repositories.reference_legacy_evidence_repository import KnowledgeLegacyEvidenceRepository
from bisheng.resource_reference.application.contracts import ReferenceSpec, TargetKey
from bisheng.resource_reference.application.source_verification import SourceReadVerifier
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.repositories.source_read_repository import ReferenceReadRow


class KnowledgeReadLegacyEvidenceRepository:
    def __init__(self, verifier: SourceReadVerifier):
        if not isinstance(verifier, SourceReadVerifier):
            raise TypeError("legacy read evidence requires the actual source authority")
        self.verifier = verifier

    async def aload(self, session, scope, target, *, run_id, evidence_key, identity):
        snapshot = await self.verifier.aget_source_snapshot(session, scope, identity)
        expected = {ref for ref in snapshot.references if ref.target == target}
        if not isinstance(target, TargetKey) or not expected:
            raise ResourceReferenceInvalidError(reason="legacy_evidence_original_mismatch")
        source = snapshot.source_key
        model = BusinessResourceReference
        statement = select(*(getattr(model, field.name) for field in fields(ReferenceReadRow))).where(
            model.tenant_id == source.tenant_id,
            model.source_type == source.source_type.value,
            model.source_id == source.source_id,
            model.source_version == source.source_version,
            model.target_type == target.target_type.value,
            model.target_id == target.target_id,
        )
        with session.no_autoflush, bypass_tenant_filter():
            rows = tuple(ReferenceReadRow(**row._mapping) for row in await session.execute(statement))
        actual = {ReferenceSpec(row.slot_key, TargetKey(row.target_type, row.target_id)) for row in rows}
        if actual != expected or len({(row.target_tenant_id, row.target_space_id) for row in rows}) != 1:
            raise ResourceReferenceInvalidError(reason="legacy_evidence_original_mismatch")
        # Pure validators are shared with the existing write evidence adapter;
        # its current-tenant SQL loaders are deliberately not called here.
        KnowledgeLegacyEvidenceRepository._check_original(rows, source, run_id, evidence_key)
        ledger = KnowledgeUnificationRun
        with session.no_autoflush, bypass_tenant_filter():
            run = (
                await session.execute(
                    select(
                        ledger.tenant_id,
                        ledger.run_id,
                        ledger.origin,
                        ledger.phase,
                        ledger.baseline_hash,
                        ledger.plan_hash,
                        ledger.baseline_ref,
                        ledger.plan_ref,
                    ).where(ledger.tenant_id == source.tenant_id, ledger.run_id == run_id)
                )
            ).one_or_none()
        await self.verifier.aget_source_snapshot(session, scope, identity)
        return KnowledgeLegacyEvidenceRepository._facts(run, source, run_id, evidence_key)
