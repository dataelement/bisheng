"""V6 query shape, offline mixed resume and fail-closed completion evidence."""

from copy import deepcopy

import pytest
import sqlalchemy as sa

from bisheng.core.context import tenant as tenant_context
from bisheng.core.database.tenant_filter import register_tenant_filter_events
from bisheng.permission.application.department_batch_repair import DepartmentBatchRepairApplication
from bisheng.permission.application.department_recovery_runtime import tenant_scope
from bisheng.permission.domain.models import PermissionProjectionOperation
from bisheng.permission.domain.repositories.current_department_repair_repository import CurrentDepartmentRepairLedger
from bisheng.permission.domain.services.current_department_repair import ACTIVE
from bisheng.permission.domain.services.department_recovery_plan import RecoveryBlockedError
from scripts.department_batch_io import read_batch_plan, write_batch_plan
from scripts.reconcile_department_projections import parse_args
from test.permission import test_f086_current_department_repair_repository as repo_tests
from test.permission import test_f086_department_batch_repair as batch


@pytest.fixture
async def database():
    async for factory in repo_tests.database.__wrapped__():
        yield factory


async def extra(factory, count, *, tenant_id=1):
    async with factory() as session:
        original = await session.get(PermissionProjectionOperation, 9)
        for index in range(count):
            row = original.model_dump() | {
                "id": (100 if tenant_id == 1 else 1000) + index,
                "tenant_id": tenant_id,
                "idempotency_key": f"hotfix-{tenant_id}-{index}",
                "status": sorted(ACTIVE)[index % len(ACTIVE)],
            }
            row.pop("create_time", None)
            row.pop("update_time", None)
            session.add(PermissionProjectionOperation(**row))
        await session.commit()


async def test_active_probes_are_skinny_equalities_and_tenant_filtered(database):
    await repo_tests.seed(database)
    await extra(database, 3)
    await extra(database, 1, tenant_id=2)
    register_tenant_filter_events()
    captured = []
    async with database() as session:
        engine = session.get_bind()

        def capture(connection, cursor, statement, parameters, context, executemany):
            captured.append((statement, parameters))

        sa.event.listen(engine, "before_cursor_execute", capture)
        token = tenant_context._bypass_tenant_filter.set(False)
        try:
            with tenant_scope(1):
                ids = await CurrentDepartmentRepairLedger(database).active_operation_ids({"id": 42}, session=session)
            assert ids == [9, 100, 101, 102]
        finally:
            tenant_context._bypass_tenant_filter.reset(token)
            sa.event.remove(engine, "before_cursor_execute", capture)
    probes = [sql for sql, _ in captured if "permission_projection_operation.status =" in sql]
    assert len(probes) == 4
    for sql in probes:
        assert "permission_projection_operation.tenant_id =" in sql
        assert "ORDER BY" not in sql and "status IN" not in sql
        assert sql.startswith("SELECT permission_projection_operation.id ")


@pytest.mark.parametrize("total", [32, 33])
async def test_limit_is_across_all_four_statuses_without_truncation(database, total):
    await repo_tests.seed(database)
    await extra(database, total - 1)
    async with database() as session:
        ledger = CurrentDepartmentRepairLedger(database)
        if total == 33:
            with pytest.raises(RecoveryBlockedError, match="TOO_MANY_PENDING"):
                await ledger.active_operation_ids({"id": 42}, session=session)
        else:
            assert len(await ledger.active_operation_ids({"id": 42}, session=session)) == 32


async def test_offline_resume_skips_completed_scope_probe_and_t1_fga(database, monkeypatch, tmp_path):
    await batch.composition.seed(database)
    await batch.make_pending_parent(database)
    client, audit = batch.FGA(), batch.Audit()
    backend = batch.runtime(database, client, monkeypatch)
    app = DepartmentBatchRepairApplication(backend)
    with tenant_scope(1):
        plan = await app.scan(audit)
        assert plan["format"] == "cofco.department-recovery.v1"
        path = tmp_path / "v5-plan.jsonl"
        write_batch_plan(path, plan)
        frozen = deepcopy(plan)
        parent = next(row["preview"] for row in plan["entries"] if row["department_id"] == 3)
        await app.single.recover_department(parent, audit)
        writes, version = client.writes, (await backend.departments.get(3))["version"]
        resumed = batch.runtime(database, client, monkeypatch)
        resumed.offline_maintenance = True
        active = resumed.ledger.active_operation_ids

        async def no_completed_probe(department, **kwargs):
            assert department["id"] != 3, "completed scope must use its PK receipts"
            return await active(department, **kwargs)

        monkeypatch.setattr(resumed.ledger, "active_operation_ids", no_completed_probe)
        client.queries.clear()
        result = await DepartmentBatchRepairApplication(resumed).apply(read_batch_plan(path), audit)
        assert result["complete"] and result["repaired_operations"] == 1
        assert result["results"][3] == "ALREADY_DONE" and client.writes == writes + 1
        assert (await resumed.departments.get(3))["version"] == version
        assert len(client.queries) == 12  # preflight both; T2 before/after child only
        assert result["verification"]["verification_mode"].startswith("offline_")
        assert read_batch_plan(path) == frozen
        assert any(event == "batch_preflight_completed" for event, _ in audit.events)
        assert all("elapsed_seconds" in fields for event, fields in audit.events if event == "item_result")


