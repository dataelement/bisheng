"""Fail-closed production repair from current organization facts.

The maintenance operation is persisted only as FAILED_CLOSED or FINALIZED.
Online PROJECTING resumptions never receive this tool's private receipt format.
"""

import asyncio
import json
from types import SimpleNamespace

from bisheng.core.openfga.exceptions import FGAClientError
from bisheng.permission.domain.services.current_department_repair import (
    FORMAT,
    MAX_RECORD_BYTES,
    correction,
    event_id,
    target_keys,
    validate_history,
)
from bisheng.permission.domain.services.department_recovery_plan import (
    RecoveryBlockedError,
    RecoveryRuntimeError,
    checksum,
)
from bisheng.permission.domain.services.projection_diagnostics import emit_projection_alert, reason_from_exception


class CurrentDepartmentRepairApplication:
    def __init__(self, backend, *, transaction_timeout=15):
        self.backend = backend
        self.transaction_timeout = transaction_timeout

    async def inspect_department(self, identity):
        current = await self.backend.snapshot(identity)
        payload = self.preview(current)
        return SimpleNamespace(payload=payload)

    async def confirmed_snapshot(self, payload, record, *, lock=False):
        snapshot = getattr(self.backend, "snapshot_for_confirmation", None)
        if snapshot is not None:
            return await snapshot(payload, record, lock=lock)
        return await self.backend.snapshot(payload["department_id"], lock=lock)

    @staticmethod
    def preview(current):
        department, proof, observed = current["department"], current["business"], current["observed"]
        identity = department["id"]
        archive = current.get("archive")
        sources = []
        for operation, rows, owned in current["sources"]:
            if operation["id"] == department["operation_id"] and not owned:
                raise RecoveryBlockedError("BOUND_OPERATION_NOT_OWNED")
            if owned:
                validate_history(operation, rows, identity, archive=bool(archive or proof.get("inactive_cleanup")))
            sources.append(
                {
                    "operation": operation,
                    "owned": owned,
                    "tuples": [
                        {
                            "phase": row.phase,
                            "sequence": row.sequence,
                            "action": row.action,
                            "user": row.fga_user,
                            "relation": row.relation,
                            "object": row.fga_object,
                        }
                        for row in rows
                    ],
                }
            )
        if department["operation_id"] and not any(s["operation"]["id"] == department["operation_id"] for s in sources):
            raise RecoveryBlockedError("BOUND_OPERATION_MISSING")
        reparent = current.get("reparent")
        target = (
            frozenset()
            if proof.get("inactive_cleanup") or archive
            else target_keys(reparent["target"] if reparent else department, proof["direct_members"])
        )
        delta = correction(observed, target)
        bound = next(
            (row["operation"] for row in sources if row["operation"]["id"] == department["operation_id"]), None
        )
        consistent = department["state"] == "CURRENT" and (
            (department["operation_id"] is None and department["version"] == 0)
            or (
                bound
                and bound["tenant_id"] == department["tenant_id"]
                and bound["scope_type"] == "department"
                and bound["scope_key"] == str(identity)
                and bound["status"] == "FINALIZED"
                and bound["target_version"] == department["version"]
            )
        )
        payload = {
            "format": FORMAT,
            "algorithm": "f086-current-v1",
            "environment": current["environment"],
            "tenant_id": department["tenant_id"],
            "department_id": identity,
            "department": department,
            "business": proof,
            "business_checksum": checksum(proof),
            "sources": sources,
            "operation": {"id": department["operation_id"] or 0},
            "observed": [list(key) for key in sorted(observed)],
            "target": [list(key) for key in sorted(target)],
            "correction": delta,
            "classification": "PROCESSING"
            if current.get("processing")
            else "RECOVER_ARCHIVE"
            if archive
            and (
                department["status"] != "archived"
                or department["deleted"] != 1
                or any(archive["before"].values())
                or delta
                or not consistent
            )
            else "RECOVER_REPARENT"
            if reparent
            else "ALREADY_DONE"
            if consistent and not delta
            else "RECOVER_RELATIONS"
            if delta
            else "RECOVER_STATE_ONLY",
        }
        if reparent:
            payload["reparent"] = reparent
        if archive:
            payload["archive"] = archive
        payload["confirmation_checksum"] = checksum(payload)
        payload["recovery_id"] = event_id(payload["confirmation_checksum"], "identity")
        if len(json.dumps(payload, ensure_ascii=True).encode()) > MAX_RECORD_BYTES:
            raise RecoveryBlockedError("REPAIR_EVIDENCE_EXCEEDS_1MIB")
        return payload

    async def recover_department(self, confirmed, audit):
        try:
            scope = getattr(self.backend, "execution_scope", None)
            if scope is None:
                result = await self._recover_department(confirmed, audit)
            else:
                async with scope(confirmed):
                    result = await self._recover_department(confirmed, audit)
            emit_projection_alert(
                "RECOVERED",
                reason_code="RESTORED_AFTER_VERIFIED",
                tenant_id=confirmed["tenant_id"],
                department_id=confirmed["department_id"],
                operation_id=confirmed["operation"]["id"],
                details={"mode": "MANUAL_CURRENT", "recovery_id": confirmed["recovery_id"], "phase": "sql_readback"},
            )
            return result
        except Exception as error:
            emit_projection_alert(
                "FAILED",
                reason_code=reason_from_exception(error),
                tenant_id=confirmed.get("tenant_id"),
                department_id=confirmed.get("department_id"),
                operation_id=confirmed.get("operation", {}).get("id"),
                details={
                    "mode": "MANUAL_CURRENT",
                    "recovery_id": confirmed.get("recovery_id"),
                    "contained": None,
                    "phase": "apply",
                },
            )
            raise

    async def _recover_department(self, confirmed, audit):
        self.validate_confirmation(confirmed)
        # Network-only prerequisites are collected before holding SQL locks.
        await self._external_facts(confirmed)
        recovery_id = confirmed["recovery_id"]
        existing = await self.backend.record(recovery_id)
        if existing is None:
            outside = getattr(self.backend, "before_outside_transaction", False)
            if outside:
                await audit.before(confirmed)
            await self.backend.wait_for_request_slot()
            async with asyncio.timeout(self.transaction_timeout):
                async with self.backend.transaction():
                    # Recheck after locking; another process may have committed T1.
                    gate_snapshot = getattr(self.backend, "gate_snapshot", None)
                    locked = (
                        await gate_snapshot(confirmed)
                        if gate_snapshot is not None
                        else await self.backend.snapshot(confirmed["department_id"], lock=True)
                    )
                    existing = await self.backend.record(recovery_id, lock=True)
                    if existing is None:
                        current = self.preview(locked)
                        if current["confirmation_checksum"] != confirmed["confirmation_checksum"]:
                            raise RecoveryBlockedError("PLAN_CHANGED_REQUIRES_PREVIEW")
                        if current["classification"] == "PROCESSING":
                            raise RecoveryBlockedError("OPERATION_STILL_PROCESSING")
                        if current["classification"] == "ALREADY_DONE":
                            return "ALREADY_DONE"
                        if not outside:
                            await audit.before(confirmed)
                        await self.backend.prepare(confirmed)
        audit.emit("recovery_gate_committed", department_id=confirmed["department_id"], recovery_id=recovery_id)
        try:
            return await self.resume(recovery_id, audit)
        except RecoveryBlockedError as exc:
            # T1 may already be durable. Do not let the legacy batch helper
            # refund this item and open gates for more departments than limit.
            raise RecoveryRuntimeError(f"PREPARED_REPAIR_BLOCKED_STOP_BATCH:{exc}") from exc

    @staticmethod
    def validate_confirmation(payload):
        sealed = {key: value for key, value in payload.items() if key not in {"confirmation_checksum", "recovery_id"}}
        if (
            payload.get("format") != FORMAT
            or payload.get("algorithm") != "f086-current-v1"
            or payload.get("confirmation_checksum") != checksum(sealed)
            or payload.get("recovery_id") != event_id(payload["confirmation_checksum"], "identity")
        ):
            raise RecoveryBlockedError("CURRENT_REPAIR_CONFIRMATION_INVALID")

    async def resume(self, recovery_id, audit):
        initial = await self.backend.record(recovery_id)
        if initial is None:
            raise RecoveryBlockedError("REPAIR_PREPARED_EVIDENCE_MISSING")
        scope = getattr(self.backend, "execution_scope", None)
        if scope is None:
            return await self._resume(recovery_id, audit)
        async with scope(initial["preview"]):
            return await self._resume(recovery_id, audit)

    async def _resume(self, recovery_id, audit):
        initial = await self.backend.record(recovery_id)
        if initial is None:
            raise RecoveryBlockedError("REPAIR_PREPARED_EVIDENCE_MISSING")
        await self._external_facts(initial["preview"])
        await self.backend.wait_for_request_slot()
        async with asyncio.timeout(self.transaction_timeout):
            async with self.backend.transaction():
                current = await self.confirmed_snapshot(initial["preview"], initial, lock=True)
                record = await self.backend.record(recovery_id, lock=True)
                if record is None:
                    raise RecoveryBlockedError("REPAIR_PREPARED_EVIDENCE_MISSING")
                payload = record["preview"]
                self.validate_confirmation(payload)
                if payload.get("archive"):
                    await self.backend.validate_archive_record(record, current)
                # Lock/read environment and D before acting; completion is SQL truth.
                completed = await self.backend.completed(record, current)
                if completed is not None:
                    return completed
                department = current["department"]
                if (
                    department["state"] != "FAILED_CLOSED"
                    or department["operation_id"] != record["operation_id"]
                    or department["version"] != payload["department"]["version"]
                ):
                    raise RecoveryBlockedError("SUPERSEDED_REPAIR_NOT_OWNED")
                if (
                    current["environment"] != payload["environment"]
                    or checksum(current["business"]) != payload["business_checksum"]
                ):
                    raise RecoveryBlockedError("BUSINESS_OR_MODEL_CHANGED_REQUIRES_PREVIEW")
                if await self.backend.has_active_operations(department):
                    raise RecoveryBlockedError("NEW_DEPARTMENT_OPERATION_REQUIRES_DRAIN")
                observed = current["observed"]
                before, target = {tuple(k) for k in payload["observed"]}, {tuple(k) for k in payload["target"]}
                if observed != before and observed != target:
                    raise RecoveryBlockedError("THIRD_TOPOLOGY_STATE_REQUIRES_PREVIEW")
                await self.backend.arm_repair(recovery_id, payload["tenant_id"])
                if observed != target:
                    audit.emit("fga_write_started", department_id=payload["department_id"], recovery_id=recovery_id)
                    try:
                        await self.backend.write_repair(payload["correction"])
                    except FGAClientError as exc:
                        if await self.backend.observed(payload["department_id"]) != target:
                            raise RecoveryRuntimeError("FGA_OUTCOME_UNKNOWN_GATE_REMAINS_CLOSED") from exc
                if await self.backend.observed(payload["department_id"]) != target:
                    raise RecoveryRuntimeError("CURRENT_TARGET_NOT_VERIFIED_GATE_REMAINS_CLOSED")
                audit.emit("fga_verified", department_id=payload["department_id"], recovery_id=recovery_id)
                proof = await self.backend.current_business(payload["department_id"], lock=True)
                if (
                    checksum(proof) != payload["business_checksum"]
                    or await self.backend.environment(lock=True, refresh=True) != payload["environment"]
                ):
                    raise RecoveryRuntimeError("FACTS_CHANGED_AFTER_WRITE_GATE_REMAINS_CLOSED")
                await self.backend.finalize(record)
        # Never infer SQL commit from FGA AFTER or the external result file.
        audit.emit("sql_finalized", recovery_id=recovery_id)
        await self.backend.verify_repair(recovery_id)
        audit.emit("sql_readback_verified", recovery_id=recovery_id)
        return "FINALIZED"

    async def _external_facts(self, payload):
        prepare = getattr(self.backend, "prepare_external_facts", None)
        if prepare is not None:
            await prepare(payload)
