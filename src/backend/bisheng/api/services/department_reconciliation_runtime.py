"""SQL candidate selection and bounded per-department production repair reads.

No unfiltered FGA Read, tenant-wide member dump, or online dispatcher.
"""

import asyncio
import math

from bisheng.api.services.department_business_scan import structural_candidates
from bisheng.api.services.iam_department_repair_runtime import IamDepartmentRepairRuntime
from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id
from bisheng.department.domain.repositories.iam_archive_repository import IamArchiveDepartmentRepository
from bisheng.department.domain.services.current_projection_repair import CurrentDepartmentRepairService
from bisheng.department.domain.services.iam_archive_repair import IamArchiveDepartmentService
from bisheng.department.domain.services.iam_oneoff_repair import IamOneoffDepartmentService
from bisheng.permission.application.department_recovery_model import discover_batch_model
from bisheng.permission.application.department_recovery_runtime import abnormal_department
from bisheng.permission.domain.services.current_department_repair import MAX_KEYS, archive_owned_key
from bisheng.permission.domain.services.department_recovery_plan import (
    RecoveryBlockedError,
    RecoveryRuntimeError,
    checksum,
)
from bisheng.role.domain.repositories.department_retirement_repository import DepartmentRoleRetirementRepository
from scripts.iam_department_lookup import IamDepartmentNotFound


