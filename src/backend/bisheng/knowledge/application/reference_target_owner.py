"""Knowledge target facts; resource authorization belongs to the source use case."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.knowledge.domain.repositories.move_cutover_repository import MoveCutoverRepository
from bisheng.knowledge.domain.repositories.reference_target_repository import KnowledgeReferenceTargetRepository
from bisheng.resource_reference.application.contracts import (
    LegacyEvidence,
    TargetKey,
    TargetLockReceipt,
    TransactionIdentity,
)
from bisheng.resource_reference.application.target_state import resolve_target_state
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime

if TYPE_CHECKING:
    from bisheng.resource_reference.application.evidence import LegacyReferenceEvidencePort


class KnowledgeReferenceTargetOwner:
    def __init__(
        self,
        repository: KnowledgeReferenceTargetRepository | None = None,
        *,
        legacy_evidence: LegacyReferenceEvidencePort | None = None,
        move_cutover: MoveCutoverRepository | None = None,
    ):
        self.repository = repository if repository is not None else KnowledgeReferenceTargetRepository()
        self.legacy_evidence = legacy_evidence
        if move_cutover is not None and not isinstance(move_cutover, MoveCutoverRepository):
            raise TypeError("move ownership requires the actual cutover issuer")
        self.move_cutover = move_cutover

    async def amove_file_ownership(self, session, *, logical, reference_runtime):
        """Maintain incoming File ownership under the caller's logical SAVEPOINT."""
        if self.move_cutover is None or not isinstance(reference_runtime, ReferenceBindingRuntime):
            raise ResourceReferenceInvalidError(reason="move_reference_owner_unconfigured")
        self.move_cutover.assert_logical_current(logical, session)
        scope = logical._prepared.scope
        transaction = TransactionIdentity.capture(session)
        tenant = scope.tenant_id

        def current():
            transaction.assert_current(session)
            if get_current_tenant_id() != tenant or is_tenant_filter_bypassed():
                raise ResourceReferenceInvalidError(reason="move_reference_context_changed")

        current()
        native = getattr(session, "sync_session", None)
        if native is None or native.new or native.dirty or native.deleted:
            raise ResourceReferenceInvalidError(reason="move_reference_pending_changes")
        targets = tuple(TargetKey("knowledge_file", row.file_id) for row in scope.files)
        with session.no_autoflush:
            receipts = await reference_runtime.verifier.averify_owner_targets(session, targets)
            current()
            if any(receipt.target.target_space_id != str(scope.destination_space_id) for receipt in receipts):
                raise ResourceReferenceInvalidError(reason="move_reference_after_changed")
            count = await reference_runtime.arefresh_file_target_ownership(
                session, receipts=receipts, expected_space_id=scope.source_space_id
            )
        current()
        self.move_cutover.assert_logical_current(logical, session)
        return count

    def prelock_targets(self, session, target_keys, source_keys) -> None:
        TransactionIdentity.capture(session)
        self.repository.prelock_targets(session, target_keys, source_keys)

    async def aprelock_targets(self, session, target_keys, source_keys) -> None:
        TransactionIdentity.capture(session)
        await self.repository.aprelock_targets(session, target_keys, source_keys)

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
