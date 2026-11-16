"""Existing ledger/audit persistence for one-off current department repair.

Every mutator requires the caller's UOW. No new table, implicit commit, JSON
query, or online projection dispatch is used.
"""

import json

from sqlmodel import select

from bisheng.core.database import get_async_db_session
from bisheng.database.models.audit_log import AuditLog
from bisheng.permission.domain.models import PermissionProjectionOperation, PermissionProjectionTuple
from bisheng.permission.domain.services.current_department_repair import (
    ACTIVE,
    MAX_DELTA,
    MAX_RECORD_BYTES,
    REPAIR_TYPE,
    event_id,
)
from bisheng.permission.domain.services.department_recovery_plan import RecoveryBlockedError, checksum


def operation_snapshot(operation):
    if operation is None:
        return None
    fields = (
        "id",
        "tenant_id",
        "operation_type",
        "scope_type",
        "scope_key",
        "status",
        "expected_version",
        "target_version",
        "store_id",
        "model_id",
        "request_checksum",
        "before_checksum",
        "after_checksum",
        "commit_checksum",
    )
    return {key: getattr(operation, key) for key in fields} | {
        "error_message_checksum": checksum(operation.error_message or ""),
        "update_time": operation.update_time.isoformat() if operation.update_time else None,
    }


class CurrentDepartmentRepairLedger:
    def __init__(self, session_factory=get_async_db_session):
        self.session_factory = session_factory

    async def check_existing_schema(self):
        # SELECT zero rows verifies existing columns without DDL or probe writes.
        async with self.session_factory() as session:
            for model in (PermissionProjectionOperation, PermissionProjectionTuple, AuditLog):
                await session.exec(select(model).limit(0))

    async def record(self, recovery_id, tenant_id, *, session=None, lock=False, stage="prepared"):
        identity = event_id(recovery_id, stage)
        if session is None:
            async with self.session_factory() as own:
                return await self.record(recovery_id, tenant_id, session=own, stage=stage)
        statement = select(AuditLog).where(AuditLog.id == identity)
        if lock:
            statement = statement.with_for_update(nowait=True).execution_options(populate_existing=True)
        row = (await session.exec(statement)).first()
        if row is None:
            return None
        if row.tenant_id != tenant_id or row.action != f"permission.department.recovery.{stage}":
            raise RecoveryBlockedError("AUDIT_IDENTITY_MISMATCH")
        value = row.audit_metadata
        if (
            not isinstance(value, dict)
            or value.get("recovery_id") != recovery_id
            or not isinstance(value.get("operation_id"), int)
            or value["operation_id"] <= 0
            or not isinstance(value.get("preview"), dict)
            or value["preview"].get("tenant_id") != tenant_id
            or value["preview"].get("recovery_id") != recovery_id
        ):
            raise RecoveryBlockedError("AUDIT_EVIDENCE_INVALID")
        return value

    async def active_operation_ids(self, department, *, session, first_only=False):
        # Avoid DM's expensive status-IN + ORDER BY id + pagination plan.
        # Each probe matches the scope index with one status and reads IDs only.
        # 33 per status still detects >32 across their union without truncating
        # any permitted set. Tenant predicates are supplied by the shared filter.
        identities = set()
        for status in sorted(ACTIVE):
            statement = (
                select(PermissionProjectionOperation.id)
                .where(
                    PermissionProjectionOperation.scope_type == "department",
                    PermissionProjectionOperation.scope_key == str(department["id"]),
                    PermissionProjectionOperation.status == status,
                )
                .limit(1 if first_only else 33)
            )
            identities.update(int(value) for value in (await session.exec(statement)).all())
            if first_only and identities:
                return sorted(identities)
            if len(identities) > 32:
                raise RecoveryBlockedError("TOO_MANY_PENDING_OPERATIONS")
        return sorted(identities)

    async def completed_sources(self, department, record, *, session, lock=False):
        if record is None or department["state"] != "CURRENT":
            return None
        payload = record["preview"]
        if department["operation_id"] != record["operation_id"]:
            raise RecoveryBlockedError("BATCH_RESUME_BINDING_NOT_OWNED")
        if department["version"] != payload["department"]["version"] + 1:
            raise RecoveryBlockedError("BATCH_RESUME_DEPARTMENT_CHANGED")
        statement = select(PermissionProjectionOperation).where(
            PermissionProjectionOperation.id == record["operation_id"]
        )
        if lock:
            statement = statement.with_for_update(nowait=True).execution_options(populate_existing=True)
        operation = (await session.exec(statement)).first()
        finished = await self.record(
            payload["recovery_id"], department["tenant_id"], session=session, stage="finalized"
        )
        if (
            operation is None
            or operation.tenant_id != department["tenant_id"]
            or operation.scope_type != "department"
            or operation.scope_key != str(department["id"])
            or operation.operation_type != REPAIR_TYPE
            or operation.status != "FINALIZED"
            or operation.target_version != department["version"]
            or operation.commit_checksum != checksum(payload["target"])
            or finished is None
            or finished["operation_id"] != record["operation_id"]
            or checksum(finished["preview"]) != checksum(payload)
        ):
            raise RecoveryBlockedError("COMPLETION_EVIDENCE_MISSING")
        # Only an explicitly confirmed, completed recovery uses this path.
        # Ordinary discovery still examines all active operations for the scope.
        return [(operation_snapshot(operation), [], True)]

    async def operations(self, department, *, session, lock=False, completed_record=None):
        completed = await self.completed_sources(department, completed_record, session=session, lock=lock)
        if completed is not None:
            return completed
        identities = set(await self.active_operation_ids(department, session=session))
        if department["operation_id"]:
            identities.add(department["operation_id"])
        result = []
        for identity in sorted(identities):
            row = (
                await session.exec(
                    select(PermissionProjectionOperation).where(PermissionProjectionOperation.id == identity)
                )
            ).first()
            if row is None:
                if identity != department["operation_id"]:
                    raise RecoveryBlockedError("ACTIVE_OPERATION_DISAPPEARED")
                continue
            # Scope/tenant-mismatched bindings are reported but never canceled.
            owned = (
                row.tenant_id == department["tenant_id"]
                and row.scope_type == "department"
                and row.scope_key == str(department["id"])
            )
            tuples = []
            if owned:
                tuples = list(
                    (
                        await session.exec(
                            select(PermissionProjectionTuple)
                            .where(PermissionProjectionTuple.operation_id == row.id)
                            .order_by(PermissionProjectionTuple.sequence)
                            .limit(MAX_DELTA + 1)
                        )
                    ).all()
                )
                if len(tuples) > MAX_DELTA:
                    raise RecoveryBlockedError("PENDING_LEDGER_SCOPE_TOO_LARGE")
            if owned and lock:
                row = await self.lock_operation(row.id, session=session)
                if (
                    row is None
                    or row.tenant_id != department["tenant_id"]
                    or row.scope_type != "department"
                    or row.scope_key != str(department["id"])
                ):
                    raise RecoveryBlockedError("SOURCE_CHANGED_DURING_LOCK")
            if owned and row.operation_type == REPAIR_TYPE:
                if not row.idempotency_key.startswith("f086:current:"):
                    raise RecoveryBlockedError("CURRENT_MAINTENANCE_PROTOCOL_UNKNOWN")
                recovery_id = row.idempotency_key.removeprefix("f086:current:")
                sealed = await self.record(recovery_id, row.tenant_id, session=session)
                if sealed is None or sealed["operation_id"] != row.id:
                    raise RecoveryBlockedError("CURRENT_MAINTENANCE_SEAL_MISSING")
                await self.check_gate(sealed["preview"], row.id, session=session, lock=lock)
            snapshot = operation_snapshot(row)
            if owned and row.operation_type == "DEPARTMENT_CURRENT_REPAIR":
                await self.verify_legacy_record(row, tuples, session=session)
                snapshot["legacy_sealed_v2_verified"] = True
            result.append((snapshot, tuples, owned))
        return result

    async def verify_legacy_record(self, operation, tuples, *, session):
        from uuid import NAMESPACE_URL, uuid5

        prefix = "f078-current:"
        if not operation.idempotency_key.startswith(prefix):
            raise RecoveryBlockedError("LEGACY_MAINTENANCE_PROTOCOL_UNKNOWN")
        recovery_id = operation.idempotency_key.removeprefix(prefix)
        identity = uuid5(NAMESPACE_URL, f"bisheng:f078:production:v2:{recovery_id}:prepared").hex
        record = (await session.exec(select(AuditLog).where(AuditLog.id == identity))).first()
        value = record.audit_metadata if record is not None else None
        if (
            record is None
            or record.tenant_id != operation.tenant_id
            or record.action != "permission.department.current_repair.prepared"
            or not isinstance(value, dict)
            or value.get("operation_id") != operation.id
        ):
            raise RecoveryBlockedError("LEGACY_MAINTENANCE_SEAL_MISSING")
        preview = value.get("preview", {})
        core = {k: v for k, v in preview.items() if k not in {"confirmation_checksum", "recovery_id"}}
        if (
            preview.get("format") != "f078.current-department-production.v2"
            or preview.get("confirmation_checksum") != checksum(core)
            or operation.request_checksum != preview.get("confirmation_checksum")
            or preview.get("recovery_id") != recovery_id
            or preview.get("tenant_id") != operation.tenant_id
            or str(preview.get("department_id")) != operation.scope_key
            or operation.expected_version != preview.get("department", {}).get("version")
            or operation.target_version != operation.expected_version + 1
            or operation.store_id != preview.get("environment", {}).get("store_id")
            or operation.model_id != preview.get("environment", {}).get("model_id")
            or recovery_id
            != uuid5(NAMESPACE_URL, f"bisheng:f078:production:v2:{preview.get('confirmation_checksum')}:identity").hex
            or operation.before_checksum != checksum(preview.get("observed"))
            or operation.after_checksum != checksum(preview.get("target"))
        ):
            raise RecoveryBlockedError("LEGACY_MAINTENANCE_SEAL_INVALID")
        actual = [
            {"action": r.action, "user": r.fga_user, "relation": r.relation, "object": r.fga_object} for r in tuples
        ]
        if actual != preview.get("correction"):
            raise RecoveryBlockedError("LEGACY_MAINTENANCE_TUPLES_CHANGED")

    async def lock_operation(self, operation_id, *, session):
        return (
            await session.exec(
                select(PermissionProjectionOperation)
                .where(PermissionProjectionOperation.id == operation_id)
                .with_for_update(nowait=True)
                .execution_options(populate_existing=True)
            )
        ).first()

    async def create_gate(self, payload, *, session):
        recovery_id = payload["recovery_id"]
        key = f"f086:current:{recovery_id}"
        existing = (
            await session.exec(
                select(PermissionProjectionOperation).where(PermissionProjectionOperation.idempotency_key == key)
            )
        ).first()
        if existing is not None:
            raise RecoveryBlockedError("GATE_WITHOUT_PREPARED_AUDIT")
        operation = PermissionProjectionOperation(
            tenant_id=payload["tenant_id"],
            idempotency_key=key,
            request_checksum=payload["confirmation_checksum"],
            operation_type=REPAIR_TYPE,
            scope_type="department",
            scope_key=str(payload["department_id"]),
            expected_version=payload["department"]["version"],
            target_version=payload["department"]["version"] + 1,
            store_id=payload["environment"]["store_id"],
            model_id=payload["environment"]["model_id"],
            status="FAILED_CLOSED",
            before_checksum=checksum(payload["observed"]),
            after_checksum=checksum(payload["target"]),
            operator_id=0,
            error_message=f"F086 maintenance gate; recovery_id={recovery_id}",
        )
        session.add(operation)
        await session.flush()
        for index, delta in enumerate(payload["correction"]):
            row = PermissionProjectionTuple(
                tenant_id=payload["tenant_id"],
                operation_id=operation.id,
                phase="COMMIT",
                sequence=index,
                action=delta["action"],
                fga_user=delta["user"],
                relation=delta["relation"],
                fga_object=delta["object"],
                tuple_fingerprint=checksum(delta),
                inverse_action="DELETE" if delta["action"] == "WRITE" else "WRITE",
                status="PENDING",
            )
            session.add(row)
        return int(operation.id)

    async def cancel_sources(self, sources, recovery_id, *, session):
        for snapshot, _, owned in sources:
            if not owned or snapshot["status"] not in (ACTIVE | {"FAILED_CLOSED"}):
                continue
            row = await self.lock_operation(snapshot["id"], session=session)
            if row is None or operation_snapshot(row) != snapshot:
                raise RecoveryBlockedError("SOURCE_OPERATION_CHANGED")
            row.status = "FAILED_CLOSED"
            session.add(row)
            identity = event_id(recovery_id, f"superseded:{row.id}")
            if (await session.exec(select(AuditLog.id).where(AuditLog.id == identity))).first() is None:
                session.add(
                    AuditLog(
                        id=identity,
                        tenant_id=row.tenant_id,
                        operator_id=0,
                        action="permission.department.recovery.superseded",
                        target_type="department_projection",
                        target_id=row.scope_key,
                        audit_metadata={
                            "operation_id": row.id,
                            "recovery_id": recovery_id,
                            "source_disposition": "maintenance_terminated_not_success",
                        },
                    )
                )

    async def append(self, payload, operation_id, stage, *, session, **extra):
        recovery_id = payload["recovery_id"]
        value = {
            "schema_version": 1,
            "recovery_id": recovery_id,
            "operation_id": operation_id,
            "preview": payload,
            **extra,
        }
        if len(json.dumps(value, ensure_ascii=True).encode()) > MAX_RECORD_BYTES:
            raise RecoveryBlockedError("AUDIT_EVIDENCE_EXCEEDS_1MIB")
        existing = await self.record(recovery_id, payload["tenant_id"], session=session, lock=True, stage=stage)
        if existing is not None:
            if checksum(existing) != checksum(value):
                raise RecoveryBlockedError("AUDIT_CONTENT_CONFLICT")
            return
        session.add(
            AuditLog(
                id=event_id(recovery_id, stage),
                tenant_id=payload["tenant_id"],
                operator_id=0,
                action=f"permission.department.recovery.{stage}",
                target_type="department_projection",
                target_id=str(operation_id),
                audit_metadata=value,
            )
        )
        await session.flush()

    async def check_gate(self, payload, operation_id, *, session, lock=True):
        operation = (
            await self.lock_operation(operation_id, session=session)
            if lock
            else (
                await session.exec(
                    select(PermissionProjectionOperation).where(PermissionProjectionOperation.id == operation_id)
                )
            ).first()
        )
        core = {key: value for key, value in payload.items() if key not in {"confirmation_checksum", "recovery_id"}}
        from bisheng.permission.domain.services.current_department_repair import FORMAT

        if payload.get("format") != FORMAT or checksum(core) != payload.get("confirmation_checksum"):
            raise RecoveryBlockedError("CURRENT_MAINTENANCE_SEAL_INVALID")
        expected = {
            "tenant_id": payload["tenant_id"],
            "operation_type": REPAIR_TYPE,
            "scope_type": "department",
            "scope_key": str(payload["department_id"]),
            "idempotency_key": f"f086:current:{payload['recovery_id']}",
            "request_checksum": payload["confirmation_checksum"],
            "expected_version": payload["department"]["version"],
            "target_version": payload["department"]["version"] + 1,
            "store_id": payload["environment"]["store_id"],
            "model_id": payload["environment"]["model_id"],
            "before_checksum": checksum(payload["observed"]),
            "after_checksum": checksum(payload["target"]),
        }
        if operation is None or any(getattr(operation, key) != value for key, value in expected.items()):
            raise RecoveryBlockedError("REPAIR_LEDGER_IDENTITY_OR_CHECKSUM_MISMATCH")
        rows = list(
            (
                await session.exec(
                    select(PermissionProjectionTuple)
                    .where(PermissionProjectionTuple.operation_id == operation_id)
                    .order_by(PermissionProjectionTuple.sequence)
                    .limit(MAX_DELTA + 1)
                )
            ).all()
        )
        actual = [
            {"action": row.action, "user": row.fga_user, "relation": row.relation, "object": row.fga_object}
            for row in rows
        ]
        if actual != payload["correction"] or any(
            row.phase != "COMMIT"
            or row.sequence != index
            or row.tuple_fingerprint != checksum(payload["correction"][index])
            or row.inverse_action != ("DELETE" if row.action == "WRITE" else "WRITE")
            for index, row in enumerate(rows)
        ):
            raise RecoveryBlockedError("REPAIR_TUPLE_LEDGER_MISMATCH")
        expected_status = "VERIFIED" if operation.status == "FINALIZED" else "PENDING"
        if any(row.status != expected_status for row in rows):
            raise RecoveryBlockedError("REPAIR_TUPLE_STAGE_MISMATCH")
        return operation

    async def finalize(self, payload, operation_id, *, session):
        operation = await self.check_gate(payload, operation_id, session=session)
        if operation.status != "FAILED_CLOSED":
            raise RecoveryBlockedError("REPAIR_OPERATION_FENCE_MISMATCH")
        operation.status = "FINALIZED"
        operation.commit_checksum = operation.after_checksum
        operation.error_message = None
        session.add(operation)
        rows = list(
            (
                await session.exec(
                    select(PermissionProjectionTuple).where(PermissionProjectionTuple.operation_id == operation_id)
                )
            ).all()
        )
        for row in rows:
            row.status = "VERIFIED"
            session.add(row)
        await self.append(
            payload,
            operation_id,
            "finalized",
            session=session,
            outcome="CURRENT_REPAIRED",
        )
