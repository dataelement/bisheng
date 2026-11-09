"""Real same-Session Coverage ports; only completed closed Run certificates admit reads."""

import re

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.knowledge.domain.repositories.unification_coverage_repository import (
    CoverageContext,
    UnificationCoverageRepository,
    blocked,
)
from bisheng.knowledge.domain.services.unification_fingerprints import digest
from bisheng.resource_reference.application.contracts import (
    CoverageStatus,
    GlobalCoverageStatus,
    SourceType,
    tenant_inventory_digest,
)
from bisheng.resource_reference.domain.repositories.coverage_repository import CoverageRepository

_TYPES = tuple(kind.value for kind in SourceType)
_CERTIFICATE_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "run_id",
        "writer_contract_version",
        "origin",
        "coverage_epoch",
        "baseline_hash",
        "plan_hash",
        "source_types",
        "proofs",
        "superseded_ledger_count",
        "superseded_ledger_digest",
        "certificate_digest",
    }
)
_PROOF_FIELDS = frozenset(
    {
        "extractor_version",
        "root_count",
        "source_count",
        "zero_reference_count",
        "reference_count",
        "valid_count",
        "invalid_legacy_count",
        "invalid_deleted_count",
        "source_digest",
        "reference_digest",
    }
)
_HISTORY_FIELDS = (
    "id",
    "tenant_id",
    "run_id",
    "origin",
    "phase",
    "writer_contract_version",
    "baseline_hash",
    "plan_hash",
    "baseline_ref",
    "plan_ref",
    "checkpoints",
    "source_coverage",
    "verification_report",
    "error_code",
    "error_reason",
    "coverage_epoch",
)