class DepartmentBatchRuntime(IamDepartmentRepairRuntime):
    def __init__(self, *args, scan_timeout=7200, relation_read_timeout=120, offline_maintenance=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.departments = IamArchiveDepartmentRepository()
        self.business = CurrentDepartmentRepairService(self.departments)
        self.iam_business = IamOneoffDepartmentService(self.departments)
        self.archive_roles = DepartmentRoleRetirementRepository()
        self.archive_business = IamArchiveDepartmentService(self.departments, self.archive_roles)
        self.archive_targets = set()
        self.dependency_preview = False
        self.scan_timeout = scan_timeout
        self.relation_read_timeout = relation_read_timeout
        self.enforce_prefetched_iam = True
        self.before_outside_transaction = True
        self.model_cache = {}
        self._coverage = {}
        self._observed_counts = {}
        self.offline_maintenance = offline_maintenance

    async def discover(self):
        async with asyncio.timeout(10):
            return await discover_batch_model(self.client._http, self.model_cache)

    def clear_inventory(self):
        # Proof caches are already scoped to a single _snapshot/current_business.
        # Never carry observed FGA relations across validation phases.
        return None

    async def prove_business(self, department, *, session=None, lock=False):
        if department["id"] in self.archive_targets:
            return await self._prove_current_archive(department, session=session, lock=lock)
        if department["status"] == "archived":
            if department["operation_id"]:
                operation = await self.projections.aget_operation(department["operation_id"])
                key = operation.idempotency_key if operation is not None else ""
                if (
                    operation is not None
                    and operation.operation_type == "DEPARTMENT_RECONCILE"
                    and key.startswith("f086:current:")
                ):
                    record = await self.record(key.removeprefix("f086:current:"))
                    if record is not None and record["preview"].get("archive"):
                        self.archive_targets.add(department["id"])
                        return await self._prove_current_archive(department, session=session, lock=lock)
            proof = await self.iam_business.prove_inactive(department, session=session, lock=lock)
            await self.departments.require_no_space_binding(department, session=session)
            associations, _ = await self.departments.archive_snapshot(
                department, self.archive_roles, session=session, lock=lock
            )
            if any(associations.values()):
                raise ValueError("INACTIVE_OWNER_CLEANUP_REQUIRED")
            return proof
        proof, patch = await super().prove_business(department, session=session, lock=lock)
        if not self.dependency_preview and not proof.get("iam_archive"):
            ancestors = await self.departments.ancestors(proof["department"], session=session, lock=lock)
            if any(row["state"] != "CURRENT" for row in ancestors):
                raise ValueError("ANCESTOR_DEPENDENCY_NOT_CURRENT")
        return proof, patch

    async def _prove_current_archive(self, department, *, session=None, lock=False):
        if self.iam_lookup is None:
            raise RecoveryBlockedError("IAM_CONFIG_REQUIRED_FOR_UNPROVEN_BUSINESS")
        source = await self.departments.identity(department["id"], session=session, lock=lock)
        if source["source"] != self.iam_lookup.local_source:
            raise ValueError("ARCHIVE_LOCAL_SOURCE_CHANGED")
        try:
            if lock:
                self.iam_lookup.cached_department(source["external_id"])
            else:
                await self.iam_lookup.department(source["external_id"])
        except IamDepartmentNotFound as exc:
            return await self.prove_archive(department, source, exc.evidence, session=session, lock=lock)
        raise ValueError("ARCHIVE_IAM_DEPARTMENT_REAPPEARED")

    async def prove_archive(self, department, source, evidence, *, session, lock=False):
        if source["source"] != self.iam_lookup.local_source:
            raise ValueError("ARCHIVE_LOCAL_SOURCE_CHANGED")
        self.archive_targets.add(department["id"])
        return await self.archive_business.prove(
            department, source, evidence, self.iam_lookup.source_fingerprint, session=session, lock=lock
        )

    async def _snapshot(self, environment, department, session, *, lock):
        with self.departments.read_scope():
            result = await super()._snapshot(environment, department, session, lock=lock)
            ancestors = (
                []
                if result["business"].get("inactive_cleanup") or result["business"].get("iam_archive")
                else await self.departments.ancestors(result["business"]["department"], session=session, lock=lock)
            )
            result["ancestor_ids"] = [row["id"] for row in ancestors]
            result["pending_ancestors"] = [row["id"] for row in ancestors if row["state"] != "CURRENT"]
            result["ancestor_rows"] = ancestors
            return result

    async def required_dependencies(self, current):
        rows = [row for row in current["ancestor_rows"] if row["tenant_id"] == get_current_tenant_id()]
        ids = sorted({row["operation_id"] for row in rows if row["operation_id"]})
        metadata = await self.projections.aget_bound_operation_metadata(ids)
        return {row["id"] for row in rows if abnormal_department(row, metadata)} | set(current["pending_ancestors"])

    async def current_business(self, identity, *, lock=False):
        with self.departments.read_scope():
            return await super().current_business(identity, lock=lock)

    async def observed(self, identity, *, include_admin=False):
        gate = getattr(self, "_gate_payload_hint", None)
        if gate is not None and self.session is not None and gate["department_id"] == identity:
            # T1 establishes only the gate; T2 still reads actual FGA before
            # writing and verifies it afterwards, including unknown outcomes.
            return frozenset(tuple(key) for key in gate["observed"])
        keys = await super().observed(identity, include_admin=include_admin)
        if identity in self.archive_targets and not include_admin:
            present = set(keys)
            async with asyncio.timeout(self.relation_read_timeout):
                async for row in self.client.iter_tuples(
                    object=f"department:{identity}", relation="admin", consistency="HIGHER_CONSISTENCY"
                ):
                    key = row.get("user", ""), row.get("relation", ""), row.get("object", "")
                    if row.get("condition") or not archive_owned_key(key, identity):
                        raise RecoveryBlockedError("ARCHIVE_UNSUPPORTED_ADMIN_RELATION")
                    present.add(key)
                    if len(present) > MAX_KEYS:
                        raise RecoveryBlockedError("ARCHIVE_OWNED_SCOPE_TOO_LARGE")
            keys = frozenset(present)
        self._observed_counts[identity] = len(keys)
        self._coverage.update(
            fga_departments_read=len(self._observed_counts),
            fga_owned_keys_read=sum(self._observed_counts.values()),
        )
        return keys

    async def prepare_external_facts(self, payload):
        if self.iam_lookup is None and (payload.get("archive") or payload["business"].get("iam")):
            raise RecoveryBlockedError("IAM_CONFIG_REQUIRED_FOR_UNPROVEN_BUSINESS")
        # Network-only IAM input is fetched before SQL locks. The locked proof
        # repeats identity/structure/member checks, using only cached IAM data.
        if payload.get("archive"):
            expected = payload["business"]["iam_archive"]
            source = await self.departments.identity(payload["department_id"])
            if source != expected["local_identity"] or source["source"] != self.iam_lookup.local_source:
                raise RecoveryBlockedError("ARCHIVE_LOCAL_IDENTITY_CHANGED")
            try:
                await self.iam_lookup.refresh_department(source["external_id"])
            except IamDepartmentNotFound as exc:
                if exc.evidence != expected["evidence"]:
                    raise RecoveryBlockedError("ARCHIVE_DELETION_EVIDENCE_CHANGED") from exc
                self.archive_targets.add(payload["department_id"])
            else:
                raise RecoveryBlockedError("ARCHIVE_IAM_DEPARTMENT_REAPPEARED")
        elif payload["business"].get("iam"):
            expected = payload["business"]["iam"]
            self.iam_targets.add(payload["department_id"])
            source = await self.departments.identity(payload["department_id"])
            if source != expected["local_identity"]:
                raise RecoveryBlockedError("IAM_LOCAL_IDENTITY_CHANGED")
            item = await self.iam_lookup.department(source["external_id"])
            parent = await self.iam_lookup.department(item["parentid"])
            if item != expected["department"] or parent != expected["parent"]:
                raise RecoveryBlockedError("IAM_FACTS_CHANGED_REQUIRES_DRY_RUN")

    def validate_item_budget(self, payload):
        # T2 includes before+after owned reads, optional atomic write, and two
        # bounded Store/latest-model requests. Do not commit a gate when even
        # the minimum request spacing cannot fit the retained 15s transaction.
        def pages(keys):
            relations = (
                ("parent", "child", "member", "admin")
                if payload.get("archive") or payload.get("business", {}).get("inactive_cleanup")
                else ("parent", "child", "member")
            )
            counts = [sum(key[1] == relation for key in keys) for relation in relations]
            return sum(max(1, math.ceil(count / 100)) for count in counts)

        reads = pages(payload["observed"]) + pages(payload["target"])
        minimum = max(0, reads + bool(payload["correction"]) + 2 - 1) * self.limiter.interval
        if payload["classification"] != "ALREADY_DONE" and minimum > 12:
            raise RecoveryBlockedError("ITEM_READ_BUDGET_EXCEEDS_SHORT_TRANSACTION")

    async def inventory(self, audit, *, requested_ids=None, include_requested=True):
        """Full SQL thin scan, or explicit IDs+ancestors; never reads FGA/IAM."""
        self._observed_counts = {}
        async with asyncio.timeout(self.scan_timeout):
            environment = await self.environment(refresh=True)
            tenant = get_current_tenant_id()
            rows, cursor, upper = {}, 0, None
            if requested_ids is None:
                upper = await self.departments.high_water()
                while cursor < upper:
                    page = await self.departments.page(cursor, upper, 500)
                    if not page:
                        break
                    rows.update((row["id"], row) for row in page)
                    cursor = page[-1]["id"]
                    if len(rows) > 200000:
                        raise RecoveryRuntimeError("BATCH_INVENTORY_DEPARTMENT_LIMIT_200000")
                    audit.emit("scan_sql_progress", departments=len(rows), cursor=cursor)
            else:
                rows.update(await self.departments.get_many(requested_ids))
            attempted = set(rows)
            rounds = 0
            with bypass_tenant_filter():
                while (
                    missing := {row["parent_id"] for row in rows.values() if row["parent_id"] is not None} - attempted
                ):
                    rounds += 1
                    attempted.update(missing)
                    if rounds > 100 or len(attempted) - len(rows) > 10000 or len(attempted) > 200000:
                        raise RecoveryRuntimeError("BATCH_ANCESTRY_SCOPE_LIMIT")
                    rows.update(await self.departments.get_many(missing))
            selected = {identity for identity, row in rows.items() if row["tenant_id"] == tenant}
            metadata = {}
            operations = sorted(
                {rows[identity]["operation_id"] for identity in selected if rows[identity]["operation_id"]}
            )
            for start in range(0, len(operations), 500):
                metadata.update(await self.projections.aget_bound_operation_metadata(operations[start : start + 500]))
            candidates = structural_candidates(rows, selected)
            candidates.update(identity for identity in selected if abnormal_department(rows[identity], metadata))
            candidates.update(
                identity for identity in selected if rows[identity]["status"] not in {"active", "archived"}
            )
            if requested_ids is None:
                # Only department IDs, not every user's membership records.
                candidates.update((await self.departments.inactive_membership_departments()) & selected)
            elif include_requested:
                candidates.update(requested_ids)
            ancestor_impacts = {}
            for identity in selected:
                if rows[identity]["status"] != "active":
                    continue
                current, seen = rows[identity]["parent_id"], set()
                while current is not None and current in rows and current not in seen and len(seen) < 100:
                    seen.add(current)
                    if rows[current]["state"] != "CURRENT":
                        ancestor_impacts[identity] = current
                        break
                    current = rows[current]["parent_id"]
            # An ancestor's gate does not make every CURRENT descendant a new
            # owned-tuple repair. Report its impact without reading that subtree.
            passive = sorted(set(ancestor_impacts) - candidates)
            for start in range(0, len(passive), 500):
                audit.emit(
                    "scan_ancestor_gate_impact",
                    departments=[
                        {"department_id": identity, "blocking_ancestor_id": ancestor_impacts[identity]}
                        for identity in passive[start : start + 500]
                    ],
                    owned_relations_audited=False,
                )
            if await self.environment(refresh=True) != environment:
                raise RecoveryRuntimeError("BATCH_INVENTORY_MODEL_CHANGED")
            self._coverage = {
                "tenant_id": tenant,
                "selection": "sql_anomalies" if requested_ids is None else "explicit_ids_and_ancestors",
                "department_count": len(selected),
                "department_ids_checksum": checksum(sorted(selected)),
                "high_water": upper,
                "sql_scope_complete": True,
                "ancestor_gate_only_count": len(passive),
                "ancestor_gate_only_ids_checksum": checksum(passive),
                "fga_store_scan": False,
                "fga_audit_scope": "candidate_department_owned_relations",
                "fga_departments_read": 0,
                "fga_owned_keys_read": 0,
            }
            return {"environment": environment, "coverage": self._coverage, "candidates": candidates, "rows": rows}

    def offline_final_verify(self, indexed, expected_operations, inventory):
        remaining = set(inventory["candidates"])
        for identity, entry in indexed.items():
            payload = entry["preview"]
            expected = payload.get("archive", payload.get("reparent", {})).get("target", payload["department"])
            row = inventory["rows"].get(identity)
            fields = (
                "id",
                "tenant_id",
                "parent_id",
                "path",
                "status",
                "deleted",
                "is_tenant_root",
                "mounted_tenant_id",
            )
            version = payload["department"]["version"] + (payload["classification"] != "ALREADY_DONE")
            if (
                row is None
                or any(row[key] != expected[key] for key in fields)
                or row["state"] != "CURRENT"
                or row["version"] != version
                or identity not in expected_operations
                or row["operation_id"] != expected_operations[identity]
            ):
                remaining.add(identity)
        inventory["coverage"]["verification_mode"] = "offline_per_item_fga_and_receipt_then_sql_final"
        return remaining

    async def preflight_record(self, record, payload, current):
        from bisheng.permission.application.current_department_repair import CurrentDepartmentRepairApplication

        CurrentDepartmentRepairApplication.validate_confirmation(record["preview"])
        if checksum(record["preview"]) != checksum(payload):
            raise RecoveryBlockedError("BATCH_SHARED_RECORD_PREVIEW_MISMATCH")
        if (
            current["environment"] != payload["environment"]
            or checksum(current["business"]) != payload["business_checksum"]
        ):
            raise RecoveryBlockedError("BATCH_RESUME_BUSINESS_OR_MODEL_CHANGED")
        row, operation_id = current["department"], record["operation_id"]
        target_business = payload.get("archive", payload.get("reparent", {})).get("target", payload["department"])
        if payload.get("archive"):
            await self.validate_archive_record(record, current)
        if row["operation_id"] != operation_id or row["state"] not in {"FAILED_CLOSED", "CURRENT"}:
            raise RecoveryBlockedError("BATCH_RESUME_BINDING_NOT_OWNED")
        if row["state"] == "FAILED_CLOSED" and (
            record.get("window_id") != self.window_id or record.get("backup_evidence") != self.backup_evidence
        ):
            raise RecoveryBlockedError("BATCH_RESUME_WINDOW_OR_BACKUP_CHANGED")
        expected_version = payload["department"]["version"] + (1 if row["state"] == "CURRENT" else 0)
        if (
            row["version"] != expected_version
            or row["parent_id"] != target_business["parent_id"]
            or row["path"] != target_business["path"]
        ):
            raise RecoveryBlockedError("BATCH_RESUME_DEPARTMENT_CHANGED")
        if current["observed"] not in (
            {tuple(key) for key in payload["observed"]},
            {tuple(key) for key in payload["target"]},
        ):
            raise RecoveryBlockedError("BATCH_RESUME_THIRD_RELATION_STATE")

    async def validate_archive_record(self, record, current):
        payload = record["preview"]
        actual = current.get("archive")
        if actual is None or current["department"]["status"] != "archived" or current["department"]["deleted"] != 1:
            raise RecoveryBlockedError("ARCHIVE_PREPARED_LIFECYCLE_CHANGED")
        expected = (
            {key: [] for key in payload["archive"]["before"]}
            if current["department"]["state"] == "CURRENT"
            else payload["archive"]["before"]
        )
        if actual["before"] != expected:
            raise RecoveryBlockedError("ARCHIVE_ASSOCIATIONS_CHANGED")
