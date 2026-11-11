"""Knowledge lifecycle facts for saved source reads and unsaved previews."""

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.knowledge.domain.repositories.source_read_target_repository import KnowledgeSourceReadTargetRepository
from bisheng.resource_reference.application.source_contracts import ReferenceTargetReadFact
from bisheng.resource_reference.application.target_state import resolve_target_state


class KnowledgeSourceReadTargetOwner:
    def __init__(self, verifier, repository=None, *, legacy_evidence=None):
        self.verifier = verifier
        self.repository = repository if repository is not None else KnowledgeSourceReadTargetRepository(verifier)
        if self.repository.verifier is not verifier:
            raise ValueError("knowledge read facts require the same source authority")
        self.legacy_evidence = legacy_evidence

    async def _inspect(self, session, scope, target_keys, identity, *, transient):
        snapshot = await (self.verifier.aget_transient_snapshot if transient else self.verifier.aget_source_snapshot)(
            session, scope, identity
        )
        observations = await self.repository.alock_targets(
            session, scope, target_keys, identity=identity, transient=transient
        )
        result = []
        for row in observations:
            legacy = None
            original = row.original
            if original is not None and original.legacy_invalid_reason is not None:
                if (
                    original.legacy_invalid_reason != "target_missing"
                    or not original.legacy_run_id
                    or not original.legacy_evidence_key
                ):
                    raise ResourceReferenceInvalidError(reason="reference_legacy_evidence_mismatch")
                if self.legacy_evidence is None:
                    raise ReferenceCoverageNotReadyError(reason="reference_legacy_evidence_unavailable")
                legacy = await self.legacy_evidence.aresolve(
                    session,
                    scope,
                    row.key,
                    run_id=original.legacy_run_id,
                    evidence_key=original.legacy_evidence_key,
                    identity=identity,
                )
            target = resolve_target_state(
                row.key,
                exists=row.exists,
                target_tenant_id=row.target_tenant_id,
                target_space_id=row.target_space_id,
                target_revision="source-read-v1",
                deletion_evidence=row.deletion,
                ancestor_deletion=row.ancestor_deletion,
                legacy_evidence=legacy,
                original_reference=original,
                source_key=None if transient else snapshot.source_key,
            )
            result.append(
                ReferenceTargetReadFact(
                    target.key,
                    target.state,
                    target.state == "valid",
                    target.target_tenant_id,
                    int(target.target_space_id) if target.target_space_id is not None else None,
                )
            )
        await (self.verifier.aget_transient_snapshot if transient else self.verifier.aget_source_snapshot)(
            session, scope, identity
        )
        return tuple(result)

    async def ainspect_source_targets(self, session, scope, target_keys, *, identity):
        return await self._inspect(session, scope, target_keys, identity, transient=False)

    async def ainspect_transient_targets(self, session, scope, target_keys, *, identity):
        return await self._inspect(session, scope, target_keys, identity, transient=True)
