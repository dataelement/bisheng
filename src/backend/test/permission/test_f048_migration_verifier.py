"""D4 verifier contracts for an existing formal F048 migration run."""

from __future__ import annotations

from dataclasses import replace

import pytest

from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.permission.migration.f048_coordinator import MigrationRunState
from bisheng.permission.migration.f048_verifier import (
    F048MigrationVerifier,
    InstancePinEvidence,
    MigrationVerificationEvidence,
)


def _run() -> MigrationRunState:
    return MigrationRunState(
        id=3,
        environment_fingerprint="e" * 64,
        phase="VERIFYING",
        status="RUNNING",
        store_id="store-live",
        source_model_id="legacy",
        target_model_id="new-model",
        source_watermark="wm-1",
        source_checksum="s" * 64,
        target_checksum="t" * 64,
        version=8,
    )


def _evidence(**overrides) -> MigrationVerificationEvidence:
    values = {
        "source_checksum": "s" * 64,
        "expected_target_checksum": "t" * 64,
        "actual_target_checksum": "t" * 64,
        "expected_target_count": 10,
        "actual_target_count": 10,
        "blocker_count": 0,
        "unapproved_manual_count": 0,
        "cross_tenant_count": 0,
        "orphan_count": 0,
        "invalid_parent_count": 0,
        "invalid_owner_count": 0,
        "failed_tuple_count": 0,
        "legacy_tuple_count": 0,
        "legacy_config_count": 0,
        "preserved_tuple_checksum_matches": True,
        "model_checksum_matches": True,
        "semantic_results": {
            "owner": True,
            "mode": True,
            "multiple_sources": True,
            "dashboard": True,
            "download": True,
            "high_risk_check": True,
            "high_risk_list": True,
        },
        "instance_pins": (
            InstancePinEvidence(
                role="api",
                ready=True,
                store_id="store-live",
                model_id="new-model",
                catalog_release_id=9,
            ),
            InstancePinEvidence(
                role="worker",
                ready=True,
                store_id="store-live",
                model_id="new-model",
                catalog_release_id=9,
            ),
        ),
        "visible_source_checksum_matches": True,
        "visible_aggregate_checksum_matches": True,
        "unattributed_visible_count": 0,
        "visible_stream_complete": True,
    }
    values.update(overrides)
    return MigrationVerificationEvidence(**values)


class FakeStore:
    def __init__(self, run=None):
        self.run = run or _run()
        self.ready_checksums = []

    async def aget_run(self, run_id):
        return self.run if run_id == self.run.id else None

    async def amark_ready(self, *, run_id, expected_version, evidence_checksum):
        assert run_id == self.run.id
        assert expected_version == self.run.version
        self.ready_checksums.append(evidence_checksum)
        self.run = replace(
            self.run,
            phase="READY_TO_START",
            status="COMPLETED",
            version=self.run.version + 1,
        )
        return self.run


class FakeEvidenceProvider:
    def __init__(self, evidence):
        self.evidence = evidence
        self.consistency = None

    async def acollect(self, *, run, consistency):
        self.consistency = consistency
        return self.evidence


async def test_verifier_uses_higher_consistency_and_marks_ready():
    store = FakeStore()
    provider = FakeEvidenceProvider(_evidence())
    verifier = F048MigrationVerifier(
        run_store=store,
        evidence_provider=provider,
    )

    result = await verifier.verify(run_id=3)

    assert result.phase == "READY_TO_START"
    assert provider.consistency == "HIGHER_CONSISTENCY"
    assert len(store.ready_checksums[0]) == 64


async def test_verifier_allows_retained_legacy_config_audit_rows():
    store = FakeStore()
    verifier = F048MigrationVerifier(
        run_store=store,
        evidence_provider=FakeEvidenceProvider(
            _evidence(legacy_config_count=2),
        ),
    )

    result = await verifier.verify(run_id=3)

    assert result.phase == "READY_TO_START"


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("legacy_tuple_count", 1, "LEGACY_TUPLES_REMAIN"),
        ("unapproved_manual_count", 1, "UNAPPROVED_MANUAL_ITEMS"),
        ("cross_tenant_count", 1, "CROSS_TENANT_FACTS"),
        ("invalid_owner_count", 1, "INVALID_OWNER_FACTS"),
        ("unattributed_visible_count", 1, "UNATTRIBUTED_VISIBLE_TUPLES"),
        ("visible_source_checksum_matches", False, "VISIBLE_SOURCE_CHECKSUM_MISMATCH"),
        ("visible_aggregate_checksum_matches", False, "VISIBLE_AGGREGATE_CHECKSUM_MISMATCH"),
        ("visible_stream_complete", False, "VISIBLE_STREAM_INCOMPLETE"),
        ("actual_target_checksum", "x" * 64, "TARGET_CHECKSUM_MISMATCH"),
    ],
)
async def test_verifier_blocks_any_unresolved_data_gate(field, value, reason):
    store = FakeStore()
    verifier = F048MigrationVerifier(
        run_store=store,
        evidence_provider=FakeEvidenceProvider(_evidence(**{field: value})),
    )

    with pytest.raises(PermissionMigrationBlockedError, match=reason):
        await verifier.verify(run_id=3)

    assert store.ready_checksums == []


async def test_verifier_blocks_semantic_failure_or_mixed_runtime_pins():
    bad_semantics = dict(_evidence().semantic_results)
    bad_semantics["download"] = False
    pins = (
        InstancePinEvidence(
            role="api",
            ready=True,
            store_id="store-live",
            model_id="legacy",
            catalog_release_id=9,
        ),
    )
    verifier = F048MigrationVerifier(
        run_store=FakeStore(),
        evidence_provider=FakeEvidenceProvider(
            _evidence(
                semantic_results=bad_semantics,
                instance_pins=pins,
            )
        ),
    )

    with pytest.raises(PermissionMigrationBlockedError) as exc_info:
        await verifier.verify(run_id=3)

    assert "SEMANTIC_CHECK_FAILED:download" in str(exc_info.value)
    assert "RUNTIME_PIN_MISMATCH" in str(exc_info.value)


async def test_verify_only_accepts_existing_formal_run_in_verifying_phase():
    store = FakeStore(run=replace(_run(), phase="MIGRATING_TUPLES"))
    verifier = F048MigrationVerifier(
        run_store=store,
        evidence_provider=FakeEvidenceProvider(_evidence()),
    )

    with pytest.raises(PermissionMigrationBlockedError):
        await verifier.verify(run_id=3)
