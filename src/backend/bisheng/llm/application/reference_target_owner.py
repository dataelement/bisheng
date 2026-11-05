"""Business-backed model target Owner and existing Root sharing adapter."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Protocol

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.core.database.tenant_filter import _resolve_tenant_id
from bisheng.llm.domain.repositories.reference_target_repository import ModelReferenceTargetRepository
from bisheng.permission.application import PermissionSubject, get_permission_relation_api
from bisheng.resource_reference.application.contracts import LegacyEvidence, TargetLockReceipt, TransactionIdentity
from bisheng.resource_reference.application.target_state import resolve_target_state

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import Session

    from bisheng.resource_reference.application.evidence import LegacyReferenceEvidencePort


class ModelReferenceSharePort(Protocol):
    def get_shared_server_ids(
        self, session: Session, tenant_id: int, server_ids: tuple[int, ...]
    ) -> frozenset[int]: ...
    async def aget_shared_server_ids(
        self, session: AsyncSession, tenant_id: int, server_ids: tuple[int, ...]
    ) -> frozenset[int]: ...


class DefaultModelReferenceSharing:
    def __init__(self, repository: ModelReferenceTargetRepository):
        self.repository = repository

    def get_shared_server_ids(self, session, tenant_id, server_ids):
        # No event-loop nesting or blocking permission transport in sync callers.
        # Maintenance may inject a native, trusted frozen-snapshot implementation.
        raise ReferenceCoverageNotReadyError(reason="model_reference_sync_share_unavailable")

    async def aget_shared_server_ids(self, session, tenant_id, server_ids):
        permissions = await get_permission_relation_api()
        shared = await permissions.list_resource_ids(
            subject=PermissionSubject("tenant", str(tenant_id)), relation="shared_with", resource_type="llm_server"
        )
        shared_ids = {
            int(value)
            for value in shared
            if isinstance(value, str) and value.isascii() and value.isdecimal() and int(value) > 0
        }
        inherited = await self.repository.aget_inherited_default_server_ids(session, tenant_id)
        return frozenset(server_ids) & (shared_ids | inherited)


class ModelReferenceTargetOwner:
    def __init__(
        self,
        repository: ModelReferenceTargetRepository | None = None,
        *,
        legacy_evidence: LegacyReferenceEvidencePort | None = None,
        sharing: ModelReferenceSharePort | None = None,
    ):
        self.repository = repository if repository is not None else ModelReferenceTargetRepository()
        self.legacy_evidence = legacy_evidence
        self.sharing = sharing if sharing is not None else DefaultModelReferenceSharing(self.repository)

    def prelock_targets(self, session, target_keys, source_keys) -> None:
        TransactionIdentity.capture(session)
        self.repository.prelock_targets(session, target_keys, source_keys)

    async def aprelock_targets(self, session, target_keys, source_keys) -> None:
        TransactionIdentity.capture(session)
        await self.repository.aprelock_targets(session, target_keys, source_keys)

    @staticmethod
    def _shared_servers(observations):
        tenant_id = _resolve_tenant_id()
        return tuple(
            sorted(
                {
                    int(row.model_server_id)
                    for row in observations
                    if row.exists and row.deletion is None and row.target_tenant_id != tenant_id
                }
            )
        )

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
            model_server_id=observation.model_server_id,
            deletion_evidence=observation.deletion,
            legacy_evidence=legacy,
            original_reference=observation.original,
            source_key=source_key,
        )
        return TargetLockReceipt(source_key, target, TransactionIdentity.capture(session), issuer)

    @staticmethod
    def _check_sharing(requested, allowed):
        if not isinstance(allowed, frozenset) or any(type(value) is not int or value <= 0 for value in allowed):
            raise ResourceReferenceInvalidError(reason="model_reference_target_unavailable")
        return allowed & frozenset(requested)

    @staticmethod
    def _new_binding_allowed(observation, source_key, allowed):
        if (
            not observation.exists
            or observation.deletion is not None
            or observation.target_tenant_id == _resolve_tenant_id()
            or int(observation.model_server_id) in allowed
        ):
            return True
        # Sharing revocation does not delete a real model. The original
        # source may retain or remove its slots, but cannot authorize any new
        # identity. R2 checks each slot against that same source/version.
        original = observation.original
        if (
            source_key is not None
            and original is not None
            and (
                original.tenant_id,
                original.source_type,
                original.source_id,
                original.source_version,
                original.target_type,
                original.target_id,
            )
            == (
                source_key.tenant_id,
                source_key.source_type.value,
                source_key.source_id,
                source_key.source_version,
                observation.key.target_type.value,
                observation.key.target_id,
            )
            and original.target_tenant_id == observation.target_tenant_id
            and original.legacy_invalid_reason is None
        ):
            return False
        raise ResourceReferenceInvalidError(reason="model_reference_target_unavailable")

    def lock_and_verify(self, session, target_keys, source_key, operation):
        TransactionIdentity.capture(session)
        observations = self.repository.lock_targets(session, target_keys, source_key, operation)
        shared = self._shared_servers(observations)
        allowed = frozenset()
        if shared:
            allowed = self._check_sharing(
                shared, self.sharing.get_shared_server_ids(session, _resolve_tenant_id(), shared)
            )
        result = []
        for observation in observations:
            eligible = self._new_binding_allowed(observation, source_key, allowed)
            request = self._legacy_request(observation)
            legacy = self.legacy_evidence.resolve(session, source_key, observation.key, **request) if request else None
            receipt = self._receipt(session, source_key, observation, legacy, self)
            if not eligible:
                receipt = replace(receipt, target=replace(receipt.target, new_binding_allowed=False))
            result.append(receipt)
        return tuple(result)

    async def alock_and_verify(self, session, target_keys, source_key, operation):
        TransactionIdentity.capture(session)
        observations = await self.repository.alock_targets(session, target_keys, source_key, operation)
        shared = self._shared_servers(observations)
        allowed = frozenset()
        if shared:
            allowed = self._check_sharing(
                shared, await self.sharing.aget_shared_server_ids(session, _resolve_tenant_id(), shared)
            )
        result = []
        for observation in observations:
            eligible = self._new_binding_allowed(observation, source_key, allowed)
            request = self._legacy_request(observation)
            legacy = (
                await self.legacy_evidence.aresolve(session, source_key, observation.key, **request)
                if request
                else None
            )
            receipt = self._receipt(session, source_key, observation, legacy, self)
            if not eligible:
                receipt = replace(receipt, target=replace(receipt.target, new_binding_allowed=False))
            result.append(receipt)
        return tuple(result)
