"""Confirmed IAM deletion: CURRENT/FAILED retirement, atomic cleanup, and reentry."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy import delete
from sqlmodel import SQLModel, select

from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.department_admin_grant import DepartmentAdminGrant
from bisheng.database.models.role import Role
from bisheng.database.models.role_access import RoleAccess
from bisheng.permission.application.department_batch_repair import DepartmentBatchRepairApplication
from bisheng.permission.application.department_recovery_runtime import tenant_scope
from bisheng.permission.domain.services.department_recovery_plan import RecoveryBlockedError
from bisheng.user.domain.models.user_role import UserRole
from scripts.iam_department_lookup import IamDepartmentLookup
from test.permission.test_f086_department_batch_repair import FGA, Audit, composition, runtime
from test.permission.test_f086_department_batch_repair import database as database


async def seed(factory, *, state="CURRENT", populated=False):
    await composition.seed(factory)
    async with factory() as db:
        connection = await db.connection()
        metadata = sa.MetaData()
        sa.Table("user", metadata, sa.Column("user_id", sa.Integer, primary_key=True))
        SQLModel.metadata.tables["department"].to_metadata(metadata)
        tables = []
        for model in (Role, UserRole, RoleAccess, DepartmentAdminGrant):
            table = model.__table__.to_metadata(metadata)
            table.c.id.type, table.c.id.autoincrement = sa.Integer(), False
            tables.append(table)
        for table in tables:
            await connection.run_sync(lambda sync, table=table: table.create(sync, checkfirst=True))
        row = await db.get(Department, composition.IDENTITY)
        # Same shape as production: a CURRENT leaf with stale ancestor path.
        row.parent_id, row.path = 3, f"/1/{composition.IDENTITY}/"
        row.permission_projection_state = state
        row.permission_projection_version = 0
        row.permission_projection_operation_id = None
        row.last_sync_ts = 123
        db.add(row)
        if not populated:
            await db.exec(delete(UserDepartment).where(UserDepartment.department_id == composition.IDENTITY))
        else:
            db.add(DepartmentAdminGrant(id=51, user_id=55, department_id=composition.IDENTITY, grant_source="manual"))
            db.add(
                Role(
                    id=71,
                    role_name="department-role",
                    role_type="tenant",
                    tenant_id=1,
                    department_id=composition.IDENTITY,
                )
            )
            db.add(UserRole(id=81, user_id=10, role_id=71, tenant_id=1))
            db.add(RoleAccess(id=91, role_id=71, third_id="workstation", type=99, tenant_id=1))
            db.add(Role(id=72, role_name="unrelated-role", role_type="tenant", tenant_id=1, department_id=3))
            db.add(UserRole(id=82, user_id=10, role_id=72, tenant_id=1))
            db.add(UserDepartment(id=2, user_id=10, department_id=3, is_primary=0, source="wecom"))
        await db.commit()


def lookup(monkeypatch, *, response=None):
    monkeypatch.setenv("BS_DEPARTMENT_IAM_APP_ID", "test-app")
    monkeypatch.setenv("BS_DEPARTMENT_IAM_APP_SECRET", "test-only-value")
    status = SimpleNamespace(body=response or {"errcode": "1", "errmsg": "部门不存在\uff01"}, requests=[])

    def serve(request):
        status.requests.append(dict(request.url.params))
        return httpx.Response(200, json=status.body)

    client = IamDepartmentLookup(
        {"base_url": "https://iam.test", "bisheng_source": "wecom", "max_qps": 5}, transport=httpx.MockTransport(serve)
    )
    client.interval = 0  # fake transport, no production requests or rate changes
    return client, status


@pytest.mark.parametrize("state", ["CURRENT", "FAILED_CLOSED"])
async def test_empty_stale_leaf_is_repairable_without_path_rewrite(database, monkeypatch, state):
    await seed(database, state=state)
    client, status = lookup(monkeypatch)
    fga, audit = FGA(), Audit()
    fga.keys.add(("user:55", "viewer", "knowledge_space:other"))
    backend = runtime(database, fga, monkeypatch)
    backend.iam_lookup = client
    try:
        with tenant_scope(1):
            app = DepartmentBatchRepairApplication(backend)
            plan = await app.scan(audit, requested_ids=[composition.IDENTITY])
            preview = plan["entries"][0]["preview"]
            assert plan["all_repairable"] and preview["classification"] == "RECOVER_ARCHIVE"
            assert preview["target"] == [] and not preview["archive"]["before"]["memberships"]
            assert (await backend.departments.get(composition.IDENTITY))["status"] == "active"
            assert fga.writes == 0 and len(status.requests) == 1
            assert (await app.apply(plan, audit))["complete"]
            row = await backend.departments.get(composition.IDENTITY)
            assert (
                row["status"] == "archived"
                and row["deleted"] == 1
                and row["state"] == "CURRENT"
                and row["version"] == 1
            )
            assert row["path"] == f"/1/{composition.IDENTITY}/"
            async with database() as db:
                assert (await db.get(Department, composition.IDENTITY)).last_sync_ts == 123
            assert ("user:55", "viewer", "knowledge_space:other") in fga.keys
            writes = fga.writes
            restarted = runtime(database, fga, monkeypatch)
            restarted.iam_lookup = client
            assert (await DepartmentBatchRepairApplication(restarted).apply(plan, audit))["complete"]
            assert fga.writes == writes
            inspected = await DepartmentBatchRepairApplication(restarted).scan(
                Audit(), requested_ids=[composition.IDENTITY]
            )
            assert inspected["entries"][0]["preview"]["classification"] == "ALREADY_DONE"
    finally:
        await client.close()


async def test_populated_archive_cleans_owned_references_and_preserves_other_affiliations(database, monkeypatch):
    await seed(database, populated=True)
    client, _ = lookup(monkeypatch)
    fga = FGA()
    backend = runtime(database, fga, monkeypatch)
    backend.iam_lookup = client
    try:
        with tenant_scope(1):
            app = DepartmentBatchRepairApplication(backend)
            plan = await app.scan(Audit(), requested_ids=[composition.IDENTITY])
            before = plan["entries"][0]["preview"]["archive"]["before"]
            assert len(before["memberships"]) == len(before["admins"]) == len(before["roles"]) == 1
            assert (await app.apply(plan, Audit()))["complete"]
            async with database() as db:
                assert (
                    await db.exec(select(UserDepartment).where(UserDepartment.department_id == composition.IDENTITY))
                ).first() is None
                assert await db.get(DepartmentAdminGrant, 51) is None
                assert await db.get(Role, 71) is None
                assert (await db.exec(select(UserRole).where(UserRole.role_id == 71))).first() is None
                assert await db.get(RoleAccess, 91) is None
                assert await db.get(Role, 72) is not None
                assert (await db.exec(select(UserRole).where(UserRole.role_id == 72))).first() is not None
                assert (
                    await db.exec(select(UserDepartment).where(UserDepartment.department_id == 3))
                ).first() is not None
    finally:
        await client.close()


@pytest.mark.parametrize("failure", ["cleanup", "ledger", "department"])
async def test_write_then_sql_cleanup_failure_restarts_without_repeating_fga(database, monkeypatch, failure):
    await seed(database, populated=True)
    client, _ = lookup(monkeypatch)
    fga, backend = FGA(), None
    backend = runtime(database, fga, monkeypatch)
    backend.iam_lookup = client
    try:
        with tenant_scope(1):
            app = DepartmentBatchRepairApplication(backend)
            plan = await app.scan(Audit(), requested_ids=[composition.IDENTITY])
            target, method = (
                (backend.departments, "cleanup_archive")
                if failure == "cleanup"
                else (backend.ledger, "finalize")
                if failure == "ledger"
                else (backend.departments, "finish")
            )
            setattr(target, method, AsyncMock(side_effect=RuntimeError("SQL cleanup failure")))
            with pytest.raises(RuntimeError, match="cleanup failure"):
                await app.apply(plan, Audit())
            assert (await backend.departments.get(composition.IDENTITY))["state"] == "FAILED_CLOSED"
            async with database() as db:
                assert await db.get(Role, 71) is not None
            writes = fga.writes
            restarted = runtime(database, fga, monkeypatch)
            restarted.iam_lookup = client
            preview = await DepartmentBatchRepairApplication(restarted).scan(
                Audit(), requested_ids=[composition.IDENTITY]
            )
            assert preview["all_repairable"] and preview["entries"][0]["preview"]["classification"] == "RECOVER_ARCHIVE"
            restarted.window_id = "different-window"
            with pytest.raises(RecoveryBlockedError, match="WINDOW_OR_BACKUP_CHANGED"):
                await DepartmentBatchRepairApplication(restarted).apply(plan, Audit())
            assert fga.writes == writes
            restarted.window_id = "test-window"
            assert (await DepartmentBatchRepairApplication(restarted).apply(plan, Audit()))["complete"]
            assert fga.writes == writes
    finally:
        await client.close()


async def test_source_reappearance_before_apply_refuses_all_writes(database, monkeypatch):
    await seed(database)
    client, status = lookup(monkeypatch)
    fga = FGA()
    backend = runtime(database, fga, monkeypatch)
    backend.iam_lookup = client
    try:
        with tenant_scope(1):
            app = DepartmentBatchRepairApplication(backend)
            plan = await app.scan(Audit(), requested_ids=[composition.IDENTITY])
            status.body = {"department": [{"id": "4294956307", "parentid": "300", "enable": 1}]}
            with pytest.raises(RecoveryBlockedError, match="REAPPEARED"):
                await app.apply(plan, Audit())
            assert fga.writes == 0 and (await backend.departments.get(composition.IDENTITY))["status"] == "active"
    finally:
        await client.close()


@pytest.mark.parametrize(
    "body",
    [
        {"errcode": "1", "errmsg": "权限不足"},
        {"errcode": "2", "errmsg": "部门不存在\uff01"},
        {"errcode": "0", "department": []},
    ],
)
async def test_other_business_errors_never_authorize_archive(database, monkeypatch, body):
    await seed(database)
    client, _ = lookup(monkeypatch, response=body)
    backend = runtime(database, FGA(), monkeypatch)
    backend.iam_lookup = client
    try:
        with tenant_scope(1):
            plan = await DepartmentBatchRepairApplication(backend).scan(Audit(), requested_ids=[composition.IDENTITY])
        assert not plan["all_repairable"] and plan["entries"][0]["status"] == "BLOCKED"
    finally:
        await client.close()


async def test_parent_not_found_does_not_retire_existing_child(database, monkeypatch):
    await seed(database)
    client, _ = lookup(monkeypatch)
    original = client._read

    async def read(identity):
        if identity == "4294956307":
            return {"id": identity, "parentid": "300", "enable": 1}
        return await original(identity)

    client._read = read
    backend = runtime(database, FGA(), monkeypatch)
    backend.iam_lookup = client
    try:
        with tenant_scope(1):
            plan = await DepartmentBatchRepairApplication(backend).scan(Audit(), requested_ids=[composition.IDENTITY])
        assert not plan["all_repairable"] and not backend.archive_targets
    finally:
        await client.close()


async def test_t1_failure_rolls_back_lifecycle_binding_and_shared_receipt(database, monkeypatch):
    await seed(database, populated=True)
    client, _ = lookup(monkeypatch)
    fga = FGA()
    backend = runtime(database, fga, monkeypatch)
    backend.iam_lookup = client
    try:
        with tenant_scope(1):
            app = DepartmentBatchRepairApplication(backend)
            plan = await app.scan(Audit(), requested_ids=[composition.IDENTITY])
            identity = plan["entries"][0]["preview"]["recovery_id"]
            backend.ledger.append = AsyncMock(side_effect=RuntimeError("prepare receipt failed"))
            with pytest.raises(RuntimeError, match="receipt failed"):
                await app.apply(plan, Audit())
            row = await backend.departments.get(composition.IDENTITY)
            assert (
                row["status"] == "active"
                and row["deleted"] == 0
                and row["state"] == "CURRENT"
                and row["operation_id"] is None
            )
            assert await backend.record(identity) is None and fga.writes == 0
    finally:
        await client.close()


@pytest.mark.parametrize("fault", ["nonleaf", "mount", "global_role", "cross_tenant_role"])
async def test_unsupported_archive_scope_is_blocked_without_writes(database, monkeypatch, fault):
    await seed(database, populated=True)
    async with database() as db:
        if fault == "nonleaf":
            db.add(
                Department(
                    id=888,
                    dept_id="child",
                    name="child",
                    tenant_id=1,
                    parent_id=composition.IDENTITY,
                    path=f"/1/{composition.IDENTITY}/888/",
                )
            )
        elif fault == "mount":
            row = await db.get(Department, composition.IDENTITY)
            row.is_tenant_root, row.mounted_tenant_id = 1, 42
            db.add(row)
        else:
            row = await db.get(Role, 71)
            if fault == "global_role":
                row.role_type = "global"
            else:
                row.tenant_id = 2
            db.add(row)
        await db.commit()
    client, _ = lookup(monkeypatch)
    fga = FGA()
    backend = runtime(database, fga, monkeypatch)
    backend.iam_lookup = client
    try:
        with tenant_scope(1):
            plan = await DepartmentBatchRepairApplication(backend).scan(Audit(), requested_ids=[composition.IDENTITY])
        assert not plan["all_repairable"] and fga.writes == 0
    finally:
        await client.close()


async def test_association_changed_after_preview_refuses_archive_before_t1(database, monkeypatch):
    await seed(database, populated=True)
    client, _ = lookup(monkeypatch)
    fga = FGA()
    backend = runtime(database, fga, monkeypatch)
    backend.iam_lookup = client
    try:
        with tenant_scope(1):
            app = DepartmentBatchRepairApplication(backend)
            plan = await app.scan(Audit(), requested_ids=[composition.IDENTITY])
            async with database() as db:
                role = await db.get(Role, 71)
                role.role_name = "newly changed role"
                db.add(role)
                await db.commit()
            with pytest.raises(RecoveryBlockedError, match="FACTS_CHANGED_BEFORE_WRITES"):
                await app.apply(plan, Audit())
            assert fga.writes == 0 and (await backend.departments.get(composition.IDENTITY))["status"] == "active"
    finally:
        await client.close()


async def test_source_reappears_after_t1_keeps_gate_closed_and_associations_intact(database, monkeypatch):
    from bisheng.permission.domain.services.department_recovery_plan import RecoveryRuntimeError

    await seed(database, populated=True)
    client, status = lookup(monkeypatch)
    fga = FGA()
    backend = runtime(database, fga, monkeypatch)
    backend.iam_lookup = client
    try:
        with tenant_scope(1):
            app = DepartmentBatchRepairApplication(backend)
            plan = await app.scan(Audit(), requested_ids=[composition.IDENTITY])
            prepare = backend.prepare

            async def changed_after_prepare(payload):
                await prepare(payload)
                status.body = {"department": [{"id": "4294956307", "parentid": "300", "enable": 1}]}

            backend.prepare = changed_after_prepare
            with pytest.raises(RecoveryRuntimeError, match="REAPPEARED"):
                await app.apply(plan, Audit())
            row = await backend.departments.get(composition.IDENTITY)
            assert row["status"] == "archived" and row["state"] == "FAILED_CLOSED" and fga.writes == 0
            async with database() as db:
                assert await db.get(Role, 71) is not None
    finally:
        await client.close()


async def test_stale_prefix_cannot_hide_orphan_descendant_from_leaf_proof(database, monkeypatch):
    await seed(database)
    async with database() as db:
        db.add(
            Department(
                id=8888,
                tenant_id=1,
                dept_id="e2e-f086-orphan-path",
                name="orphan",
                parent_id=7777,
                path=f"/1/changed-prefix/{composition.IDENTITY}/8888/",
                status="archived",
                is_deleted=1,
            )
        )
        await db.commit()
    backend = runtime(database, FGA(), monkeypatch)
    client, _ = lookup(monkeypatch)
    backend.iam_lookup = client
    try:
        with tenant_scope(1):
            plan = await DepartmentBatchRepairApplication(backend).scan(Audit(), requested_ids=[composition.IDENTITY])
        assert not plan["all_repairable"]
        assert any("LEAF" in e.get("reason", "") for e in plan["entries"])
    finally:
        await client.close()
