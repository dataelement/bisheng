"""Knowledge target facts; resource authorization belongs to the source use case."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.knowledge.domain.repositories.reference_target_repository import KnowledgeReferenceTargetRepository
from bisheng.resource_reference.application.contracts import LegacyEvidence, TargetLockReceipt, TransactionIdentity
from bisheng.resource_reference.application.target_state import resolve_target_state

if TYPE_CHECKING:
    from bisheng.resource_reference.application.evidence import LegacyReferenceEvidencePort


class KnowledgeReferenceTargetOwner:
    def __init__(
        self,
        repository: KnowledgeReferenceTargetRepository | None = None,
        *,
        legacy_evidence: LegacyReferenceEvidencePort | None = None,
    ):
        self.repository = repository if repository is not None else KnowledgeReferenceTargetRepository()
        self.legacy_evidence = legacy_evidence

    def _legacy_request(self, observation):
        original = observation.original
        if original is None or original.legacy_invalid_reason is None:
            return None
        if (
            original.legacy_invalid_reason != "target_missing"
            or not original.legacy_run_id
            or not original.legacy_evidence_key
        ):
            raise ResourceReferenceInvalidError(reason="reference_legacy_evidence_mismatch")
        if self.legacy_evidence is None:
            raise ReferenceCoverageNotReadyError(reason="reference_legacy_evidence_unavailable")
        return {"run_id": original.legacy_run_id, "evidence_key": original.legacy_evidence_key}

    @staticmethod
    def _receipt(session, source_key, observation, legacy, issuer):
        if legacy is not None and (
            not isinstance(legacy, LegacyEvidence)
            or (legacy.run_id, legacy.evidence_key)
            != (observation.original.legacy_run_id, observation.original.legacy_evidence_key)
        ):
            raise ResourceReferenceInvalidError(reason="reference_legacy_evidence_mismatch")
        target = resolve_target_state(
            observation.key,
            exists=observation.exists,
            target_tenant_id=observation.target_tenant_id,
            target_revision=observation.target_revision,
            target_space_id=observation.target_space_id,
            deletion_evidence=observation.deletion,
            ancestor_deletion=observation.ancestor_deletion,
            legacy_evidence=legacy,
            original_reference=observation.original,
            source_key=source_key,
        )
        return TargetLockReceipt(source_key, target, TransactionIdentity.capture(session), issuer)

    def lock_and_verify(self, session, target_keys, source_key, operation):
        TransactionIdentity.capture(session)
        result = []
        for observation in self.repository.lock_targets(session, target_keys, source_key, operation):
            request = self._legacy_request(observation)
            legacy = self.legacy_evidence.resolve(session, source_key, observation.key, **request) if request else None
            result.append(self._receipt(session, source_key, observation, legacy, self))
        return tuple(result)

    async def alock_and_verify(self, session, target_keys, source_key, operation):
        TransactionIdentity.capture(session)
        result = []
        for observation in await self.repository.alock_targets(session, target_keys, source_key, operation):
            request = self._legacy_request(observation)
            legacy = (
                await self.legacy_evidence.aresolve(session, source_key, observation.key, **request)
                if request
                else None
            )
            result.append(self._receipt(session, source_key, observation, legacy, self))
        return tuple(result)
