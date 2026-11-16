"""Approve one complete repair graph, then execute it without inventing new targets."""

import asyncio
import heapq
import time
from collections import defaultdict
from contextlib import contextmanager

from bisheng.permission.application.current_department_repair import CurrentDepartmentRepairApplication
from bisheng.permission.domain.services.department_recovery_plan import (
    RecoveryBlockedError,
    RecoveryRuntimeError,
    checksum,
)
from bisheng.permission.domain.services.projection_diagnostics import (
    emit_projection_alert,
    reason_from_exception,
    relation_diagnostics,
)

BATCH_FORMAT = "cofco.department-recovery.v1"
SUCCESS = frozenset({"FINALIZED", "ALREADY_DONE", "DEPENDENCY_RESOLVED"})


@contextmanager
def preview_mode(backend):
    previous = backend.dependency_preview
    backend.dependency_preview = True
    try:
        yield
    finally:
        backend.dependency_preview = previous


def execution_order(entries):
    """True dependency order, independent of numerical department IDs."""
    indexed = {item["department_id"]: item for item in entries}
    pending = {identity: set(row["dependencies"]) for identity, row in indexed.items() if row["status"] != "BLOCKED"}
    dependents = defaultdict(set)
    for identity, deps in pending.items():
        for dep in deps:
            dependents[dep].add(identity)
    ready = [identity for identity, deps in pending.items() if not deps]
    heapq.heapify(ready)
    order = []
    while ready:
        identity = heapq.heappop(ready)
        order.append(identity)
        for other in dependents[identity]:
            pending[other].remove(identity)
            if not pending[other]:
                heapq.heappush(ready, other)
    return order, set(pending) - set(order)


def build_plan(environment, scope, entries):
    indexed = {row["department_id"]: row for row in entries}
    if len(indexed) != len(entries):
        raise RecoveryRuntimeError("BATCH_DUPLICATE_DEPARTMENT")
    for row in entries:
        if row["status"] == "BLOCKED":
            continue
        row["dependencies"] = sorted(
            {
                identity
                for identity in row.pop("ancestor_ids", [])
                if identity in indexed
                and (indexed[identity].get("preview") or {}).get("classification") != "ALREADY_DONE"
            }
            | set(row.pop("pending_ancestors", []))
        )
        if any(identity not in indexed for identity in row["dependencies"]):
            row.update(status="BLOCKED", reason="DEPENDENCY_OUTSIDE_CONFIRMED_SCOPE")
        elif any((indexed[identity].get("preview") or {}).get("archive") for identity in row["dependencies"]):
            row.update(status="BLOCKED", reason="DEPENDENCY_IS_RETIRING")
        elif any((indexed[identity].get("preview") or {}).get("reparent") for identity in row["dependencies"]):
            # This one-off tool cannot pre-authorize a second business path from
            # a moving ancestor's old path. Never mark that case fully repairable.
            row.update(status="BLOCKED", reason="DEPENDENCY_BUSINESS_MOVE_REQUIRES_OWNER_PLAN")
        elif row["dependencies"]:
            row["status"] = "AFTER_DEPENDENCIES"
    while True:
        changed = False
        for row in entries:
            if row["status"] != "BLOCKED" and any(indexed[d]["status"] == "BLOCKED" for d in row["dependencies"]):
                row.update(status="BLOCKED", reason="DEPENDENCY_NOT_REPAIRABLE")
                changed = True
        if not changed:
            break
    order, unresolved = execution_order(entries)
    for identity in unresolved:
        indexed[identity].update(status="BLOCKED", reason="DEPENDENCY_CYCLE_OR_UNRESOLVED")
    if unresolved:
        order, _ = execution_order(entries)
    core = {
        "format": BATCH_FORMAT,
        "environment": environment,
        "scope": scope,
        "entries": sorted(entries, key=lambda row: row["department_id"]),
        "execution_order": order,
        "complete": True,
        "all_repairable": not any(row["status"] == "BLOCKED" for row in entries),
    }
    return core | {"plan_checksum": checksum(core)}


