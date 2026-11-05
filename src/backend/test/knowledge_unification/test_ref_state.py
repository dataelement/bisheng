"""Target failure evidence and fail-closed reference coverage.

覆盖 AC: AC-89, AC-90, AC-91, AC-93
The ledger adapter belongs to MIG/INT; these cases exercise its strict port.
"""

import pytest
from sqlmodel import Session

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.resource_reference.application.contracts import (
    CoverageStatus,
    DeletionEvidence,
    LegacyEvidence,
    SourceKey,
    SourceType,
    TargetKey,
)
from bisheng.resource_reference.application.target_state import resolve_target_state
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.repositories.coverage_repository import CoverageRepository
from test.knowledge_unification import test_ref_repo as ref_fixtures

engine = ref_fixtures.engine
tenant_events = ref_fixtures.tenant_events


def original(*, target_id="1", target_type="model", space_id=None, legacy=False):
    return BusinessResourceReference(
        tenant_id=101,
        source_type="assistant",
        source_id="a1",
        source_version="current",
        slot_key="model",
        target_type=target_type,
        target_id=target_id,
        target_tenant_id=None if legacy else 101,
        target_space_id=space_id,
        source_revision=1,
        legacy_invalid_reason="target_missing" if legacy else None,
        legacy_run_id="run1" if legacy else None,
        legacy_evidence_key="e1" if legacy else None,
    )


def observe(target=None, **kwargs):
    return resolve_target_state(target or TargetKey("model", "1"), target_revision="r1", **kwargs)


def test_live_deleting_and_deleted_are_distinct():
    key = TargetKey("model", "1")
    assert observe(exists=True, target_tenant_id=101, model_server_id="7").state == "valid"
    assert (
        observe(
            exists=True,
            target_tenant_id=101,
            model_server_id="7",
            deletion_evidence=DeletionEvidence("op1", key, 101, "deleting"),
        ).state
        == "deleting"
    )
    assert (
        observe(
            exists=False, target_tenant_id=101, deletion_evidence=DeletionEvidence("op1", key, 101, "deleted")
        ).state
        == "invalid_deleted"
    )
    with pytest.raises(ResourceReferenceInvalidError):
        observe(
            exists=True,
            target_tenant_id=101,
            model_server_id="7",
            deletion_evidence=DeletionEvidence("op1", key, 101, "deleted"),
        )


def test_legacy_missing_needs_exact_original_source_and_frozen_evidence():
    evidence = LegacyEvidence("run1", "a" * 64, "e1")
    source = SourceKey(101, "assistant", "a1", "current")
    result = observe(
        exists=False,
        target_tenant_id=None,
        source_key=source,
        original_reference=original(legacy=True),
        legacy_evidence=evidence,
    )
    assert result.state == "invalid_legacy" and result.target_tenant_id is None
    for bad in [
        {"source_key": SourceKey(101, "assistant", "another", "current")},
        {"legacy_evidence": LegacyEvidence("other-run", "b" * 64, "e1")},
        {"exists": True, "model_server_id": "7"},
    ]:
        arguments = {
            "exists": False,
            "target_tenant_id": None,
            "source_key": source,
            "original_reference": original(legacy=True),
            "legacy_evidence": evidence,
        }
        with pytest.raises(ResourceReferenceInvalidError):
            observe(**(arguments | bad))


def test_unexplained_missing_or_wrong_target_evidence_is_not_legacy():
    with pytest.raises(ResourceReferenceInvalidError) as raised:
        observe(exists=False, target_tenant_id=None)
    assert raised.value.kwargs["reason"] == "reference_target_unexplained_missing"
    for evidence in [
        DeletionEvidence("op1", TargetKey("model", "2"), 101, "deleted"),
        DeletionEvidence("op1", TargetKey("model", "1"), 202, "deleted"),
    ]:
        with pytest.raises(ResourceReferenceInvalidError):
            observe(exists=False, target_tenant_id=101, deletion_evidence=evidence)


def test_space_tombstone_invalidates_only_a_file_with_verified_membership():
    file = TargetKey("knowledge_file", "9")
    evidence = DeletionEvidence("space-op", TargetKey("knowledge_space", "3"), 101, "deleted")
    result = observe(
        file,
        exists=False,
        target_tenant_id=101,
        target_space_id="3",
        original_reference=original(target_type="knowledge_file", target_id="9", space_id="3"),
        ancestor_deletion=evidence,
    )
    assert result.state == "invalid_deleted" and result.evidence.target == file
    with pytest.raises(ResourceReferenceInvalidError):
        observe(
            file,
            exists=False,
            target_tenant_id=101,
            target_space_id="4",
            original_reference=original(target_type="knowledge_file", target_id="9", space_id="4"),
            ancestor_deletion=evidence,
        )


class LedgerPort:
    def __init__(self, *, missing=None, broken=False, wrong_tenant=False):
        self.missing, self.broken, self.wrong_tenant = missing, broken, wrong_tenant

    def get_status(self, tenant_id, source_type, writer_contract_version):
        if self.broken:
            raise RuntimeError("ledger unavailable")
        return CoverageStatus(
            202 if self.wrong_tenant else tenant_id,
            source_type,
            writer_contract_version,
            source_type != self.missing,
            "source_or_zero_set_missing" if source_type == self.missing else None,
        )

    async def aget_status(self, tenant_id, source_type, writer_contract_version):
        return self.get_status(tenant_id, source_type, writer_contract_version)


def test_coverage_requires_every_source_and_matching_trusted_tenant():
    assert len(CoverageRepository(LedgerPort()).require_ready()) == len(SourceType)
    for port in [
        LedgerPort(missing=SourceType.HOSTED_APP_VERSION),
        LedgerPort(broken=True),
        LedgerPort(wrong_tenant=True),
    ]:
        with pytest.raises(ReferenceCoverageNotReadyError):
            CoverageRepository(port).require_ready()
    with pytest.raises(ReferenceCoverageNotReadyError):
        CoverageRepository(LedgerPort()).require_ready(tenant_id=202)


async def test_async_coverage_does_not_turn_missing_or_error_into_ready():
    assert len(await CoverageRepository(LedgerPort()).arequire_ready()) == len(SourceType)
    with pytest.raises(ReferenceCoverageNotReadyError):
        await CoverageRepository(LedgerPort(missing=SourceType.ASSISTANT)).arequire_ready()


def test_empty_tenant_initializer_must_be_injected_and_keep_same_transaction(engine):
    class EmptyTenantInitializer:
        def initialize_empty_tenant_coverage(self, session, tenant_id, writer_contract_version):
            assert tenant_id == 101 and writer_contract_version == "f118-v1"
            assert session.in_transaction()
            self.called = True

    initializer = EmptyTenantInitializer()
    with Session(engine) as session, session.begin():
        with pytest.raises(ReferenceCoverageNotReadyError):
            CoverageRepository(LedgerPort()).initialize_empty_tenant_coverage(session, 101, "f118-v1")
        repository = CoverageRepository(LedgerPort(), initializer=initializer)
        repository.initialize_empty_tenant_coverage(session, 101, "f118-v1")
        assert initializer.called and session.in_transaction()
        with pytest.raises(ReferenceCoverageNotReadyError):
            repository.initialize_empty_tenant_coverage(session, 202, "f118-v1")
