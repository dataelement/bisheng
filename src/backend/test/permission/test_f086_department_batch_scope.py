"""AC32/33: scoped reads, proof-local caches, bounded serial requests."""

import asyncio
import time
from itertools import pairwise
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from bisheng.api.services.department_reconciliation_runtime import DepartmentBatchRuntime
from bisheng.permission.application import department_recovery_model as model
from bisheng.permission.application.department_batch_repair import DepartmentBatchRepairApplication
from bisheng.permission.application.department_recovery_fga import RecoveryRequestLimiter
from bisheng.permission.application.department_recovery_runtime import tenant_scope
from bisheng.permission.domain.services.department_recovery_plan import RecoveryBlockedError, RecoveryRuntimeError
from scripts.iam_department_lookup import IamDepartmentLookup, IamLookupError
from scripts.reconcile_department_projections import parse_args
from test.permission.test_f086_department_batch_repair import (
    FGA,
    Audit,
    composition,
    make_pending_parent,
    runtime,
)
from test.permission.test_f086_department_batch_repair import (
    database as database,
)


async def test_pilot_and_apply_never_dump_tenant_members_or_walk_store(database, monkeypatch):
    from bisheng.database.models.department import Department

    await composition.seed(database)
    await make_pending_parent(database)
    # The retired old parent is not a target dependency after reparenting.
    async with database() as db:
        old = await db.get(Department, 2)
        old.permission_projection_state = "FAILED_CLOSED"
        db.add(old)
        await db.commit()
    client, audit = FGA(), Audit()
    backend = runtime(database, client, monkeypatch)
    for name in ("page", "high_water", "member_inventory", "inactive_membership_departments"):
        setattr(backend.departments, name, AsyncMock(side_effect=AssertionError("unrelated tenant scan")))
    app = DepartmentBatchRepairApplication(backend)
    with tenant_scope(1):
        plan = await app.scan(audit, requested_ids=[composition.IDENTITY])
        assert plan["all_repairable"]
        result = await app.apply(plan, audit)
        assert result["complete"]
    assert client.queries
    assert all(
        q.get("object") in {"department:", "department:3", f"department:{composition.IDENTITY}"} for q in client.queries
    )


async def test_full_candidate_scan_does_not_dump_all_members(database, monkeypatch):
    await composition.seed(database)
    await make_pending_parent(database)
    backend = runtime(database, FGA(), monkeypatch)
    backend.departments.member_inventory = AsyncMock(side_effect=AssertionError("all-user dump"))
    with tenant_scope(1):
        plan = await DepartmentBatchRepairApplication(backend).scan(Audit())
    assert plan["all_repairable"] and not plan["scope"]["fga_store_scan"]


async def test_failed_ancestor_does_not_expand_fga_reads_to_current_descendants(database, monkeypatch):
    from bisheng.database.models.department import Department

    await composition.seed(database)
    await make_pending_parent(database)
    descendants = range(100000, 100100)
    async with database() as db:
        for identity in descendants:
            db.add(
                Department(
                    id=identity,
                    dept_id=str(identity),
                    name=str(identity),
                    tenant_id=1,
                    parent_id=3,
                    path=f"/1/3/{identity}/",
                    permission_projection_state="CURRENT",
                )
            )
        await db.commit()
    client, audit = FGA(), Audit()
    backend = runtime(database, client, monkeypatch)
    with tenant_scope(1):
        plan = await DepartmentBatchRepairApplication(backend).scan(audit)
    assert {row["department_id"] for row in plan["entries"]} == {3, composition.IDENTITY}
    assert plan["scope"]["ancestor_gate_only_count"] == 100
    assert any(event == "scan_ancestor_gate_impact" for event, _ in audit.events)
    assert all(
        q.get("object") not in {f"department:{i}" for i in descendants}
        and q.get("user") not in {f"department:{i}" for i in descendants}
        for q in client.queries
    )


async def test_snapshot_reuses_ancestry_only_within_one_proof(database, monkeypatch):
    await composition.seed(database)
    backend = runtime(database, FGA(), monkeypatch)
    from bisheng.database.models.department import Department

    with tenant_scope(1):
        department = await backend.departments.get(3)
        with backend.departments.read_scope():
            first = await backend.departments.ancestors(department)
            assert first == await backend.departments.ancestors(department)
            assert first[0]["status"] == "active"
        async with database() as db:
            root = await db.get(Department, 1)
            root.status = "archived"
            db.add(root)
            await db.commit()
        with backend.departments.read_scope():
            assert (await backend.departments.ancestors(department))[0]["status"] == "archived"


def test_large_item_and_excessive_qps_refused_before_gate(tmp_path):
    backend = DepartmentBatchRuntime.__new__(DepartmentBatchRuntime)
    backend.limiter = SimpleNamespace(interval=0.5)
    keys = [[f"user:{i}", "member", "department:1"] for i in range(1, 2001)]
    with pytest.raises(RecoveryBlockedError, match="SHORT_TRANSACTION"):
        backend.validate_item_budget(
            {"observed": keys, "target": keys, "correction": [], "classification": "RECOVER_STATE_ONLY"}
        )
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--environment-id",
                "x",
                "--tenant-id",
                "1",
                "--iam-config",
                "iam.json",
                "--scan-departments",
                "--output-dir",
                str(tmp_path),
                "--max-fga-qps",
                "100",
            ]
        )


