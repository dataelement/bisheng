"""Read-only execution and inspection coordination over issued source scopes."""

from types import MappingProxyType

from bisheng.common.errcode.knowledge import (
    ResourceReferenceInvalidError,
)
from bisheng.resource_reference.application.contracts import SourceType
from bisheng.resource_reference.application.error_details import snapshot_reference_errors
from bisheng.resource_reference.application.source_contracts import (
    ModelDefaultSlotReadResult,
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
    def _require_valid(facts, snapshot):
        if any(not fact.is_valid for fact in facts):
            raise ResourceReferenceInvalidError(
                reason="reference_target_invalid", reference_errors=snapshot_reference_errors(snapshot, facts)
            )

    async def _source(self, session, scope, identity, *, purpose, slots=None):
        snapshot = await self.verifier.aget_source_snapshot(session, scope, identity)
        if scope.purpose != purpose:
            raise ResourceReferenceInvalidError(reason="reference_read_purpose_mismatch")
        facts = await self.verifier._ainspect_targets(session, scope, identity)
        await self.verifier.arevalidate_scope(session, scope, identity)
        if purpose == "execute":
            if snapshot.invalid_reason is not None:
                raise ResourceReferenceInvalidError(reason=snapshot.invalid_reason)
            if snapshot.source_key.source_type != SourceType.HOSTED_APP_VERSION:
                self._require_valid(facts, snapshot)
        if slots is not None:
            return ModelDefaultSlotReadResult(snapshot, facts, slots)
        return SourceReferenceReadResult(snapshot, facts)

    async def ainspect_source(self, session, scope, identity):
        return await self._source(session, scope, identity, purpose="inspect")

    async def arequire_source_valid(self, session, scope, identity):
        return await self._source(session, scope, identity, purpose="execute")

    async def ainspect_transient(self, session, scope, identity):
        snapshot = await self.verifier.aget_transient_snapshot(session, scope, identity)
        facts = await self.verifier._ainspect_targets(session, scope, identity)
        await self.verifier.arevalidate_transient_scope(session, scope, identity)
        return TransientReferenceReadResult(snapshot, facts)

    async def arequire_transient_valid(self, session, scope, identity):
        result = await self.ainspect_transient(session, scope, identity)
        self._require_valid(result.target_states, result.snapshot)
        return result

    def _source_sync(self, session, scope, identity, *, purpose, slots=None):
        snapshot = self.verifier.get_source_snapshot(session, scope, identity)
        if scope.purpose != purpose:
            raise ResourceReferenceInvalidError(reason="reference_read_purpose_mismatch")
        facts = self.verifier._inspect_targets(session, scope, identity)
        self.verifier.revalidate_scope(session, scope, identity)
        if purpose == "execute":
            if snapshot.invalid_reason is not None:
                raise ResourceReferenceInvalidError(reason=snapshot.invalid_reason)
            if snapshot.source_key.source_type != SourceType.HOSTED_APP_VERSION:
                self._require_valid(facts, snapshot)
        if slots is not None:
            return ModelDefaultSlotReadResult(snapshot, facts, slots)
        return SourceReferenceReadResult(snapshot, facts)

    def inspect_source(self, session, scope, identity):
        return self._source_sync(session, scope, identity, purpose="inspect")

    def require_source_valid(self, session, scope, identity):
        return self._source_sync(session, scope, identity, purpose="execute")

    def require_default_slots_valid(self, session, scope, identity, slots):
        self.verifier.select_default_slots(session, scope, identity, slots)
        return self._source_sync(session, scope, identity, purpose="execute", slots=slots)

    async def arequire_default_slots_valid(self, session, scope, identity, slots):
        await self.verifier.aselect_default_slots(session, scope, identity, slots)
        return await self._source(session, scope, identity, purpose="execute", slots=slots)
