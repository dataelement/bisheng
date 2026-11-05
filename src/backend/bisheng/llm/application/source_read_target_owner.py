"""Model read facts preserve caller identity and real source sharing policy."""

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.llm.domain.repositories.source_read_target_repository import ModelSourceReadTargetRepository
from bisheng.permission.application import PermissionSubject, get_permission_relation_api
from bisheng.resource_reference.application.source_contracts import ReferenceTargetReadFact
from bisheng.resource_reference.application.target_state import resolve_target_state


class ModelSourceReadTargetOwner:
    def __init__(self, verifier, repository=None, *, legacy_evidence=None, sharing=None):
        self.verifier = verifier
        self.repository = repository if repository is not None else ModelSourceReadTargetRepository(verifier)
        if self.repository.verifier is not verifier:
            raise ValueError("model reads require the same source authority")
        self.legacy_evidence, self.sharing = legacy_evidence, sharing

    async def _shared(self, session, plan):
        requested = tuple(
            sorted(
                {
                    int(row.model_server_id)
                    for row in plan.observations
                    if row.exists and row.deletion is None and row.target_tenant_id != plan.tenant_id
                }
            )
        )
        if not requested:
            return frozenset()
        if self.sharing is not None:
            allowed = await self.sharing.aget_shared_server_ids(session, plan.tenant_id, requested)
            if not isinstance(allowed, frozenset) or any(type(value) is not int or value <= 0 for value in allowed):
                raise ResourceReferenceInvalidError(reason="model_reference_target_unavailable")
            return allowed & frozenset(requested)
        permissions = await get_permission_relation_api()
        ids = await permissions.list_resource_ids(
            subject=PermissionSubject("tenant", str(plan.tenant_id)), relation="shared_with", resource_type="llm_server"
        )
        if any(
            not isinstance(value, str) or not value.isascii() or not value.isdecimal() or int(value) <= 0
            for value in ids
        ):
            raise ResourceReferenceInvalidError(reason="model_reference_target_unavailable")
        return frozenset(requested) & (frozenset(int(value) for value in ids) | plan.inherited_server_ids)

    @staticmethod
    def _eligible(row, tenant_id, allowed, snapshot, transient):
        if (
            not row.exists
            or row.deletion is not None
            or row.target_tenant_id == tenant_id
            or int(row.model_server_id) in allowed
        ):
            return True
        original = row.original
        if (
            not transient
            and original is not None
            and original.legacy_invalid_reason is None
            and original.target_tenant_id == row.target_tenant_id
        ):
            key = snapshot.source_key
            if (
                original.tenant_id,
                original.source_type,
                original.source_id,
                original.source_version,
                original.target_type,
                original.target_id,
            ) == (
                key.tenant_id,
                key.source_type.value,
                key.source_id,
                key.source_version,
                row.key.target_type.value,
                row.key.target_id,
            ):
                return False
        raise ResourceReferenceInvalidError(reason="model_reference_target_unavailable")

    async def _inspect(self, session, scope, target_keys, identity, *, transient):
        get = self.verifier.aget_transient_snapshot if transient else self.verifier.aget_source_snapshot
        snapshot = await get(session, scope, identity)
        plan = await self.repository.alock_targets(session, scope, target_keys, identity=identity, transient=transient)
        allowed = await self._shared(session, plan)
        result = []
        for row in plan.observations:
            eligible = self._eligible(row, plan.tenant_id, allowed, snapshot, transient)
            legacy, original = None, row.original
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
                model_server_id=row.model_server_id,
                target_revision="source-read-v1",
                deletion_evidence=row.deletion,
                legacy_evidence=legacy,
                original_reference=original,
                source_key=None if transient else snapshot.source_key,
            )
            result.append(
                ReferenceTargetReadFact(
                    target.key, target.state, target.state == "valid" and eligible, target.target_tenant_id
                )
            )
        await get(session, scope, identity)
        return tuple(result)

    async def ainspect_source_targets(self, session, scope, target_keys, *, identity):
        return await self._inspect(session, scope, target_keys, identity, transient=False)

    async def ainspect_transient_targets(self, session, scope, target_keys, *, identity):
        return await self._inspect(session, scope, target_keys, identity, transient=True)
