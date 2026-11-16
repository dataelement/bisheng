"""AC-03/04/05/08/19: Owner proof covers all relations and rejects drift."""

import pytest

from bisheng.department.domain.services.department_projection_recovery import validate_original_target
from bisheng.permission.domain.services.projection_plan import ProjectionPlan, ProjectionTupleDelta


def delta(action, user, relation, obj, seq=0):
    return ProjectionTupleDelta(phase="COMMIT", sequence=seq, action=action, user=user, relation=relation, object=obj)


def p(deltas):
    return ProjectionPlan(
        tenant_id=7,
        idempotency_key="k",
        operation_type="DEPARTMENT_MOVE",
        scope_type="department",
        scope_key="11",
        expected_version=0,
        target_version=1,
        store_id="s",
        model_id="m",
        operator_id=0,
        change_item_count=1,
        deltas=tuple(deltas),
    )


def test_target_proof_allows_original_mixed_but_not_unrelated_missing_members():
    target = {
        ("department:2", "parent", "department:11"),
        ("department:11", "child", "department:2"),
        ("user:3", "member", "department:11"),
    }
    plan = p([delta("WRITE", *k, seq=i) for i, k in enumerate(sorted(target)[:2])])
    # Members absent outside original effect are NOT fixed by automatic recovery.
    with pytest.raises(ValueError, match="ORIGINAL_EFFECTS"):
        validate_original_target(plan, set(), target)


def test_original_after_must_equal_current_business():
    plan = p([delta("WRITE", "department:1", "parent", "department:11")])
    with pytest.raises(ValueError, match="ORIGINAL_TARGET"):
        validate_original_target(plan, set(), {("department:2", "parent", "department:11")})


def test_legacy_manual_type_and_foreign_effect_rejected():
    plan = p([delta("WRITE", "user:3", "viewer", "knowledge:10")])
    with pytest.raises(ValueError):
        validate_original_target(plan, set(), set())


