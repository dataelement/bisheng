"""Private, versioned production repair evidence and immutable plan copies."""

import json
import os

from bisheng.permission.domain.services.department_recovery_plan import RecoveryBlockedError, checksum
from scripts.f048_department_recovery_io import RecoveryAudit, encoded


class ProductionRepairAudit(RecoveryAudit):
    def emit(self, event, **fields):
        if event in {"batch_preflight_progress", "batch_item_started"}:
            self.results.write(encoded({"event": event, "run_id": self.run_id, **self.context, **fields}))
            self.results.flush()
            return
        if event in {"scan_sql_progress", "scan_fga_progress", "scan_ancestor_gate_impact"}:
            self.scan.write(encoded({"event": event, "run_id": self.run_id, **self.context, **fields}))
            self.scan.flush()
            return
        super().emit(event, **fields)

    async def before(self, payload):
        await super().before(payload)
        descriptor = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self.emit(
            "recovery_identity",
            recovery_id=payload["recovery_id"],
            department_id=payload["department_id"],
            confirmation_checksum=payload["confirmation_checksum"],
        )


def backup_evidence(path):
    with open(path, "rb") as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise RecoveryBlockedError("BACKUP_EVIDENCE_TOO_LARGE")
    try:
        value = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise RecoveryBlockedError("BACKUP_EVIDENCE_INVALID_JSON") from exc
    required = (
        "environment_fingerprint",
        "business_backup_reference",
        "fga_backup_reference",
        "backup_time",
    )
    if not isinstance(value, dict) or any(
        not isinstance(value.get(key), str) or not value[key].strip() for key in required
    ):
        raise RecoveryBlockedError("BACKUP_EVIDENCE_INCOMPLETE")
    return {key: value[key] for key in required} | {"evidence_checksum": checksum(value)}
