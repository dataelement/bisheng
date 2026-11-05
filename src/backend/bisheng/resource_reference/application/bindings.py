"""Atomic source binding protocol, explicitly injected with target Owners.

The business Owner holds the real business root lock before handing over its
transaction-bound context. This module never opens or commits a transaction.
"""

from collections.abc import Mapping
from types import MappingProxyType

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.resource_reference.application.contracts import (
    BindingReplaceResult,
    LegacyEvidence,
    ReferenceSpec,
    ReferenceState,
    SourceKey,
    TargetKey,
    TargetType,
    VerifiedReferenceSet,
    reference_set_digest,
)
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository


class ReferenceBindings:
    def __init__(self, repository: ReferenceRepository, owners: Mapping[TargetType, object]):
        self.repository = repository
        self.owners = MappingProxyType({TargetType(key): value for key, value in owners.items()})
        if any(self.owners.get(key) is not owner for key, owner in repository.owners.items()):
            raise ValueError("binding and storage target Owner registrations must match")

    def _check_context(self, session, source_key, references, effective):
        self.repository.assert_source_tenant(source_key)
        if not isinstance(references, VerifiedReferenceSet) or not isinstance(effective, bool):
            raise ResourceReferenceInvalidError(reason="verified_reference_set_required")
        if not effective and references.references:
            raise ResourceReferenceInvalidError(reason="ineffective_source_has_references")
        context = references.context
        if context.source_key != source_key:
            raise ResourceReferenceInvalidError(reason="reference_source_mismatch")
        try:
            context.transaction.assert_current(session)
            for receipt in context.receipts:
                receipt.transaction.assert_current(session)
                if (
                    receipt.source_key != source_key
                    or self.owners.get(receipt.target.key.target_type) is not receipt.issuer
                ):
                    raise ValueError("reference receipt issuer or source does not match")
        except (TypeError, ValueError) as exc:
            raise ResourceReferenceInvalidError(reason="reference_receipt_invalid") from exc

    def _prepare(self, key, expected_revision, new_revision, verified, effective, root, current, old):
        context = verified.context
        root_revision = root.source_revision if root is not None else 0
        if (
            context.expected_root_revision != context.locked_root_revision
            or root_revision != context.expected_root_revision
        ):
            raise ResourceReferenceInvalidError(reason="root_revision_conflict")
        self.repository._check_revision(current, expected_revision, new_revision)
        old_specs = tuple(ReferenceSpec(row.slot_key, TargetKey(row.target_type, row.target_id)) for row in old)
        old_digest = reference_set_digest(old_specs)
        if current is not None and (not current.ready or current.record_kind != "source"):
            raise ReferenceCoverageNotReadyError(reason="source_not_ready")
        if (current is None and old) or (current is not None and current.digest != old_digest):
            raise ReferenceCoverageNotReadyError(reason="source_set_inconsistent")
        if any(row.source_revision != current.source_revision for row in old):
            raise ReferenceCoverageNotReadyError(reason="source_revision_inconsistent")
        if old_digest != context.old_references_digest:
            raise KnowledgeOperationPlanConflictError(reason="reference_lock_plan_changed")
        expected_targets = {ref.target for ref in old_specs + verified.references}
        if expected_targets != set(context.locked_targets):
            raise KnowledgeOperationPlanConflictError(reason="reference_lock_plan_changed")
        receipts = {receipt.target.key: receipt.target for receipt in context.receipts}
        previous = {(row.slot_key, row.target_type, row.target_id): row for row in old}
        # Removed targets need the same original evidence checks as retained
        # ones. Otherwise an unrelated legacy marker could launder a missing
        # old target merely by clearing that slot from the new configuration.
        for original in old:
            target = receipts[TargetKey(original.target_type, original.target_id)]
            if (
                original.target_tenant_id is not None
                and target.target_tenant_id is not None
                and original.target_tenant_id != target.target_tenant_id
            ):
                raise ResourceReferenceInvalidError(reason="target_owner_changed")
            if isinstance(target.evidence, LegacyEvidence):
                if (original.legacy_invalid_reason, original.legacy_run_id, original.legacy_evidence_key) != (
                    "target_missing",
                    target.evidence.run_id,
                    target.evidence.evidence_key,
                ):
                    raise ResourceReferenceInvalidError(reason="legacy_evidence_mismatch")
            elif original.legacy_invalid_reason is not None:
                raise ResourceReferenceInvalidError(reason="legacy_target_reappeared")
        rows, retained_invalid = [], 0
        for ref in verified.references:
            target = receipts[ref.target]
            identity = (ref.slot_key, ref.target.target_type.value, ref.target.target_id)
            original = previous.get(identity)
            if target.state != ReferenceState.VALID:
                if original is None:
                    raise ResourceReferenceInvalidError(reason="new_invalid_reference")
                retained_invalid += 1
                if isinstance(target.evidence, LegacyEvidence):
                    if (original.legacy_invalid_reason, original.legacy_run_id, original.legacy_evidence_key) != (
                        "target_missing",
                        target.evidence.run_id,
                        target.evidence.evidence_key,
                    ):
                        raise ResourceReferenceInvalidError(reason="legacy_evidence_mismatch")
                elif original.legacy_invalid_reason is not None:
                    raise ResourceReferenceInvalidError(reason="legacy_evidence_mismatch")
            elif original is not None and original.legacy_invalid_reason is not None:
                raise ResourceReferenceInvalidError(reason="legacy_target_reappeared")
            legacy = target.evidence if isinstance(target.evidence, LegacyEvidence) else None
            rows.append(
                BusinessResourceReference(
                    tenant_id=key.tenant_id,
                    source_type=key.source_type.value,
                    source_id=key.source_id,
                    source_version=key.source_version,
                    slot_key=ref.slot_key,
                    target_type=ref.target.target_type.value,
                    target_id=ref.target.target_id,
                    target_tenant_id=target.target_tenant_id
                    if target.target_tenant_id is not None
                    else original.target_tenant_id,
                    target_space_id=target.target_space_id
                    if target.target_space_id is not None
                    else (original.target_space_id if original else None),
                    source_revision=new_revision,
                    legacy_invalid_reason="target_missing" if legacy else None,
                    legacy_run_id=legacy.run_id if legacy else None,
                    legacy_evidence_key=legacy.evidence_key if legacy else None,
                )
            )
        new_identities = {(row.slot_key, row.target_type, row.target_id) for row in rows}
        result = BindingReplaceResult(
            key,
            new_revision,
            root_revision + 1,
            verified.digest,
            len(new_identities - previous.keys()),
            len(previous.keys() - new_identities),
            retained_invalid,
        )
        return tuple(rows), result

    def replace_source_bindings(
        self,
        session: Session,
        source_key: SourceKey,
        expected_revision: int | None,
        new_revision: int,
        references: VerifiedReferenceSet,
        effective: bool,
    ) -> BindingReplaceResult:
        self._check_context(session, source_key, references, effective)
        root = self.repository.get_root_guard(session, source_key, for_update=True)
        current = self.repository.get_source_set(session, source_key, for_update=True)
        old = self.repository.list_source_references(session, source_key, for_update=True)
        rows, result = self._prepare(
            source_key, expected_revision, new_revision, references, effective, root, current, old
        )
        self.repository.advance_root_guard(
            session,
            source_key,
            expected_revision=references.context.expected_root_revision,
            new_revision=result.root_revision,
        )
        self.repository.replace_source_set(
            session,
            source_key,
            expected_revision=expected_revision,
            new_revision=new_revision,
            references=rows,
            extractor_version=references.extractor_version,
            digest=references.digest,
            effective=effective,
        )
        return result

    async def areplace_source_bindings(
        self,
        session: AsyncSession,
        source_key: SourceKey,
        expected_revision: int | None,
        new_revision: int,
        references: VerifiedReferenceSet,
        effective: bool,
    ) -> BindingReplaceResult:
        self._check_context(session, source_key, references, effective)
        root = await self.repository.aget_root_guard(session, source_key, for_update=True)
        current = await self.repository.aget_source_set(session, source_key, for_update=True)
        old = await self.repository.alist_source_references(session, source_key, for_update=True)
        rows, result = self._prepare(
            source_key, expected_revision, new_revision, references, effective, root, current, old
        )
        await self.repository.aadvance_root_guard(
            session,
            source_key,
            expected_revision=references.context.expected_root_revision,
            new_revision=result.root_revision,
        )
        await self.repository.areplace_source_set(
            session,
            source_key,
            expected_revision=expected_revision,
            new_revision=new_revision,
            references=rows,
            extractor_version=references.extractor_version,
            digest=references.digest,
            effective=effective,
        )
        return result