def validate_plan(plan):
    core = {key: value for key, value in plan.items() if key != "plan_checksum"}
    if plan.get("format") != BATCH_FORMAT or plan.get("plan_checksum") != checksum(core) or not plan.get("complete"):
        raise RecoveryBlockedError("BATCH_PLAN_FORMAT_CHECKSUM_OR_COMPLETENESS_INVALID")
    entries = plan.get("entries", [])
    ids = [entry["department_id"] for entry in entries]
    if ids != sorted(set(ids)):
        raise RecoveryBlockedError("BATCH_PLAN_IDENTITIES_INVALID")
    for entry in entries:
        if entry.get("preview") is not None:
            CurrentDepartmentRepairApplication.validate_confirmation(entry["preview"])
            if entry["preview"]["department_id"] != entry["department_id"]:
                raise RecoveryBlockedError("BATCH_PREVIEW_IDENTITY_MISMATCH")
    order, unresolved = execution_order(entries)
    if unresolved or order != plan["execution_order"]:
        raise RecoveryBlockedError("BATCH_DEPENDENCY_ORDER_INVALID")


class DepartmentBatchRepairApplication:
    def __init__(self, backend):
        self.backend = backend
        self.single = CurrentDepartmentRepairApplication(backend)
        self._run_lock = asyncio.Lock()

    async def scan(self, audit, *, max_items=50000, requested_ids=None):
        async with self._run_lock:
            return await self._scan(audit, max_items=max_items, requested_ids=requested_ids)

    async def _scan(self, audit, *, max_items, requested_ids):
        inventory = await self.backend.inventory(audit, requested_ids=requested_ids)
        pending = set(inventory["candidates"] if requested_ids is None else requested_ids)
        if len(pending) > max_items:
            raise RecoveryRuntimeError("BATCH_SCAN_INCOMPLETE_ITEM_LIMIT")
        queue = list(pending)
        heapq.heapify(queue)
        entries, seen = [], set()
        with preview_mode(self.backend):
            try:
                while queue:
                    identity = heapq.heappop(queue)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    if len(seen) > max_items:
                        raise RecoveryRuntimeError("BATCH_SCAN_INCOMPLETE_ITEM_LIMIT")
                    try:
                        current = await self.backend.snapshot(identity)
                        preview = self.single.preview(current)
                        self.backend.validate_item_budget(preview)
                        if preview["classification"] != "ALREADY_DONE":
                            emit_projection_alert(
                                "INCONSISTENT",
                                reason_code="PERMISSION_TARGET_MISMATCH",
                                tenant_id=preview["tenant_id"],
                                department_id=identity,
                                operation_id=preview["department"]["operation_id"],
                                details=relation_diagnostics(current["observed"], {tuple(k) for k in preview["target"]})
                                | {
                                    "mode": "DRY_RUN",
                                    "current_state": preview["department"]["state"],
                                    "current_version": preview["department"]["version"],
                                },
                            )
                        if preview["classification"] == "PROCESSING":
                            raise RecoveryBlockedError("OPERATION_STILL_PROCESSING_REQUIRES_DRAIN")
                        row = {
                            "department_id": identity,
                            "status": "READY",
                            "dependencies": [],
                            "preview": preview,
                            "ancestor_ids": current["ancestor_ids"],
                            "pending_ancestors": current["pending_ancestors"],
                        }
                        dependencies = await self.backend.required_dependencies(current)
                        inventory["candidates"].update(dependencies)
                        for ancestor in dependencies - pending:
                            pending.add(ancestor)
                            heapq.heappush(queue, ancestor)
                    except RecoveryBlockedError as exc:
                        emit_projection_alert(
                            "MANUAL_REQUIRED",
                            reason_code=reason_from_exception(exc),
                            tenant_id=inventory["coverage"]["tenant_id"],
                            department_id=identity,
                            details={"mode": "DRY_RUN", "phase": "candidate_scan"},
                        )
                        row = {
                            "department_id": identity,
                            "status": "BLOCKED",
                            "dependencies": [],
                            "reason": str(exc),
                            "details": getattr(exc, "details", {}),
                        }
                    entries.append(row)
                    audit.emit("item_inspected", **row)
            finally:
                self.backend.clear_inventory()
        if await self.backend.environment(refresh=True) != inventory["environment"]:
            raise RecoveryRuntimeError("ENVIRONMENT_CHANGED_DURING_BATCH_SCAN")
        scope = inventory["coverage"] | {
            "iam_source_fingerprint": getattr(self.backend.iam_lookup, "source_fingerprint", None),
            "writers_idle_confirmed_at_scan": bool(getattr(self.backend, "writers_idle", False)),
            "requested_ids": sorted(set(requested_ids)) if requested_ids is not None else None,
        }
        return build_plan(inventory["environment"], scope, entries)

    async def apply(self, plan, audit, *, max_repairs=10000):
        async with self._run_lock:
            return await self._apply(plan, audit, max_repairs=max_repairs)

    async def _apply(self, plan, audit, *, max_repairs):
        validate_plan(plan)
        if not plan["all_repairable"] or any(row["status"] == "BLOCKED" for row in plan["entries"]):
            raise RecoveryBlockedError("BATCH_HAS_UNREPAIRABLE_ITEMS_NO_WRITES")
        if getattr(self.backend.iam_lookup, "source_fingerprint", None) != plan["scope"]["iam_source_fingerprint"]:
            raise RecoveryBlockedError("BATCH_IAM_SOURCE_CHANGED")
        work = sum(row["preview"]["classification"] != "ALREADY_DONE" for row in plan["entries"])
        if work > max_repairs:
            raise RecoveryBlockedError("BATCH_REPAIR_LIMIT_BEFORE_WRITES")
        indexed = {row["department_id"]: row for row in plan["entries"]}
        offline = getattr(self.backend, "offline_maintenance", False)
        completed_preflight = {}
        expected_operations = {}
        sql_scope = set(indexed)
        for entry in plan["entries"]:
            sql_scope.update(row["id"] for row in entry["preview"]["business"].get("ancestors", []))
        inventory = await self.backend.inventory(audit, requested_ids=sql_scope, include_requested=False)
        if inventory["environment"] != plan["environment"]:
            raise RecoveryBlockedError("BATCH_ENVIRONMENT_CHANGED")
        if (inventory["candidates"] & sql_scope) - indexed.keys():
            raise RecoveryBlockedError("NEW_DEPENDENCY_REQUIRES_DRY_RUN")
        preflight_started = time.monotonic()
        audit.emit("batch_preflight_started", item_count=len(plan["entries"]))
        with preview_mode(self.backend):
            try:
                # Validate the entire approved batch before the first T1 commit.
                for position, entry in enumerate(plan["entries"], 1):
                    item_started = time.monotonic()
                    audit.emit(
                        "batch_preflight_progress",
                        position=position,
                        item_count=len(plan["entries"]),
                        department_id=entry["department_id"],
                        phase="started",
                    )
                    payload = entry["preview"]
                    self.backend.validate_item_budget(payload)
                    await self.backend.prepare_external_facts(payload)
                    recorded = await self.backend.record(payload["recovery_id"])
                    current = await self.single.confirmed_snapshot(payload, recorded)
                    if (set(current["ancestor_ids"]) & inventory["candidates"]) - indexed.keys():
                        raise RecoveryBlockedError("NEW_DEPENDENCY_REQUIRES_DRY_RUN")
                    if recorded is None:
                        if self.single.preview(current)["confirmation_checksum"] != payload["confirmation_checksum"]:
                            raise RecoveryBlockedError("BATCH_FACTS_CHANGED_BEFORE_WRITES")
                    else:
                        await self.backend.preflight_record(recorded, payload, current)
                        if current["department"]["state"] == "CURRENT":
                            completed_preflight[entry["department_id"]] = current["department"]["operation_id"]
                    audit.emit(
                        "batch_preflight_progress",
                        position=position,
                        item_count=len(plan["entries"]),
                        department_id=entry["department_id"],
                        phase="completed",
                        elapsed_seconds=round(time.monotonic() - item_started, 3),
                    )
            finally:
                self.backend.clear_inventory()
        if await self.backend.environment(refresh=True) != plan["environment"]:
            raise RecoveryBlockedError("BATCH_ENVIRONMENT_CHANGED_BEFORE_WRITES")
        audit.emit(
            "batch_preflight_completed",
            item_count=len(plan["entries"]),
            elapsed_seconds=round(time.monotonic() - preflight_started, 3),
        )
        results = {}
        for identity in plan["execution_order"]:
            item_started = time.monotonic()
            audit.emit(
                "batch_item_started",
                department_id=identity,
                completed_count=len(results),
                item_count=len(plan["entries"]),
            )
            entry = indexed[identity]
            if any(results.get(dep) not in SUCCESS for dep in entry["dependencies"]):
                raise RecoveryRuntimeError("BATCH_DEPENDENCY_NOT_COMPLETED_STOP")
            try:
                if offline and identity in completed_preflight:
                    result = "ALREADY_DONE"
                    expected_operations[identity] = completed_preflight[identity]
                elif entry["preview"]["classification"] == "ALREADY_DONE":
                    result = "DEPENDENCY_RESOLVED" if entry["dependencies"] else "ALREADY_DONE"
                    expected_operations[identity] = entry["preview"]["department"]["operation_id"]
                else:
                    result = await self.single.recover_department(entry["preview"], audit)
                    if offline:
                        finished = getattr(self.backend, "_finished_operations", {})
                        if identity not in finished:
                            raise RecoveryRuntimeError("OFFLINE_COMPLETION_IDENTITY_MISSING")
                        expected_operations[identity] = finished[identity]
                if result not in SUCCESS:
                    raise RecoveryRuntimeError("BATCH_ITEM_NOT_CURRENT_STOP")
                results[identity] = result
                audit.emit(
                    "item_result",
                    department_id=identity,
                    status=result,
                    elapsed_seconds=round(time.monotonic() - item_started, 3),
                )
            except BaseException as exc:
                audit.emit(
                    "batch_interrupted",
                    complete=False,
                    department_id=identity,
                    completed_ids=sorted(results),
                    reason=type(exc).__name__,
                )
                raise
        audit.emit("batch_final_verify_started", item_count=len(indexed))
        final = await self.backend.inventory(audit, requested_ids=sql_scope, include_requested=False)
        try:
            if final["environment"] != plan["environment"]:
                raise RecoveryRuntimeError("BATCH_MODEL_CHANGED_AT_FINAL_VERIFY")
            remaining = (set(final["candidates"]) & sql_scope) - indexed.keys()
            if offline:
                remaining.update(self.backend.offline_final_verify(indexed, expected_operations, final))
            for identity in [] if offline else sorted(indexed):
                try:
                    payload = indexed[identity]["preview"]
                    recorded = await self.backend.record(payload["recovery_id"])
                    current = await self.single.confirmed_snapshot(payload, recorded)
                    if self.single.preview(current)["classification"] != "ALREADY_DONE":
                        remaining.add(identity)
                except RecoveryBlockedError as exc:
                    remaining.add(identity)
                    audit.emit("final_item_blocked", department_id=identity, reason=str(exc))
            remaining = sorted(remaining)
            if await self.backend.environment(refresh=True) != plan["environment"]:
                raise RecoveryRuntimeError("BATCH_MODEL_CHANGED_AT_FINAL_VERIFY")
        finally:
            self.backend.clear_inventory()
        return {
            "complete": not remaining,
            "repaired_operations": sum(value == "FINALIZED" for value in results.values()),
            "results": results,
            "remaining_department_ids": remaining,
            "verification": final["coverage"],
        }