async def test_t1_reuses_its_locked_sources_but_not_next_transaction(database, monkeypatch):
    await batch.composition.seed(database)
    client, audit = batch.FGA(), batch.Audit()
    backend = batch.runtime(database, client, monkeypatch)
    with tenant_scope(1):
        payload = (
            await DepartmentBatchRepairApplication(backend).single.inspect_department(batch.composition.IDENTITY)
        ).payload
        original = backend.ledger.operations
        calls = []

        async def operations(department, **kwargs):
            if kwargs.get("lock"):
                calls.append(kwargs["session"])
            return await original(department, **kwargs)

        monkeypatch.setattr(backend.ledger, "operations", operations)
        await DepartmentBatchRepairApplication(backend).single.recover_department(payload, audit)
        assert len(calls) == 2 and calls[0] is not calls[1]  # exactly T1 and T2


async def test_completed_fast_path_refuses_missing_finalized_receipt(database, monkeypatch):
    await batch.composition.seed(database)
    client, audit = batch.FGA(), batch.Audit()
    backend = batch.runtime(database, client, monkeypatch)
    app = DepartmentBatchRepairApplication(backend)
    with tenant_scope(1):
        plan = await app.scan(audit)
        await app.apply(plan, audit)
        writes = client.writes
        resumed = batch.runtime(database, client, monkeypatch)
        resumed.offline_maintenance = True
        original = resumed.ledger.record

        async def missing(*args, **kwargs):
            return None if kwargs.get("stage") == "finalized" else await original(*args, **kwargs)

        monkeypatch.setattr(resumed.ledger, "record", missing)
        with pytest.raises(RecoveryBlockedError, match="COMPLETION_EVIDENCE_MISSING"):
            await DepartmentBatchRepairApplication(resumed).apply(plan, audit)
        assert client.writes == writes


def test_high_qps_requires_explicit_offline_apply_and_all_confirmations():
    base = ["--environment-id", "test", "--tenant-id", "1", "--iam-config", "iam", "--output-dir", "unused"]
    with pytest.raises(SystemExit):
        parse_args([*base, "--scan-departments", "--max-fga-qps", "20"])
    confirmed = [
        *base,
        "--plan-file",
        "v5-plan",
        "--apply",
        "--confirm-writers-idle",
        "--confirm-store-id",
        "s",
        "--confirm-model-id",
        "m",
        "--confirm-plan-checksum",
        "hash",
        "--backup-evidence",
        "backup",
        "--window-id",
        "window",
        "--max-fga-qps",
        "20",
    ]
    with pytest.raises(SystemExit):
        parse_args(confirmed)
    assert parse_args([*confirmed, "--offline-maintenance"]).max_fga_qps == 20
    with pytest.raises(SystemExit):
        parse_args([*confirmed, "--offline-maintenance", "--max-fga-qps", "21"])


async def test_offline_sql_failure_resumes_v5_plan_without_rewriting_fga(database, monkeypatch):
    await batch.composition.seed(database)
    await batch.make_pending_parent(database)
    client, audit = batch.FGA(), batch.Audit()
    backend = batch.runtime(database, client, monkeypatch)
    backend.offline_maintenance = True
    app = DepartmentBatchRepairApplication(backend)
    with tenant_scope(1):
        plan = await app.scan(audit)
        finish = backend.departments.finish

        async def fail_child(before, *args):
            if before["id"] == batch.composition.IDENTITY:
                raise RuntimeError("injected child finalize failure")
            return await finish(before, *args)

        monkeypatch.setattr(backend.departments, "finish", fail_child)
        with pytest.raises(RuntimeError, match="finalize failure"):
            await app.apply(plan, audit)
        writes = client.writes
        assert (await backend.departments.get(3))["state"] == "CURRENT"
        assert (await backend.departments.get(batch.composition.IDENTITY))["state"] == "FAILED_CLOSED"
        resumed = batch.runtime(database, client, monkeypatch)
        resumed.offline_maintenance = True
        result = await DepartmentBatchRepairApplication(resumed).apply(plan, audit)
        assert result["complete"] and result["repaired_operations"] == 1
        assert client.writes == writes


async def test_offline_t1_skip_never_bypasses_t2_actual_relation_validation(database, monkeypatch):
    from bisheng.permission.domain.services.department_recovery_plan import RecoveryRuntimeError

    await batch.composition.seed(database)
    client, audit = batch.FGA(), batch.Audit()
    backend = batch.runtime(database, client, monkeypatch)
    backend.offline_maintenance = True
    app = DepartmentBatchRepairApplication(backend)
    with tenant_scope(1):
        plan = await app.scan(audit)
        prepare = backend.prepare

        async def third_state(payload):
            await prepare(payload)
            client.keys.add(("user:777", "member", f"department:{batch.composition.IDENTITY}"))

        monkeypatch.setattr(backend, "prepare", third_state)
        with pytest.raises(RecoveryRuntimeError, match="THIRD_TOPOLOGY_STATE"):
            await app.apply(plan, audit)
        assert client.writes == 0
        assert (await backend.departments.get(batch.composition.IDENTITY))["state"] == "FAILED_CLOSED"
