"""Production-only composition for current department facts; no online dispatch."""

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime
from types import SimpleNamespace

from bisheng.core.database import get_async_db_session
from bisheng.department.domain.repositories.current_repair_repository import CurrentDepartmentRepairRepository
from bisheng.department.domain.services.current_projection_repair import CurrentDepartmentRepairService
from bisheng.permission.application.department_recovery_runtime import DepartmentRecoveryRuntime
from bisheng.permission.domain.repositories.current_department_repair_repository import CurrentDepartmentRepairLedger
from bisheng.permission.domain.services.current_department_repair import ACTIVE, MAX_KEYS, archive_owned_key, owned_key
from bisheng.permission.domain.services.department_recovery_plan import (
    RecoveryBlockedError,
    RecoveryRuntimeError,
    checksum,
)
from bisheng.permission.domain.services.projection_plan import ProjectionTupleDelta


class CurrentDepartmentRepairRuntime(DepartmentRecoveryRuntime):
    def __init__(
        self,
        environment_id,
        qps=2,
        *,
        backup_evidence=None,
        window_id=None,
        stale_after_seconds=1800,
        writers_idle=False,
    ):
        super().__init__(environment_id, qps)
        self.departments = CurrentDepartmentRepairRepository()
        self.business = CurrentDepartmentRepairService(self.departments)
        self.ledger = CurrentDepartmentRepairLedger()
        self.backup_evidence = backup_evidence
        self.window_id = window_id
        self.stale_after_seconds = stale_after_seconds
        self.writers_idle = writers_idle
        self._locked_sources = None

    @property
    def _locked_sources(self):
        contexts = self.__dict__.setdefault("_proof_contexts", {})
        return contexts.setdefault("_locked_sources", ContextVar("_locked_sources", default=None)).get()

    @_locked_sources.setter
    def _locked_sources(self, value):
        contexts = self.__dict__.setdefault("_proof_contexts", {})
        contexts.setdefault("_locked_sources", ContextVar("_locked_sources", default=None)).set(value)

    @property
    def _completed_record_hint(self):
        contexts = self.__dict__.setdefault("_proof_contexts", {})
        return contexts.setdefault("_completed_record_hint", ContextVar("_completed_record_hint", default=None)).get()

    @_completed_record_hint.setter
    def _completed_record_hint(self, value):
        contexts = self.__dict__.setdefault("_proof_contexts", {})
        contexts.setdefault("_completed_record_hint", ContextVar("_completed_record_hint", default=None)).set(value)

    @property
    def _gate_payload_hint(self):
        contexts = self.__dict__.setdefault("_proof_contexts", {})
        return contexts.setdefault("_gate_payload_hint", ContextVar("_gate_payload_hint", default=None)).get()

    @_gate_payload_hint.setter
    def _gate_payload_hint(self, value):
        contexts = self.__dict__.setdefault("_proof_contexts", {})
        contexts.setdefault("_gate_payload_hint", ContextVar("_gate_payload_hint", default=None)).set(value)

    @asynccontextmanager
    async def transaction(self):
        self._locked_sources = None
        try:
            async with super().transaction():
                yield
        finally:
            self._locked_sources = None

    async def observed(self, identity, *, include_admin=False):
        present = set()
        filters = (
            {"object": f"department:{identity}", "relation": "parent"},
            {"object": "department:", "user": f"department:{identity}", "relation": "child"},
            {"object": f"department:{identity}", "relation": "member"},
        )
        if include_admin:
            filters = (*filters, {"object": f"department:{identity}", "relation": "admin"})
        owns = archive_owned_key if include_admin else owned_key
        for query in filters:
            # Per-HTTP timeout remains 5s. Complete pagination gets a separate
            # bounded budget so low QPS does not masquerade as missing data.
            async with asyncio.timeout(getattr(self, "relation_read_timeout", 5)):
                async for row in self.client.iter_tuples(**query, consistency="HIGHER_CONSISTENCY"):
                    key = (row.get("user", ""), row.get("relation", ""), row.get("object", ""))
                    if row.get("condition") or not owns(key, identity):
                        raise RecoveryBlockedError("UNSUPPORTED_DEPARTMENT_RELATION_SHAPE")
                    present.add(key)
                    if len(present) > MAX_KEYS:
                        raise RecoveryBlockedError("OBSERVED_SCOPE_TOO_LARGE")
        return frozenset(present)

    async def snapshot(self, identity, *, lock=False):
        # Catalog before D before operations/ancestors/members, consistently in T1/T2.
        environment = await self.environment(lock=lock)
        if self.session is None:
            async with get_async_db_session() as db:
                department = await self.departments.get(identity, session=db)
                return await self._snapshot(environment, department, db, lock=False)
        department = await self.departments.get(identity, session=self.session, lock=lock)
        return await self._snapshot(environment, department, self.session, lock=lock)

    async def snapshot_for_confirmation(self, payload, record, *, lock=False):
        if record is not None and checksum(record["preview"]) != checksum(payload):
            raise RecoveryBlockedError("BATCH_SHARED_RECORD_PREVIEW_MISMATCH")
        previous = getattr(self, "_completed_record_hint", None)
        self._completed_record_hint = (payload["department_id"], record)
        try:
            return await self.snapshot(payload["department_id"], lock=lock)
        finally:
            self._completed_record_hint = previous

    async def gate_snapshot(self, payload):
        previous = getattr(self, "_gate_payload_hint", None)
        self._gate_payload_hint = payload if getattr(self, "offline_maintenance", False) else None
        try:
            return await self.snapshot(payload["department_id"], lock=True)
        finally:
            self._gate_payload_hint = previous

    async def _snapshot(self, environment, department, session, *, lock):
        if department is None:
            raise RecoveryBlockedError("DEPARTMENT_MISSING_OR_NOT_VISIBLE")
        from bisheng.core.context.tenant import get_current_tenant_id

        if department["tenant_id"] != get_current_tenant_id():
            raise RecoveryBlockedError("DEPARTMENT_OUTSIDE_SELECTED_TENANT")
        hint = getattr(self, "_completed_record_hint", None)
        kwargs = {"completed_record": hint[1]} if hint is not None and hint[0] == department["id"] else {}
        sources = await self.ledger.operations(department, session=session, lock=lock, **kwargs)
        # ledger.operations already returns fresh, NOWAIT-locked owned rows.
        try:
            business, reparent = await self.prove_business(department, session=session, lock=lock)
        except ValueError as exc:
            blocked = RecoveryBlockedError(str(exc))
            blocked.details = getattr(exc, "details", {})
            raise blocked from exc
        now = await self.database_time()
        if isinstance(now, str):
            now = datetime.fromisoformat(now)
        processing = False
        for operation, _, owned in sources:
            if owned and operation["status"] in ACTIVE:
                updated = operation["update_time"]
                if not updated:
                    raise RecoveryBlockedError("PENDING_OPERATION_TIME_MISSING")
                age = (now.replace(tzinfo=None) - datetime.fromisoformat(updated).replace(tzinfo=None)).total_seconds()
                processing = processing or (
                    department["state"] == "PROJECTING"
                    and not getattr(self, "writers_idle", False)
                    and age < self.stale_after_seconds
                )
        result = {
            "environment": environment,
            "department": department,
            "business": business,
            "processing": processing,
            "observed": await self.observed(
                department["id"], include_admin=bool(business.get("inactive_cleanup") or business.get("iam_archive"))
            ),
            "sources": sources,
        }
        if reparent:
            result["archive" if reparent.get("kind") == "archive" else "reparent"] = reparent
        if lock and self.session is session:
            self._locked_sources = (session, dict(department), sources)
        return result

    async def prove_business(self, department, *, session=None, lock=False):
        return await self.business.prove(department, session=session, lock=lock), None

    async def prepare_external_facts(self, payload):
        if payload["business"].get("iam"):
            raise RecoveryBlockedError("IAM_CONFIG_REQUIRED_FOR_IAM_PLAN")

    async def current_business(self, identity, *, lock=False):
        department = await self.departments.get(identity, session=self.session, lock=lock)
        try:
            proof, _ = await self.prove_business(department, session=self.session, lock=lock)
            return proof
        except ValueError as exc:
            raise RecoveryRuntimeError("CURRENT_BUSINESS_PROOF_FAILED_AFTER_WRITE") from exc

    async def record(self, recovery_id, *, lock=False):
        from bisheng.core.context.tenant import get_current_tenant_id

        return await self.ledger.record(recovery_id, get_current_tenant_id(), session=self.session, lock=lock)

    async def prepare(self, payload):
        await self.verify_execution()
        if not self.session or not self.backup_evidence or not self.window_id:
            raise RecoveryBlockedError("BACKUP_WINDOW_AND_UOW_REQUIRED")
        if self.backup_evidence["environment_fingerprint"] != checksum(payload["environment"]):
            raise RecoveryBlockedError("BACKUP_ENVIRONMENT_MISMATCH")
        cached = getattr(self, "_locked_sources", None)
        self._locked_sources = None
        if cached is not None and cached[0] is self.session and cached[1] == payload["department"]:
            sources = cached[2]
        else:
            sources = await self.ledger.operations(payload["department"], session=self.session, lock=True)
        operation_id = await self.ledger.create_gate(payload, session=self.session)
        await self.ledger.cancel_sources(sources, payload["recovery_id"], session=self.session)
        if payload.get("archive"):
            await self.departments.archive_gate(payload["department"], payload["archive"], operation_id, self.session)
        elif payload.get("reparent"):
            await self.departments.reparent_gate(payload["department"], payload["reparent"], operation_id, self.session)
        else:
            await self.departments.set_gate(payload["department"], operation_id, self.session)
        await self.ledger.append(
            payload,
            operation_id,
            "prepared",
            session=self.session,
            backup_evidence=self.backup_evidence,
            window_id=self.window_id,
            superseded_operations=[row[0]["id"] for row in sources if row[2] and row[0]["status"] in ACTIVE],
            source_disposition="maintenance_terminated_not_success",
        )

    async def completed(self, record, current):
        payload, identity = record["preview"], record["operation_id"]
        from bisheng.core.context.tenant import get_current_tenant_id

        completed = await self.ledger.record(
            payload["recovery_id"], get_current_tenant_id(), session=self.session, stage="finalized"
        )
        operation = await self.ledger.check_gate(payload, identity, session=self.session)
        if operation.status == "FINALIZED":
            if (
                completed is None
                or completed["operation_id"] != identity
                or checksum(completed["preview"]) != checksum(payload)
                or operation.commit_checksum != checksum(payload["target"])
            ):
                raise RecoveryBlockedError("COMPLETION_EVIDENCE_MISSING")
            department = current["department"]
            if (
                department["operation_id"] == identity
                and department["state"] == "CURRENT"
                and department["version"] == operation.target_version
                and current["environment"] == payload["environment"]
                and checksum(current["business"]) == payload["business_checksum"]
                and current["observed"] == {tuple(key) for key in payload["target"]}
            ):
                return "ALREADY_DONE"
            return "FINALIZED_HISTORY_ONLY"
        if completed is not None or operation.status != "FAILED_CLOSED":
            raise RecoveryBlockedError("INCONSISTENT_REPAIR_STAGE")
        if record.get("window_id") != self.window_id or record.get("backup_evidence") != self.backup_evidence:
            raise RecoveryBlockedError("REPAIR_WINDOW_OR_BACKUP_CHANGED_REPREVIEW")
        return None

    async def has_active_operations(self, department):
        return bool(await self.ledger.active_operation_ids(department, session=self.session, first_only=True))

    async def arm_repair(self, recovery_id, tenant_id):
        await self.verify_execution()
        await self.fga.arm(SimpleNamespace(tenant_id=tenant_id, idempotency_key=f"f086:current:{recovery_id}"))

    async def write_repair(self, rows):
        await self.verify_execution()
        deltas = tuple(ProjectionTupleDelta(phase="COMMIT", sequence=index, **row) for index, row in enumerate(rows))
        await self.fga.write(deltas)

    async def finalize(self, record):
        await self.verify_execution()
        payload, identity = record["preview"], record["operation_id"]
        if payload.get("archive"):
            await self.departments.cleanup_archive(
                payload["archive"]["target"], payload["archive"]["before"], self.archive_roles, self.session
            )
        await self.ledger.finalize(payload, identity, session=self.session)
        await self.departments.finish(
            payload.get("archive", payload.get("reparent", {})).get("target", payload["department"]),
            identity,
            payload["department"]["version"] + 1,
            self.session,
        )

    async def verify_repair(self, recovery_id):
        from bisheng.core.context.tenant import get_current_tenant_id

        tenant_id = get_current_tenant_id()
        prepared = await self.ledger.record(recovery_id, tenant_id)
        completed = await self.ledger.record(recovery_id, tenant_id, stage="finalized")
        if prepared is None or completed is None or prepared["operation_id"] != completed["operation_id"]:
            raise RecoveryRuntimeError("SQL_COMMIT_NOT_VERIFIED_GATE_MAY_REMAIN_CLOSED")
        department, operation, _ = await self.load(prepared["preview"]["department_id"])
        if (
            department is None
            or operation is None
            or department["operation_id"] != prepared["operation_id"]
            or department["state"] != "CURRENT"
            or operation.status != "FINALIZED"
            or department["version"] != prepared["preview"]["department"]["version"] + 1
        ):
            raise RecoveryRuntimeError("SQL_COMMIT_NOT_VERIFIED")
        if not hasattr(self, "_finished_operations"):
            self._finished_operations = {}
        self._finished_operations[department["id"]] = int(operation.id)
