"""One approved batch resolves projection dependencies before IAM reparent."""

import json
from copy import deepcopy

import pytest

from bisheng.api.services.department_reconciliation_runtime import DepartmentBatchRuntime
from bisheng.permission.application.department_batch_repair import (
    DepartmentBatchRepairApplication,
    build_plan,
    validate_plan,
)
from bisheng.permission.application.department_recovery_runtime import tenant_scope
from bisheng.permission.domain.services.department_recovery_plan import RecoveryBlockedError
from scripts.department_batch_io import read_batch_plan, write_batch_plan
from test.permission import test_f086_iam_department_repair_runtime as composition


@pytest.fixture
async def database():
    async for factory in composition.repository_tests.database.__wrapped__():
        yield factory


class Audit:
    def __init__(self):
        self.events = []

    def emit(self, event, **fields):
        self.events.append((event, fields))

    async def before(self, payload):
        self.events.append(("before", {"department_id": payload["department_id"]}))


class FGA(composition.FGA):
    def __init__(self):
        super().__init__()
        self.queries = []

    async def iter_tuples(self, **query):
        assert "relation" in query, "unfiltered Store reads are forbidden"
        self.queries.append(dict(query))
        async for row in super().iter_tuples(**query):
            yield row


def runtime(factory, client, monkeypatch):
    backend = composition.runtime(factory, client, monkeypatch)
    backend.__class__ = DepartmentBatchRuntime
    from bisheng.department.domain.repositories.iam_archive_repository import IamArchiveDepartmentRepository
    from bisheng.department.domain.services.current_projection_repair import CurrentDepartmentRepairService
    from bisheng.department.domain.services.iam_archive_repair import IamArchiveDepartmentService
    from bisheng.department.domain.services.iam_oneoff_repair import IamOneoffDepartmentService
    from bisheng.role.domain.repositories.department_retirement_repository import DepartmentRoleRetirementRepository

    backend.departments = IamArchiveDepartmentRepository(factory)
    backend.business = CurrentDepartmentRepairService(backend.departments)
    backend.iam_business = IamOneoffDepartmentService(backend.departments)
    backend.archive_roles = DepartmentRoleRetirementRepository()
    backend.archive_business = IamArchiveDepartmentService(backend.departments, backend.archive_roles)
    backend.archive_targets = set()
    backend.dependency_preview = False
    backend.scan_timeout = 30
    backend.relation_read_timeout = 120
    backend.enforce_prefetched_iam = True
    backend.before_outside_transaction = True
    backend.model_cache = {}
    backend._coverage = {}
    backend._observed_counts = {}
    from types import SimpleNamespace

    backend.limiter = SimpleNamespace(interval=0.5)
    cached = {}
    original = backend.iam_lookup.department.side_effect

    async def lookup(identity):
        cached[identity] = original(identity)
        return dict(cached[identity])

    backend.iam_lookup.department.side_effect = lookup
    backend.iam_lookup.cached_department = lambda identity: dict(cached[identity])
    return backend


async def make_pending_parent(factory):
    from bisheng.database.models.department import Department

    async with factory() as db:
        row = await db.get(Department, 3)
        row.permission_projection_state = "FAILED_CLOSED"
        db.add(row)
        await db.commit()