async def test_latest_model_only_still_detects_pin_and_content_change(monkeypatch):
    monkeypatch.setattr(
        model, "settings", SimpleNamespace(openfga=SimpleNamespace(store_name="production", force_write_model=False))
    )
    calls, latest, body = [], {"id": "model1"}, model.build_authorization_model_f048()

    def response(request):
        calls.append((request.url.path, dict(request.url.params)))
        if request.url.path == "/stores":
            assert dict(request.url.params) == {"name": "production", "page_size": "2"}
            return httpx.Response(200, json={"stores": [{"name": "production", "id": "store"}]})
        assert request.url.path == "/stores/store/authorization-models"
        assert dict(request.url.params) == {"page_size": "1"}
        return httpx.Response(
            200, json={"authorization_models": [{"id": latest["id"], **body}], "continuation_token": "must-not-follow"}
        )

    async with httpx.AsyncClient(base_url="https://fga.test", transport=httpx.MockTransport(response)) as client:
        cache = {}
        first = await model.discover_batch_model(client, cache)
        latest["id"] = "model2"
        second = await model.discover_batch_model(client, cache)
        assert first.model_id == "model1" and second.model_id == "model2" and len(calls) == 4
        body["type_definitions"] = []
        with pytest.raises(RecoveryRuntimeError, match="CHECKSUM_MISMATCH"):
            await model.discover_batch_model(client, cache)


async def test_model_never_autowrites(monkeypatch):
    monkeypatch.setattr(model, "settings", SimpleNamespace(openfga=SimpleNamespace(force_write_model=True)))
    async with httpx.AsyncClient(base_url="https://fga.test") as client:
        with pytest.raises(RecoveryRuntimeError, match="AUTO_WRITE_FORBIDDEN"):
            await model.discover_batch_model(client, {})


async def test_fga_limiter_serializes_concurrent_hooks():
    limiter, completed = RecoveryRequestLimiter(100), []

    async def request():
        await limiter.on_request(None)
        completed.append(time.monotonic())

    await asyncio.gather(*(request() for _ in range(4)))
    assert all(b - a >= 0.008 for a, b in pairwise(completed))
    assert limiter.calls == 4


async def test_iam_concurrent_duplicate_cached_and_locked_read_never_fetches(monkeypatch):
    monkeypatch.setenv("BS_DEPARTMENT_IAM_APP_ID", "test-app")
    monkeypatch.setenv("BS_DEPARTMENT_IAM_APP_SECRET", "test-only-value")
    calls = []

    def response(request):
        calls.append(request)
        return httpx.Response(200, json={"department": [{"id": "9", "parentid": "1", "enable": 1}]})

    lookup = IamDepartmentLookup(
        {"base_url": "https://iam.test", "bisheng_source": "wecom"}, transport=httpx.MockTransport(response)
    )
    try:
        with pytest.raises(IamLookupError, match="NOT_PREFETCHED"):
            lookup.cached_department("9")
        rows = await asyncio.gather(*(lookup.department("9") for _ in range(4)))
        assert len(calls) == 1 and all(row == rows[0] for row in rows)
        assert lookup.cached_department("9") == rows[0] and len(calls) == 1
    finally:
        await lookup.close()


async def test_before_persistence_runs_outside_sql_transaction(database, monkeypatch):
    await composition.seed(database)
    await make_pending_parent(database)
    backend = runtime(database, FGA(), monkeypatch)

    class OutsideAudit(Audit):
        async def before(self, payload):
            assert backend.session is None
            await super().before(payload)

    audit = OutsideAudit()
    app = DepartmentBatchRepairApplication(backend)
    with tenant_scope(1):
        plan = await app.scan(audit)
        assert (await app.apply(plan, audit))["complete"]
    assert any(event == "before" for event, _ in audit.events)


async def test_unprefetched_iam_is_rejected_under_lock_without_http(database, monkeypatch):
    await composition.seed(database)
    backend = runtime(database, FGA(), monkeypatch)

    def uncached(identity):
        raise IamLookupError("IAM_FACTS_NOT_PREFETCHED_BEFORE_LOCK")

    backend.iam_lookup.cached_department = uncached
    with tenant_scope(1), pytest.raises(RecoveryBlockedError, match="NOT_PREFETCHED"):
        async with backend.transaction():
            await backend.snapshot(composition.IDENTITY, lock=True)
    backend.iam_lookup.department.assert_not_awaited()


async def test_final_scoped_read_detects_relation_drift(database, monkeypatch):
    await composition.seed(database)
    await make_pending_parent(database)
    client, backend = FGA(), None
    backend = runtime(database, client, monkeypatch)
    app = DepartmentBatchRepairApplication(backend)
    with tenant_scope(1):
        plan = await app.scan(Audit())
        original, calls = backend.inventory, []

        async def inventory(*args, **kwargs):
            calls.append(kwargs)
            result = await original(*args, **kwargs)
            if len(calls) == 2:
                client.keys.discard(("department:1", "parent", "department:3"))
            return result

        backend.inventory = inventory
        result = await app.apply(plan, Audit())
    assert not result["complete"] and result["remaining_department_ids"] == [3]


async def test_apply_uses_frozen_scope_without_reading_new_unrelated_department(database, monkeypatch):
    from bisheng.database.models.department import Department

    await composition.seed(database)
    await make_pending_parent(database)
    client = FGA()
    backend = runtime(database, client, monkeypatch)
    app = DepartmentBatchRepairApplication(backend)
    with tenant_scope(1):
        plan = await app.scan(Audit())
        async with database() as db:
            db.add(
                Department(
                    id=777,
                    dept_id="unrelated",
                    name="unrelated",
                    tenant_id=1,
                    parent_id=1,
                    path="/1/777/",
                    permission_projection_state="FAILED_CLOSED",
                )
            )
            await db.commit()
        backend.departments.page = AsyncMock(side_effect=AssertionError("tenant rescan"))
        result = await app.apply(plan, Audit())
    assert result["complete"]
    assert all(q.get("object") != "department:777" and q.get("user") != "department:777" for q in client.queries)
