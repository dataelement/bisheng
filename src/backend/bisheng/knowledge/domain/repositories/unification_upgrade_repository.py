"""Unified CLI's immutable bindings in the existing tenant Run ledger."""

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.domain.repositories.unification_run_repository import (
    FrozenGlobalInventoryResult,
    KnowledgeUnificationRunRepository,
)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _reject(reason):
    raise KnowledgeOperationPlanConflictError(reason="migration_upgrade_" + reason)


@dataclass(frozen=True)
class UpgradeRunState:
    tenant_ids: tuple[int, ...]
    phases: tuple[tuple[int, str], ...]
    frozen: FrozenGlobalInventoryResult | None
    binding: dict | None
    reconciliation_refs: tuple[dict, ...] = ()
    created_at: str | None = None
    pending_intents: tuple[dict, ...] = ()
    positions: tuple[dict, ...] = ()

    @property
    def completed(self):
        return bool(self.phases) and all(phase == "completed" for _, phase in self.phases)

    @property
    def preparing(self):
        # Failed preparing is inspected through its immutable recovery phase;
        # it remains a replay of the original intent, never a fresh capture.
        return bool(self.phases) and self.frozen is None


class UpgradeRunRepository:
    def __init__(self):
        self.runs = KnowledgeUnificationRunRepository()

    async def aconnection_identity(self, session):
        from sqlalchemy import Column, MetaData, String, Table, inspect, select

        connection = await session.connection()
        url = session.get_bind().url
        endpoint = {
            "dialect": connection.dialect.name,
            "host": (url.host or "").casefold(),
            "port": url.port,
            "database": url.database or "",
        }

        def schema(sync_connection):
            inspector = inspect(sync_connection)
            names = set(inspector.get_table_names())
            rows = []
            for name in ("knowledge_unification_run", "knowledge_unification_executor_lock"):
                columns = inspector.get_columns(name) if name in names else []
                rows.append(
                    {
                        "table": name,
                        "columns": [
                            {"name": item["name"], "type": str(item["type"]), "nullable": item["nullable"]}
                            for item in columns
                        ],
                    }
                )
            return rows, "alembic_version" in names

        tables, has_head = await connection.run_sync(schema)
        required = {"id", "tenant_id", "create_time", "update_time"}
        actual = {
            column["name"]
            for table in tables
            if table["table"] == "knowledge_unification_executor_lock"
            for column in table["columns"]
        }
        if not required.issubset(actual):
            raise KnowledgeOperationPlanConflictError(reason="migration_executor_schema_not_ready")
        heads = []
        if has_head:
            table = Table("alembic_version", MetaData(), Column("version_num", String(128)))
            heads = sorted((await session.execute(select(table.c.version_num))).scalars())
        identity = {
            "database_fingerprint": hashlib.sha256(_canonical(endpoint).encode()).hexdigest(),
            "schema_digest": hashlib.sha256(_canonical({"tables": tables, "heads": heads}).encode()).hexdigest(),
        }
        return identity

    async def aload_state(self, session, *, run_id, writer_contract_version):
        tenants = await self.runs.alist_actual_tenant_ids(session)
        rows = []
        for tenant in tenants:
            with tenant_execution_scope(tenant):
                row = await self.runs.aget(session, run_id=run_id, writer_contract_version=writer_contract_version)
                if row is not None:
                    rows.append(row)
        if not rows:
            return UpgradeRunState(tenants, (), None, None)
        if tuple(row.tenant_id for row in rows) != tenants:
            _reject("mixed_global_state")
        effective = tuple(row.checkpoints.get("_failed_from_phase", row.phase) for row in rows)
        if any(phase == "preparing" for phase in effective) and not all(phase == "preparing" for phase in effective):
            _reject("mixed_global_state")
        if len({(row.baseline_hash, row.plan_hash) for row in rows}) != 1:
            _reject("global_evidence_changed")
        bindings = [row.checkpoints.get("preparing", {}).get("flow_identity_v1") for row in rows]
        if any(value != bindings[0] for value in bindings):
            _reject("global_binding_changed")
        binding = None
        if bindings[0] is not None:
            try:
                binding = json.loads(bindings[0]["cursor"])
                if (
                    _canonical(binding) != bindings[0]["cursor"]
                    or hashlib.sha256(_canonical(binding).encode()).hexdigest() != bindings[0]["digest"]
                ):
                    _reject("binding_changed")
            except (ValueError, TypeError, KeyError) as error:
                raise KnowledgeOperationPlanConflictError(reason="migration_upgrade_binding_changed") from error
        frozen = None
        if effective[0] != "preparing":
            frozen = FrozenGlobalInventoryResult(
                run_id, writer_contract_version, tenants, deepcopy(rows[0].baseline_ref), deepcopy(rows[0].plan_ref)
            )
        reconciliation = {}
        for row in rows:
            for checkpoints in row.checkpoints.values():
                if not isinstance(checkpoints, dict):
                    continue
                for key, value in checkpoints.items():
                    if not key.startswith("reconciliation_"):
                        continue
                    try:
                        item = json.loads(value["cursor"])
                        if (
                            set(item) != {"schema_version", "flow_ref"}
                            or item["schema_version"] != 1
                            or _canonical(item) != value["cursor"]
                            or hashlib.sha256(_canonical(item).encode()).hexdigest() != value["digest"]
                            or value["complete"] is not True
                            or value["processed_count"] != 1
                        ):
                            _reject("reconciliation_binding_invalid")
                        ref = item["flow_ref"]
                        if key != "reconciliation_" + ref["sha256"][:32]:
                            _reject("reconciliation_binding_invalid")
                        reconciliation[ref["sha256"]] = ref
                    except (ValueError, TypeError, KeyError) as error:
                        raise KnowledgeOperationPlanConflictError(
                            reason="migration_upgrade_reconciliation_binding_invalid"
                        ) from error
        from bisheng.knowledge.domain.repositories.unification_executor_repository import UnificationExecutorRepository

        pending = []
        positions = []
        for row in rows:
            latest = UnificationExecutorRepository._latest(row)
            if latest is not None and latest[2]["pending"] is not None:
                item = latest[2]["pending"]
                pending.append(
                    {
                        "tenant_id": row.tenant_id,
                        "kind": item["kind"],
                        "identity_digest": item["identity_digest"],
                        "outcome": item.get("outcome", "dispatched"),
                    }
                )
            for phase, checkpoints in row.checkpoints.items():
                if not isinstance(checkpoints, dict):
                    continue
                for key in (
                    "history_after_v1",
                    "sql_conversion",
                    "permission_namespace",
                    "permission_fga",
                    "permission_complete",
                    "references",
                    "references_retired",
                ):
                    value = checkpoints.get(key)
                    if value is not None:
                        positions.append(
                            {
                                "tenant_id": row.tenant_id,
                                "phase": phase,
                                "checkpoint": key,
                                "processed_count": value["processed_count"],
                                "complete": value["complete"],
                                "cursor_sha256": hashlib.sha256(value["cursor"].encode()).hexdigest()
                                if value["cursor"] is not None
                                else None,
                            }
                        )
        return UpgradeRunState(
            tenants,
            tuple((row.tenant_id, row.phase) for row in rows),
            frozen,
            binding,
            tuple(reconciliation[key] for key in sorted(reconciliation)),
            min(row.create_time for row in rows).isoformat(),
            tuple(pending),
            tuple(positions),
        )

    async def abind_preparing(self, session, *, run_id, writer_contract_version, tenant_ids, binding):
        cursor = _canonical(binding)
        value = {
            "cursor": cursor,
            "processed_count": 1,
            "digest": hashlib.sha256(cursor.encode()).hexdigest(),
            "complete": True,
        }
        for tenant in tenant_ids:
            with tenant_execution_scope(tenant):
                row = await self.runs._required(session, run_id, writer_contract_version)
                expected = row.checkpoints.get("preparing", {}).get("flow_identity_v1")
                if expected is not None and expected != value:
                    _reject("original_flow_changed")
                await self.runs.acheckpoint(
                    session,
                    run_id=run_id,
                    writer_contract_version=writer_contract_version,
                    baseline_hash=None,
                    plan_hash=None,
                    expected_phase="preparing",
                    checkpoint_key="flow_identity_v1",
                    expected_checkpoint=expected,
                    checkpoint=value,
                )

    async def aresume_failed(self, session, *, run_id, writer_contract_version, tenant_ids):
        for tenant in tenant_ids:
            with tenant_execution_scope(tenant):
                row = await self.runs._required(session, run_id, writer_contract_version)
                if row.phase == "failed":
                    await self.runs.aresume(
                        session,
                        run_id=run_id,
                        writer_contract_version=writer_contract_version,
                        baseline_hash=row.baseline_hash,
                        plan_hash=row.plan_hash,
                    )

    async def abind_reconciliation(self, session, *, run_id, writer_contract_version, tenant_ids, flow_ref):
        cursor = _canonical({"schema_version": 1, "flow_ref": flow_ref})
        digest = hashlib.sha256(cursor.encode()).hexdigest()
        value = {"cursor": cursor, "processed_count": 1, "digest": digest, "complete": True}
        key = "reconciliation_" + flow_ref["sha256"][:32]
        for tenant in tenant_ids:
            with tenant_execution_scope(tenant):
                row = await self.runs._required(session, run_id, writer_contract_version)
                if row.phase == "completed":
                    continue
                bound = [
                    json.loads(value["cursor"])["flow_ref"]
                    for checkpoints in row.checkpoints.values()
                    if isinstance(checkpoints, dict)
                    for old_key, value in checkpoints.items()
                    if old_key.startswith("reconciliation_")
                ]
                if bound:
                    if any(ref != flow_ref for ref in bound):
                        _reject("bound_reconciliation_changed")
                    continue
                expected = row.checkpoints.get(row.phase, {}).get(key)
                await self.runs.acheckpoint(
                    session,
                    run_id=run_id,
                    writer_contract_version=writer_contract_version,
                    baseline_hash=row.baseline_hash,
                    plan_hash=row.plan_hash,
                    expected_phase=row.phase,
                    checkpoint_key=key,
                    expected_checkpoint=expected,
                    checkpoint=value,
                )