async def test_dryrun_all_dependencies_then_one_apply_finishes_every_item(database, monkeypatch, tmp_path):
    await composition.seed(database)
    await make_pending_parent(database)
    from bisheng.database.models.department import Department

    async with database() as db:
        row = await db.get(Department, 2)
        row.permission_projection_state = "FAILED_CLOSED"
        db.add(row)
        await db.commit()
    client, audit = FGA(), Audit()
    # Stale owned tuples of a genuinely archived, empty department can be
    # removed without changing lifecycle, other child-owned edges or admin.
    client.keys.update(
        {
            ("department:1", "parent", "department:2"),
            ("department:2", "child", "department:1"),
            ("user:99", "member", "department:2"),
        }
    )
    backend = runtime(database, client, monkeypatch)
    app = DepartmentBatchRepairApplication(backend)
    with tenant_scope(1):
        plan = await app.scan(audit)
        validate_plan(plan)
        assert plan["all_repairable"]
        # Mandatory configuration does not mean a whole-IAM comparison. Only
        # the unresolved orphan and its explicit IAM parent are requested.
        assert [call.args[0] for call in backend.iam_lookup.department.await_args_list] == ["4294956307", "300"]
        rows = {row["department_id"]: row for row in plan["entries"]}
        assert rows[composition.IDENTITY]["status"] == "AFTER_DEPENDENCIES"
        assert rows[composition.IDENTITY]["dependencies"] == [3]
        assert rows[composition.IDENTITY]["preview"]["classification"] == "RECOVER_REPARENT"
        assert plan["execution_order"].index(3) < plan["execution_order"].index(composition.IDENTITY)
        assert (await backend.departments.get(composition.IDENTITY))["parent_id"] == 2 and client.writes == 0
        path = tmp_path / "plan.jsonl"
        write_batch_plan(path, plan)
        assert read_batch_plan(path, plan["plan_checksum"]) == plan
        result = await app.apply(plan, audit)
        assert result["complete"] and result["remaining_department_ids"] == []
        assert result["repaired_operations"] == 3
        assert (await backend.departments.get(2))["status"] == "archived"
        assert (await backend.departments.get(3))["state"] == "CURRENT"
        assert (await backend.departments.get(composition.IDENTITY))["parent_id"] == 3
        assert ("user:55", "admin", f"department:{composition.IDENTITY}") in client.keys
        writes = client.writes
        restarted = DepartmentBatchRepairApplication(runtime(database, client, monkeypatch))
        again = await restarted.apply(plan, audit)
        assert again["complete"] and again["repaired_operations"] == 0 and client.writes == writes


async def test_batch_restart_after_child_write_sql_failure_preserves_completed_parent(database, monkeypatch):
    from unittest.mock import AsyncMock

    await composition.seed(database)
    await make_pending_parent(database)
    client, audit = FGA(), Audit()
    backend = runtime(database, client, monkeypatch)
    app = DepartmentBatchRepairApplication(backend)
    with tenant_scope(1):
        plan = await app.scan(audit)
        finish = backend.departments.finish

        async def fail_child(before, operation_id, version, session):
            if before["id"] == composition.IDENTITY:
                raise RuntimeError("child finalize failure")
            return await finish(before, operation_id, version, session)

        backend.departments.finish = AsyncMock(side_effect=fail_child)
        with pytest.raises(RuntimeError, match="child finalize"):
            await app.apply(plan, audit)
        assert (await backend.departments.get(3))["state"] == "CURRENT"
        assert (await backend.departments.get(composition.IDENTITY))["state"] == "FAILED_CLOSED"
        writes = client.writes
        resumed = DepartmentBatchRepairApplication(runtime(database, client, monkeypatch))
        result = await resumed.apply(plan, audit)
        assert result["complete"] and client.writes == writes


async def test_unrepairable_member_disposition_refuses_entire_batch_before_writes(database, monkeypatch):
    from bisheng.database.models.department import UserDepartment

    await composition.seed(database)
    await make_pending_parent(database)
    async with database() as db:
        db.add(UserDepartment(id=2, user_id=20, department_id=2, is_primary=1, source="wecom"))
        await db.commit()
    client, audit = FGA(), Audit()
    backend = runtime(database, client, monkeypatch)
    app = DepartmentBatchRepairApplication(backend)
    with tenant_scope(1):
        plan = await app.scan(audit)
        assert not plan["all_repairable"]
        with pytest.raises(RecoveryBlockedError, match="UNREPAIRABLE"):
            await app.apply(plan, audit)
        assert client.writes == 0 and (await backend.departments.get(3))["state"] == "FAILED_CLOSED"


async def test_sql_candidates_exclude_unrelated_healthy_current_fga_drift(database, monkeypatch):
    await composition.seed(database)
    client, audit = FGA(), Audit()
    backend = runtime(database, client, monkeypatch)
    with tenant_scope(1):
        inventory = await backend.inventory(audit)
        assert 3 not in inventory["candidates"]  # SQL normal: no speculative FGA audit
        assert not client.queries and not inventory["coverage"]["fga_store_scan"]