def _hash(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def ledger_inventory(rows):
    """Exact ordered prior Run state, excluding mutable audit-clock columns."""
    values = [{name: row[name] for name in _HISTORY_FIELDS} for row in sorted(rows, key=lambda row: row["id"])]
    return len(values), digest(values)


def _descriptor(value, checksum):
    return (
        type(value) is dict
        and set(value) == {"object_key", "sha256"}
        and _hash(checksum)
        and value["sha256"] == checksum
        and type(value["object_key"]) is str
        and bool(value["object_key"].strip())
        and not value["object_key"].startswith(("/", "file:"))
        and "://" not in value["object_key"]
    )


def validate_certificate(row, history, writer):
    if (
        row["phase"] != "completed"
        or row["writer_contract_version"] != writer
        or type(row["coverage_epoch"]) is not int
        or not 0 < row["coverage_epoch"] < 2**63
        or type(row["source_coverage"]) is not dict
        or set(row["source_coverage"]) != set(_TYPES)
        or any(value is not True for value in row["source_coverage"].values())
        or type(row["verification_report"]) is not dict
    ):
        blocked("certificate_not_complete")
    cert = row["verification_report"].get("reference_coverage")
    if type(cert) is not dict or set(cert) != _CERTIFICATE_FIELDS:
        blocked("closed_certificate_required")
    if (
        type(cert["schema_version"]) is not int
        or cert["schema_version"] != 1
        or type(cert["tenant_id"]) is not int
        or cert["tenant_id"] != row["tenant_id"]
        or type(cert["coverage_epoch"]) is not int
        or cert["coverage_epoch"] != row["coverage_epoch"]
        or any(
            cert[name] != row[name]
            for name in ("run_id", "writer_contract_version", "origin", "baseline_hash", "plan_hash")
        )
        or cert["source_types"] != list(_TYPES)
        or type(cert["proofs"]) is not dict
        or set(cert["proofs"]) != set(_TYPES)
    ):
        blocked("certificate_identity")
    if row["origin"] == "migration":
        if not _descriptor(row["baseline_ref"], row["baseline_hash"]) or not _descriptor(
            row["plan_ref"], row["plan_hash"]
        ):
            blocked("frozen_descriptors_required")
    elif row["origin"] == "empty_tenant":
        if (
            any(row[name] is not None for name in ("baseline_hash", "plan_hash"))
            or row["baseline_ref"] != {}
            or row["plan_ref"] != {}
        ):
            blocked("empty_tenant_not_migration")
    else:
        blocked("certificate_origin")
    for proof in cert["proofs"].values():
        if (
            type(proof) is not dict
            or set(proof) != _PROOF_FIELDS
            or type(proof["extractor_version"]) is not str
            or not 1 <= len(proof["extractor_version"]) <= 64
            or not _hash(proof["source_digest"])
            or not _hash(proof["reference_digest"])
        ):
            blocked("source_proof")
        if any(
            type(proof[name]) is not int or proof[name] < 0
            for name in _PROOF_FIELDS - {"extractor_version", "source_digest", "reference_digest"}
        ):
            blocked("source_counts")
        if (
            proof["zero_reference_count"] > proof["source_count"]
            or proof["reference_count"]
            != proof["valid_count"] + proof["invalid_legacy_count"] + proof["invalid_deleted_count"]
        ):
            blocked("source_count_closure")
        if row["origin"] == "empty_tenant" and any(
            proof[name] for name in _PROOF_FIELDS - {"extractor_version", "source_digest", "reference_digest"}
        ):
            blocked("empty_tenant_not_empty")
    if any(item["phase"] not in {"completed", "failed"} for item in history):
        blocked("unfinished_run_present")
    count, fingerprint = ledger_inventory(history)
    if type(cert["superseded_ledger_count"]) is not int or (
        cert["superseded_ledger_count"],
        cert["superseded_ledger_digest"],
    ) != (count, fingerprint):
        blocked("run_inventory_changed")
    if not _hash(cert["certificate_digest"]) or cert["certificate_digest"] != digest(
        {key: value for key, value in cert.items() if key != "certificate_digest"}
    ):
        blocked("certificate_checksum")
    return cert


def _current(rows, tenant, writer):
    candidates = [
        row
        for row in rows
        if row["tenant_id"] == tenant
        and row["writer_contract_version"] == writer
        and type(row["coverage_epoch"]) is int
        and row["coverage_epoch"] > 0
    ]
    if not candidates:
        blocked("certificate_missing")
    epoch = max(row["coverage_epoch"] for row in candidates)
    current = [row for row in candidates if row["coverage_epoch"] == epoch]
    if len(current) != 1:
        blocked("ambiguous_certificate")
    row = current[0]
    validate_certificate(
        row, tuple(item for item in rows if item["tenant_id"] == tenant and item["id"] != row["id"]), writer
    )
    return row


class ProductionCoverageReader:
    def __init__(self, session, *, repository=None):
        self.session = session
        self.repository = repository or UnificationCoverageRepository()

    @staticmethod
    def _local(rows, tenant, kind, writer):
        _current(rows, tenant, writer)
        return CoverageStatus(tenant, SourceType(kind), writer, True)

    @staticmethod
    def _global(rows, tenants, writer):
        if (
            not tenants
            or tuple(sorted(set(tenants))) != tenants
            or any(type(value) is not int or value <= 0 for value in tenants)
        ):
            blocked("actual_tenant_inventory_required")
        if any(row["tenant_id"] not in tenants for row in rows):
            blocked("orphan_coverage_run")
        by_tenant = {tenant: [] for tenant in tenants}
        for row in rows:
            by_tenant[row["tenant_id"]].append(row)
        current = tuple(_current(by_tenant[tenant], tenant, writer) for tenant in tenants)
        epoch = max(row["coverage_epoch"] for row in current)
        return GlobalCoverageStatus(True, writer, tuple(SourceType), tenant_inventory_digest(tenants), epoch, tenants)

    def get_status(self, tenant_id, source_type, writer_contract_version):
        context = CoverageContext(self.session)
        if type(tenant_id) is not int or tenant_id != context.tenant:
            blocked("local_tenant_scope")
        try:
            rows = self.repository.load_runs(self.session, tenant_id=tenant_id)
            result = self._local(rows, tenant_id, source_type, writer_contract_version)
            context.check()
            return result
        except ReferenceCoverageNotReadyError:
            raise
        except Exception as error:
            raise ReferenceCoverageNotReadyError(reason="production_coverage_read_failed") from error

    async def aget_status(self, tenant_id, source_type, writer_contract_version):
        context = CoverageContext(self.session)
        if type(tenant_id) is not int or tenant_id != context.tenant:
            blocked("local_tenant_scope")
        try:
            rows = await self.repository.aload_runs(self.session, tenant_id=tenant_id)
            result = self._local(rows, tenant_id, source_type, writer_contract_version)
            context.check()
            return result
        except ReferenceCoverageNotReadyError:
            raise
        except Exception as error:
            raise ReferenceCoverageNotReadyError(reason="production_coverage_read_failed") from error

    def get_global_status(self, writer_contract_version):
        context = CoverageContext(self.session)
        try:
            tenants = self.repository.load_tenants(self.session)
            rows = self.repository.load_runs(self.session)
            result = self._global(rows, tenants, writer_contract_version)
            context.check()
            return result
        except ReferenceCoverageNotReadyError:
            raise
        except Exception as error:
            raise ReferenceCoverageNotReadyError(reason="production_global_coverage_read_failed") from error

    async def aget_global_status(self, writer_contract_version):
        context = CoverageContext(self.session)
        try:
            tenants = await self.repository.aload_tenants(self.session)
            rows = await self.repository.aload_runs(self.session)
            result = self._global(rows, tenants, writer_contract_version)
            context.check()
            return result
        except ReferenceCoverageNotReadyError:
            raise
        except Exception as error:
            raise ReferenceCoverageNotReadyError(reason="production_global_coverage_read_failed") from error


def production_coverage_factory(session, *, writer_contract_version="f118-v1"):
    reader = ProductionCoverageReader(session)
    return CoverageRepository(reader, global_port=reader, writer_contract_version=writer_contract_version)
