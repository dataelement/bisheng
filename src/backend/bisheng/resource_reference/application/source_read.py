"""Read-only execution and inspection coordination over issued source scopes."""

from types import MappingProxyType

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.resource_reference.application.contracts import ReferenceSpec, TargetKey, reference_set_digest
from bisheng.resource_reference.application.source_contracts import (
    SourceReferenceReadResult,
    TransientReferenceReadResult,
)
from bisheng.resource_reference.application.source_verification import SourceReadVerifier
from bisheng.resource_reference.domain.repositories.source_read_repository import SourceReadRepository


class ReferenceSourceReadRuntime:
    def __init__(self, verifier: SourceReadVerifier, repository: SourceReadRepository, target_owners):
        if not isinstance(verifier, SourceReadVerifier) or repository.verifier is not verifier:
            raise ValueError("source reads must share the same private issuance authority")
        self.verifier = verifier
        self.repository = repository
        self.target_owners = MappingProxyType(dict(target_owners))
        verifier._install_target_owners(target_owners)

    @staticmethod
    def _index(index, snapshot, *, execute):
        root, source, rows = index.root, index.source, index.references
        if root is None:
            raise ReferenceCoverageNotReadyError(reason="source_root_guard_missing")
        if root.record_kind != "root_guard" or root.ready or root.effective or root.source_revision <= 0:
            raise ReferenceCoverageNotReadyError(reason="source_root_guard_inconsistent")
        if source is None:
            raise ReferenceCoverageNotReadyError(reason="source_not_indexed")
        try:
            references = tuple(ReferenceSpec(row.slot_key, TargetKey(row.target_type, row.target_id)) for row in rows)
            digest = reference_set_digest(references)
        except (TypeError, ValueError) as exc:
            raise ReferenceCoverageNotReadyError(reason="source_set_inconsistent") from exc
        if (
            not source.ready
            or source.record_kind != "source"
            or source.extractor_version != snapshot.extractor_version
            or source.digest != digest
            or any(row.source_revision != source.source_revision for row in rows)
        ):
            raise ReferenceCoverageNotReadyError(reason="source_set_inconsistent")
        if digest != reference_set_digest(snapshot.references):
            raise ReferenceCoverageNotReadyError(reason="source_configuration_drift")
        if execute and not source.effective:
            raise ResourceReferenceInvalidError(reason="reference_source_inactive")

    @staticmethod
    def _require_valid(facts):
        if any(not fact.is_valid for fact in facts):
            raise ResourceReferenceInvalidError(reason="reference_target_invalid")

    async def _source(self, session, scope, identity, *, purpose):
        snapshot = await self.verifier.aget_source_snapshot(session, scope, identity)
        if scope.purpose != purpose:
            raise ResourceReferenceInvalidError(reason="reference_read_purpose_mismatch")
        candidate = await self.repository.aread_source(session, scope, identity)
        self._index(candidate, snapshot, execute=purpose == "execute")
        facts = await self.verifier._ainspect_targets(session, scope, identity)
        await self.verifier.arevalidate_scope(session, scope, identity)
        current = await self.repository.aread_source(session, scope, identity, for_update=True)
        self._index(current, snapshot, execute=purpose == "execute")
        if candidate != current:
            raise KnowledgeOperationPlanConflictError(reason="reference_read_index_changed")
        if purpose == "execute":
            if snapshot.invalid_reason is not None:
                raise ResourceReferenceInvalidError(reason=snapshot.invalid_reason)
            self._require_valid(facts)
        return SourceReferenceReadResult(snapshot, facts, current.source.source_revision, current.root.source_revision)

    async def ainspect_source(self, session, scope, identity):
        return await self._source(session, scope, identity, purpose="inspect")

    async def arequire_source_valid(self, session, scope, identity):
        return await self._source(session, scope, identity, purpose="execute")

    async def arequire_transient_valid(self, session, scope, identity):
        snapshot = await self.verifier.aget_transient_snapshot(session, scope, identity)
        facts = await self.verifier._ainspect_targets(session, scope, identity)
        await self.verifier.arevalidate_transient_scope(session, scope, identity)
        self._require_valid(facts)
        return TransientReferenceReadResult(snapshot, facts)

    def _source_sync(self, session, scope, identity, *, purpose):
        snapshot = self.verifier.get_source_snapshot(session, scope, identity)
        if scope.purpose != purpose:
            raise ResourceReferenceInvalidError(reason="reference_read_purpose_mismatch")
        candidate = self.repository.read_source(session, scope, identity)
        self._index(candidate, snapshot, execute=purpose == "execute")
        facts = self.verifier._inspect_targets(session, scope, identity)
        self.verifier.revalidate_scope(session, scope, identity)
        current = self.repository.read_source(session, scope, identity, for_update=True)
        self._index(current, snapshot, execute=purpose == "execute")
        if candidate != current:
            raise KnowledgeOperationPlanConflictError(reason="reference_read_index_changed")
        if purpose == "execute":
            if snapshot.invalid_reason is not None:
                raise ResourceReferenceInvalidError(reason=snapshot.invalid_reason)
            self._require_valid(facts)
        return SourceReferenceReadResult(snapshot, facts, current.source.source_revision, current.root.source_revision)

    def inspect_source(self, session, scope, identity):
        return self._source_sync(session, scope, identity, purpose="inspect")

    def require_source_valid(self, session, scope, identity):
        return self._source_sync(session, scope, identity, purpose="execute")