async def test_sql_provable_failed_parent_and_child_do_not_call_iam(database, monkeypatch):
    """AC-25/29: projection gates alone are dependencies, never IAM triggers."""
    from bisheng.database.models.department import Department

    await composition.seed(database)
    await make_pending_parent(database)
    async with database() as db:
        row = await db.get(Department, composition.IDENTITY)
        row.parent_id, row.path = 3, f"/1/3/{composition.IDENTITY}/"
        db.add(row)
        await db.commit()
    backend = runtime(database, FGA(), monkeypatch)
    with tenant_scope(1):
        plan = await DepartmentBatchRepairApplication(backend).scan(Audit())
    assert plan["all_repairable"]
    assert plan["entries"][-1]["dependencies"] == [3]
    backend.iam_lookup.department.assert_not_awaited()


def entry(identity, *, ancestors=(), pending=(), blocked=False):
    return {
        "department_id": identity,
        "status": "BLOCKED" if blocked else "READY",
        "dependencies": [],
        "ancestor_ids": list(ancestors),
        "pending_ancestors": list(pending),
        **({"reason": "business failure"} if blocked else {"preview": {"classification": "RECOVER_RELATIONS"}}),
    }


def test_topological_order_not_numerical_and_blocked_dependency_propagates():
    plan = build_plan({}, {}, [entry(1, ancestors=[900], pending=[900]), entry(900)])
    assert plan["execution_order"] == [900, 1] and plan["all_repairable"]
    blocked = build_plan({}, {}, [entry(1, ancestors=[900], pending=[900]), entry(900, blocked=True)])
    assert not blocked["all_repairable"] and blocked["entries"][0]["reason"] == "DEPENDENCY_NOT_REPAIRABLE"


def test_dependency_cycles_and_out_of_scope_ancestors_not_falsely_repairable():
    cycle = build_plan({}, {}, [entry(1, pending=[2]), entry(2, pending=[1])])
    assert not cycle["all_repairable"] and cycle["execution_order"] == []
    outside = build_plan({}, {}, [entry(1, pending=[9])])
    assert not outside["all_repairable"]


async def test_pilot_scope_automatically_includes_parent_dependency(database, monkeypatch):
    await composition.seed(database)
    await make_pending_parent(database)
    app = DepartmentBatchRepairApplication(runtime(database, FGA(), monkeypatch))
    with tenant_scope(1):
        plan = await app.scan(Audit(), requested_ids=[composition.IDENTITY])
    assert {row["department_id"] for row in plan["entries"]} == {3, composition.IDENTITY}
    assert plan["all_repairable"]


async def test_changed_last_item_blocks_entire_batch_before_any_gate(database, monkeypatch):
    from bisheng.database.models.department import UserDepartment

    await composition.seed(database)
    await make_pending_parent(database)
    client, audit = FGA(), Audit()
    backend = runtime(database, client, monkeypatch)
    app = DepartmentBatchRepairApplication(backend)
    with tenant_scope(1):
        plan = await app.scan(audit)
        async with database() as db:
            db.add(UserDepartment(id=3, user_id=21, department_id=composition.IDENTITY, is_primary=0, source="wecom"))
            await db.commit()
        with pytest.raises(RecoveryBlockedError, match="FACTS_CHANGED_BEFORE_WRITES"):
            await app.apply(plan, audit)
        assert client.writes == 0 and not any(event == "before" for event, _ in audit.events)
        assert (await backend.departments.get(3))["state"] == "FAILED_CLOSED"


async def test_repair_limit_refuses_whole_batch_before_writes(database, monkeypatch):
    await composition.seed(database)
    await make_pending_parent(database)
    client, audit = FGA(), Audit()
    backend = runtime(database, client, monkeypatch)
    app = DepartmentBatchRepairApplication(backend)
    with tenant_scope(1):
        plan = await app.scan(audit)
        with pytest.raises(RecoveryBlockedError, match="REPAIR_LIMIT_BEFORE_WRITES"):
            await app.apply(plan, audit, max_repairs=1)
        assert client.writes == 0 and not any(event == "before" for event, _ in audit.events)