async def test_actual_owner_and_ledger_commit_together_and_resume_unknown_write(monkeypatch):
    """AC-03/08/14: real SQL UOW rollback after FGA success keeps the gate."""
    from contextlib import asynccontextmanager

    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool
    from sqlmodel import SQLModel
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.core.context.tenant import exact_tenant_filter
    from bisheng.database.models.audit_log import AuditLog
    from bisheng.database.models.department import Department
    from bisheng.department.domain.services import department_projection_scope as scope_module
    from bisheng.department.domain.services.department_projection_recovery import DepartmentProjectionExecutor
    from bisheng.department.domain.services.department_projection_scope import SqlDepartmentProjectionScope
    from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository
    from bisheng.permission.domain.services.projection_service import ProjectionService
    from test.permission.test_f048_projection_service import FakeFGAProjection, FakeRecentMarker, FakeScopeGuard

    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    metadata = sa.MetaData()
    sa.Table("user", metadata, sa.Column("user_id", sa.Integer, primary_key=True))
    for name in [
        "department",
        "user_department",
        "permission_projection_operation",
        "permission_projection_tuple",
        "auditlog",
    ]:
        table = SQLModel.metadata.tables[name].to_metadata(metadata)
        if name != "auditlog":
            table.c.id.type = sa.Integer()
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

    @asynccontextmanager
    async def factory():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            yield db

    monkeypatch.setattr(scope_module, "get_async_db_session", factory)
    scope = SqlDepartmentProjectionScope()
    repo = ProjectionRepository(factory)
    fga = FakeFGAProjection(set())

    class Finalizer:
        async def finalize(self, plan, opid):
            await scope.finalize(plan, opid)

    ledger = ProjectionService(
        repository=repo, marker=FakeRecentMarker(), scope_guard=FakeScopeGuard(), fga=fga, finalizer=Finalizer()
    )
    plan = p(
        [
            delta("WRITE", "department:1", "parent", "department:11"),
            delta("WRITE", "department:11", "child", "department:1", 1),
        ]
    )

    @asynccontextmanager
    async def lease_factory(*args):
        class Lease:
            async def verify_owned(self):
                return None

        yield Lease()

    environment_calls = {"business": 0, "recovery": 0}
    gate_calls = []

    async def recovery_write_gate():
        gate_calls.append("write")

    async def present(identity, **kwargs):
        assert ledger._department_write_gate.get() is recovery_write_gate
        return frozenset(fga.present)

    async def environment(session):
        environment_calls["recovery"] += 1
        return ("s", "m")

    async def business_environment(session):
        environment_calls["business"] += 1
        return ("s", "m")

    fail = True

    async def audit(session, plan, opid, stage, reason):
        if fail:
            raise RuntimeError("injected SQL failure after FGA")
        identity = "f086-test-final" if stage == "finalized" else "f086-test-failed"
        if await session.get(AuditLog, identity) is not None:
            return
        session.add(
            AuditLog(
                id=identity,
                tenant_id=7,
                operator_id=0,
                action="recovery.finalized",
                target_type="department_projection",
                target_id="11",
                audit_metadata={"op": opid},
            )
        )

    try:
        with exact_tenant_filter(7):
            operation = await ledger.prepare(plan)
            async with factory() as db:
                db.add(Department(id=1, tenant_id=7, dept_id="test-root", name="root", path="/1/"))
                db.add(
                    Department(
                        id=11,
                        tenant_id=7,
                        dept_id="test-child",
                        name="child",
                        path="/1/11/",
                        parent_id=1,
                        permission_projection_state="PROJECTING",
                        permission_projection_operation_id=operation.id,
                    )
                )
                await db.commit()
            executor = DepartmentProjectionExecutor(
                ledger=ledger,
                scope=scope,
                lease_factory=lease_factory,
                observed=present,
                environment=environment,
                business_environment=business_environment,
                write_gate=recovery_write_gate,
                audit=audit,
                session_factory=factory,
            )
            with pytest.raises(RuntimeError, match="injected SQL"):
                await executor.execute(operation.id, plan)
            assert environment_calls == {"business": 1, "recovery": 0}
            assert gate_calls == []
            async with factory() as db:
                row = await db.get(Department, 11)
                assert row.permission_projection_state == "FAILED_CLOSED" and row.permission_projection_version == 0
            assert len(fga.calls) == 1
            fail = False
            await executor.execute(operation.id, plan)
            assert environment_calls["recovery"] > 0
            assert len(fga.calls) == 1
            async with factory() as db:
                row = await db.get(Department, 11)
                assert row.permission_projection_state == "CURRENT" and row.permission_projection_version == 1
                assert await db.get(AuditLog, "f086-test-final") is not None
            assert (await repo.aget_operation(operation.id)).status == "FINALIZED"
            from bisheng.permission.domain.models import PermissionProjectionOperation

            async with factory() as db:
                op = await db.get(PermissionProjectionOperation, operation.id)
                op.status = "COMMITTED"
                db.add(op)
                await db.commit()
            target = set(fga.present)
            fga.present.clear()
            with pytest.raises(Exception, match="COMMITTED_AFTER_STATE_MISSING"):
                await executor.execute(operation.id, plan)
            async with factory() as db:
                row = await db.get(Department, 11)
                assert row.permission_projection_state == "FAILED_CLOSED" and row.permission_projection_version == 1
            assert len(fga.calls) == 1
            fga.present.update(target)
            await executor.execute(operation.id, plan)
            async with factory() as db:
                row = await db.get(Department, 11)
                assert row.permission_projection_state == "CURRENT" and row.permission_projection_version == 1
            assert len(fga.calls) == 1
            # Normal archive remains the existing synchronous Owner flow:
            # project its verified topology first, then its caller performs
            # membership/role cleanup. Recovery never infers that cleanup done.
            from dataclasses import replace

            from bisheng.database.models.department import UserDepartment

            archive_plan = replace(
                plan,
                idempotency_key="normal-archive",
                operation_type="DEPARTMENT_ARCHIVE",
                expected_version=1,
                target_version=2,
                deltas=tuple(replace(d, action="DELETE") for d in plan.deltas),
            )
            archive_op = await ledger.prepare(archive_plan)
            async with factory() as db:
                row = await db.get(Department, 11)
                row.status = "archived"
                row.is_deleted = 1
                row.permission_projection_state = "PROJECTING"
                row.permission_projection_operation_id = archive_op.id
                db.add(row)
                db.add(UserDepartment(id=1, user_id=3, department_id=11))
                await db.commit()
            fga.present.add(("user:3", "member", "department:11"))
            before_environment = environment_calls.copy()
            before_gate_count = len(gate_calls)
            await executor.execute(archive_op.id, archive_plan)
            assert environment_calls["business"] == before_environment["business"] + 1
            assert environment_calls["recovery"] == before_environment["recovery"]
            assert len(gate_calls) == before_gate_count
            assert (await repo.aget_operation(archive_op.id)).status == "FINALIZED"
            async with factory() as db:
                row = await db.get(Department, 11)
                assert row.status == "archived" and row.permission_projection_state == "CURRENT"
    finally:
        await engine.dispose()
