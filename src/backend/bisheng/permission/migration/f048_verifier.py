"""D4 higher-consistency verifier for an existing formal F048 run."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Protocol

from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.permission.migration.f048_coordinator import MigrationRunState


@dataclass(frozen=True, slots=True)
class InstancePinEvidence:
    role: str
    ready: bool
    store_id: str
    model_id: str
    catalog_release_id: int | None
    dual_model_mode: bool
    legacy_model_id: str | None


@dataclass(frozen=True, slots=True)
class MigrationVerificationEvidence:
    source_checksum: str
    expected_target_checksum: str
    actual_target_checksum: str
    expected_target_count: int
    actual_target_count: int
    blocker_count: int
    unapproved_manual_count: int
    cross_tenant_count: int
    orphan_count: int
    invalid_parent_count: int
    invalid_owner_count: int
    failed_tuple_count: int
    legacy_tuple_count: int
    legacy_config_count: int
    preserved_tuple_checksum_matches: bool
    model_checksum_matches: bool
    semantic_results: Mapping[str, bool]
    instance_pins: tuple[InstancePinEvidence, ...]


class MigrationVerificationStorePort(Protocol):
    async def aget_run(self, run_id: int) -> MigrationRunState | None: ...

    async def amark_ready(
        self,
        *,
        run_id: int,
        expected_version: int,
        evidence_checksum: str,
    ) -> MigrationRunState: ...


class MigrationEvidenceProviderPort(Protocol):
    async def acollect(
        self,
        *,
        run: MigrationRunState,
        consistency: str,
    ) -> MigrationVerificationEvidence: ...


def _evidence_checksum(evidence: MigrationVerificationEvidence) -> str:
    payload = json.dumps(
        asdict(evidence),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _pin_reasons(
    run: MigrationRunState,
    pins: tuple[InstancePinEvidence, ...],
) -> list[str]:
    if not pins:
        return ["RUNTIME_HEARTBEATS_MISSING"]
    catalog_ids = {pin.catalog_release_id for pin in pins}
    invalid = (
        len(catalog_ids) != 1
        or None in catalog_ids
        or any(
            not pin.ready
            or pin.store_id != run.store_id
            or pin.model_id != run.target_model_id
            or pin.dual_model_mode
            or pin.legacy_model_id is not None
            for pin in pins
        )
    )
    return ["RUNTIME_PIN_MISMATCH"] if invalid else []


def _block_reasons(
    run: MigrationRunState,
    evidence: MigrationVerificationEvidence,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if run.source_checksum != evidence.source_checksum:
        reasons.append("SOURCE_CHECKSUM_MISMATCH")
    if (
        run.target_checksum != evidence.expected_target_checksum
        or evidence.expected_target_checksum != evidence.actual_target_checksum
    ):
        reasons.append("TARGET_CHECKSUM_MISMATCH")
    if evidence.expected_target_count != evidence.actual_target_count:
        reasons.append("TARGET_COUNT_MISMATCH")
    count_gates = (
        ("BLOCKER_ITEMS_REMAIN", evidence.blocker_count),
        ("UNAPPROVED_MANUAL_ITEMS", evidence.unapproved_manual_count),
        ("CROSS_TENANT_FACTS", evidence.cross_tenant_count),
        ("ORPHAN_FACTS", evidence.orphan_count),
        ("INVALID_PARENT_FACTS", evidence.invalid_parent_count),
        ("INVALID_OWNER_FACTS", evidence.invalid_owner_count),
        ("FAILED_TUPLES_REMAIN", evidence.failed_tuple_count),
        ("LEGACY_TUPLES_REMAIN", evidence.legacy_tuple_count),
    )
    reasons.extend(reason for reason, count in count_gates if count)
    if not evidence.preserved_tuple_checksum_matches:
        reasons.append("PRESERVED_TUPLE_CHECKSUM_MISMATCH")
    if not evidence.model_checksum_matches:
        reasons.append("MODEL_CHECKSUM_MISMATCH")
    reasons.extend(
        f"SEMANTIC_CHECK_FAILED:{name}" for name, passed in sorted(evidence.semantic_results.items()) if not passed
    )
    reasons.extend(_pin_reasons(run, evidence.instance_pins))
    return tuple(dict.fromkeys(reasons))


class F048MigrationVerifier:
    """Verify D4 facts and move only a clean run to READY_TO_START."""

    def __init__(
        self,
        *,
        run_store: MigrationVerificationStorePort,
        evidence_provider: MigrationEvidenceProviderPort,
    ) -> None:
        self._run_store = run_store
        self._evidence_provider = evidence_provider

    async def verify(self, *, run_id: int) -> MigrationRunState:
        run = await self._run_store.aget_run(run_id)
        if (
            run is None
            or run.phase != "VERIFYING"
            or run.status not in {"RUNNING", "BLOCKED"}
            or not run.target_model_id
        ):
            raise PermissionMigrationBlockedError(msg="VERIFY_REQUIRES_EXISTING_FORMAL_RUN")
        evidence = await self._evidence_provider.acollect(
            run=run,
            consistency="HIGHER_CONSISTENCY",
        )
        reasons = _block_reasons(run, evidence)
        if reasons:
            raise PermissionMigrationBlockedError(msg=";".join(reasons))
        return await self._run_store.amark_ready(
            run_id=run.id,
            expected_version=run.version,
            evidence_checksum=_evidence_checksum(evidence),
        )