async def test_batch_plan_detects_reordered_approval_tamper_and_old_format(database, monkeypatch, tmp_path):
    await composition.seed(database)
    await make_pending_parent(database)
    backend = runtime(database, FGA(), monkeypatch)
    with tenant_scope(1):
        plan = await DepartmentBatchRepairApplication(backend).scan(Audit())
    changed = deepcopy(plan)
    changed["execution_order"].reverse()
    with pytest.raises(RecoveryBlockedError, match="CHECKSUM"):
        validate_plan(changed)
    path = tmp_path / "plan.jsonl"
    write_batch_plan(path, plan)
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n")
    with pytest.raises(RecoveryBlockedError, match="INCOMPLETE"):
        read_batch_plan(path)
    header = json.loads(lines[0]) | {"format": "cofco.department-recovery.item.v1"}
    path.write_text(json.dumps(header) + "\n")
    with pytest.raises(RecoveryBlockedError, match="VERSION_INVALID"):
        read_batch_plan(path)


def test_formal_entry_defaults_to_read_only_scan_and_optional_iam():
    from scripts import reconcile_department_projections as cli

    args = cli.parse_args(["--tenant-id", "1", "--environment-id", "test", "--output-dir", "/tmp/new-evidence"])
    assert args.scan_departments and not args.apply and args.iam_config is None


async def test_optional_iam_sql_provable_batch_can_scan_and_apply(database, monkeypatch):
    from bisheng.database.models.department import Department

    await composition.seed(database)
    async with database() as db:
        row = await db.get(Department, composition.IDENTITY)
        row.parent_id = 3
        row.path = f"/1/3/{composition.IDENTITY}/"
        db.add(row)
        await db.commit()
    backend = runtime(database, FGA(), monkeypatch)
    backend.iam_lookup = None
    app = DepartmentBatchRepairApplication(backend)
    with tenant_scope(1):
        plan = await app.scan(Audit())
        assert plan["all_repairable"] and plan["scope"]["iam_source_fingerprint"] is None
        assert (await app.apply(plan, Audit()))["complete"]


async def test_optional_iam_reports_unprovable_business_as_blocked(database, monkeypatch):
    await composition.seed(database)
    backend = runtime(database, FGA(), monkeypatch)
    backend.iam_lookup = None
    with tenant_scope(1):
        plan = await DepartmentBatchRepairApplication(backend).scan(Audit())
    assert not plan["all_repairable"]
    assert any(e.get("reason") == "IAM_CONFIG_REQUIRED_FOR_UNPROVEN_BUSINESS" for e in plan["entries"])


async def test_stopped_writers_preview_does_not_wait_on_operation_age(database, monkeypatch):
    from datetime import datetime
    from unittest.mock import AsyncMock

    from bisheng.database.models.department import Department
    from bisheng.permission.domain.models import PermissionProjectionOperation

    await composition.seed(database)
    async with database() as db:
        row = await db.get(Department, composition.IDENTITY)
        row.parent_id = 3
        row.path = f"/1/3/{composition.IDENTITY}/"
        row.permission_projection_state = "PROJECTING"
        op = await db.get(PermissionProjectionOperation, 9)
        op.status = "STAGING"
        op.update_time = datetime(2026, 11, 16, 12, 0)
        db.add(row)
        db.add(op)
        await db.commit()
    backend = runtime(database, FGA(), monkeypatch)
    backend.database_time = AsyncMock(return_value=datetime(2026, 11, 16, 12, 0, 1))
    with tenant_scope(1):
        busy = await DepartmentBatchRepairApplication(backend).scan(Audit())
        assert not busy["all_repairable"]
        backend.writers_idle = True
        ready = await DepartmentBatchRepairApplication(backend).scan(Audit())
        assert ready["all_repairable"]
        assert ready["scope"]["writers_idle_confirmed_at_scan"]
