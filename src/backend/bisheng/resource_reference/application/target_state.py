"""Business-neutral target state resolution from Owner-verified observations."""

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.resource_reference.application.contracts import (
    DeletionEvidence,
    LegacyEvidence,
    ReferenceState,
    SourceKey,
    TargetDeleteStage,
    TargetKey,
    TargetType,
    VerifiedReferenceTarget,
    canonical_target_id,
    is_preserved_foreign_model_reference,
    is_preserved_foreign_space_reference,
)
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference


def resolve_target_state(
    target: TargetKey,
    *,
    exists: bool,
    target_tenant_id: int | None,
    target_revision: str,
    target_space_id: str | None = None,
    model_server_id: str | None = None,
    deletion_evidence: DeletionEvidence | None = None,
    ancestor_deletion: DeletionEvidence | None = None,
    legacy_evidence: LegacyEvidence | None = None,
    original_reference: BusinessResourceReference | None = None,
    source_key: SourceKey | None = None,
) -> VerifiedReferenceTarget:
    """No name lookup, implicit target tenant inference or missing-row fallback.

    ``exists`` means a currently live business target, not merely a retained
    soft-deleted row. The Owner loads observations and evidence in its trusted
    scope; this pure resolver never imports a business Service or its ORM.
    """
    if not isinstance(exists, bool) or not isinstance(target, TargetKey):
        raise ResourceReferenceInvalidError(reason="reference_target_observation_invalid")
    if target_space_id is not None:
        target_space_id = canonical_target_id(target_space_id)
    if original_reference is not None:
        if TargetKey(original_reference.target_type, original_reference.target_id) != target:
            raise ResourceReferenceInvalidError(reason="reference_original_target_mismatch")
        if (
            original_reference.target_tenant_id is not None
            and target_tenant_id is not None
            and original_reference.target_tenant_id != target_tenant_id
        ):
            raise ResourceReferenceInvalidError(reason="reference_target_owner_changed")
    # A legacy file was already absent before a later space deletion. Keep its
    # original classification rather than inventing a new force-delete cause.
    if ancestor_deletion is not None and deletion_evidence is None and legacy_evidence is None:
        if (
            target.target_type != TargetType.KNOWLEDGE_FILE
            or target_space_id is None
            or ancestor_deletion.target != TargetKey(TargetType.KNOWLEDGE_SPACE, target_space_id)
            or (target_tenant_id is not None and ancestor_deletion.target_tenant_id != target_tenant_id)
            or (not exists and original_reference is None)
            or (original_reference is not None and original_reference.target_space_id != target_space_id)
        ):
            raise ResourceReferenceInvalidError(reason="reference_ancestor_evidence_mismatch")
        deletion_evidence = DeletionEvidence(
            ancestor_deletion.operation_id, target, ancestor_deletion.target_tenant_id, ancestor_deletion.stage
        )
    if deletion_evidence is not None:
        if (
            legacy_evidence is not None
            or (original_reference is not None and original_reference.legacy_invalid_reason is not None)
            or deletion_evidence.target != target
            or (target_tenant_id is not None and deletion_evidence.target_tenant_id != target_tenant_id)
        ):
            raise ResourceReferenceInvalidError(reason="reference_deletion_evidence_mismatch")
        target_tenant_id = deletion_evidence.target_tenant_id
        if deletion_evidence.stage == TargetDeleteStage.DELETED and exists:
            raise ResourceReferenceInvalidError(reason="reference_deleted_target_reappeared")
        state = (
            ReferenceState.DELETING
            if deletion_evidence.stage == TargetDeleteStage.DELETING
            else ReferenceState.INVALID_DELETED
        )
        evidence = deletion_evidence
    elif legacy_evidence is not None:
        if exists:
            raise ResourceReferenceInvalidError(reason="reference_legacy_target_reappeared")
        if (
            original_reference is None
            or source_key is None
            or (
                original_reference.tenant_id,
                original_reference.source_type,
                original_reference.source_id,
                original_reference.source_version,
                original_reference.legacy_invalid_reason,
                original_reference.legacy_run_id,
                original_reference.legacy_evidence_key,
            )
            != (
                source_key.tenant_id,
                source_key.source_type.value,
                source_key.source_id,
                source_key.source_version,
                "target_missing",
                legacy_evidence.run_id,
                legacy_evidence.evidence_key,
            )
        ):
            raise ResourceReferenceInvalidError(reason="reference_legacy_evidence_mismatch")
        if target_tenant_id is None:
            target_tenant_id = original_reference.target_tenant_id
        state, evidence = ReferenceState.INVALID_LEGACY, legacy_evidence
    elif exists:
        if original_reference is not None and original_reference.legacy_invalid_reason is not None:
            raise ResourceReferenceInvalidError(reason="reference_legacy_target_reappeared")
        state = (
            ReferenceState.INVALID_SCOPE
            if is_preserved_foreign_model_reference(
                original_reference, source_key=source_key, target=target, target_tenant_id=target_tenant_id
            )
            or is_preserved_foreign_space_reference(
                original_reference, source_key=source_key, target=target, target_tenant_id=target_tenant_id
            )
            else ReferenceState.VALID
        )
        evidence = None
    else:
        raise ResourceReferenceInvalidError(reason="reference_target_unexplained_missing")
    try:
        return VerifiedReferenceTarget(
            target,
            target_tenant_id,
            target_space_id,
            model_server_id,
            state,
            target_revision,
            evidence,
            new_binding_allowed=state != ReferenceState.INVALID_SCOPE,
        )
    except (TypeError, ValueError) as exc:
        raise ResourceReferenceInvalidError(reason="reference_target_observation_invalid") from exc
