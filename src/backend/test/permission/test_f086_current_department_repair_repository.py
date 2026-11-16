"""Actual existing-table UOW checks; SQLite is not a production lock proof."""

from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.department import Department
from bisheng.department.domain.repositories.current_repair_repository import CurrentDepartmentRepairRepository
from bisheng.permission.application.current_department_repair import CurrentDepartmentRepairApplication
from bisheng.permission.domain.models import PermissionProjectionOperation
from bisheng.permission.domain.repositories.current_department_repair_repository import CurrentDepartmentRepairLedger
from bisheng.permission.domain.services.department_recovery_plan import RecoveryBlockedError
from test.permission.test_f086_current_department_repair import Backend


@pytest.fixture
async def database():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    metadata = sa.MetaData()
    sa.Table(
        "department_knowledge_space",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("department_id", sa.Integer),
        sa.Column("tenant_id", sa.Integer),
    )
    sa.Table("user", metadata, sa.Column("user_id", sa.Integer, primary_key=True))
    from bisheng.database.models.department_admin_grant import DepartmentAdminGrant
    from bisheng.database.models.role import Role
    from bisheng.database.models.role_access import RoleAccess
    from bisheng.user.domain.models.user_role import UserRole

    for name in (
        "department",
        "permission_projection_operation",
        "permission_projection_tuple",
        "auditlog",
        DepartmentAdminGrant.__tablename__,
        Role.__tablename__,
        RoleAccess.__tablename__,
        UserRole.__tablename__,
    ):
        table = SQLModel.metadata.tables[name].to_metadata(metadata)
        if name != "auditlog":
            table.c.id.type = sa.Integer()
        if len(table.primary_key.columns) > 1:
            for column in table.primary_key.columns:
                column.autoincrement = False
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)

    @asynccontextmanager
    async def factory():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    with bypass_tenant_filter():
        yield factory
    await engine.dispose()


async def seed(factory):
    async with factory() as session:
        session.add(
            Department(
                id=42,
                tenant_id=1,
                dept_id="e2e-f078-current-42",
                name="test",
                parent_id=3,
                path="/1/3/42/",
                permission_projection_state="PROJECTING",
                permission_projection_operation_id=9,
                permission_projection_version=7,
            )
        )
        session.add(
            PermissionProjectionOperation(
                id=9,
                tenant_id=1,
                idempotency_key="old-current-test",
                request_checksum="a" * 64,
                before_checksum="b" * 64,
                after_checksum="c" * 64,
                operation_type="DEPARTMENT_CREATE",
                scope_type="department",
                scope_key="42",
                expected_version=7,
                target_version=8,
                store_id="old-store",
                model_id="old-model",
                status="PREPARED",
                error_message="private-original-error-kept-in-sql",
                operator_id=0,
            )
        )
        await session.commit()


@pytest.mark.parametrize("rollback", [False, True])
async def test_gate_operation_department_source_and_audit_share_one_uow(database, rollback):
    await seed(database)
    departments, ledger = CurrentDepartmentRepairRepository(database), CurrentDepartmentRepairLedger(database)
    async with database() as session:
        payload = CurrentDepartmentRepairApplication.preview(
            {
                "department": await departments.get(42, session=session),
                "business": Backend().proof(),
                "observed": set(),
                "sources": [(Backend().source, [], True)],
                "environment": Backend().env,
            }
        )
    try:
        async with database() as session:
            async with session.begin():
                sources = await ledger.operations(payload["department"], session=session)
                identity = await ledger.create_gate(payload, session=session)
                await ledger.cancel_sources(sources, payload["recovery_id"], session=session)
                await departments.set_gate(payload["department"], identity, session)
                await ledger.append(
                    payload, identity, "prepared", session=session, backup_evidence={"ref": "test"}, window_id="window"
                )
                if rollback:
                    raise RuntimeError("rollback before gate commit")
    except RuntimeError:
        assert rollback
    async with database() as session:
        row = await departments.get(42, session=session)
        source = await session.get(PermissionProjectionOperation, 9)
        if rollback:
            assert row["state"] == "PROJECTING" and row["operation_id"] == 9
            assert source.status == "PREPARED"
            assert await ledger.record(payload["recovery_id"], 1, session=session) is None
        else:
            assert row["state"] == "FAILED_CLOSED" and row["operation_id"] == identity
            assert source.status == "FAILED_CLOSED"
            assert source.request_checksum == "a" * 64 and source.model_id == "old-model"
            assert source.error_message == "private-original-error-kept-in-sql"
            record = await ledger.record(payload["recovery_id"], 1, session=session)
            assert record["operation_id"] == identity


@pytest.mark.parametrize("rollback", [False, True])
async def test_finalization_receipt_department_and_audit_are_atomic(database, rollback):
    await seed(database)
    departments, ledger = CurrentDepartmentRepairRepository(database), CurrentDepartmentRepairLedger(database)
    async with database() as session:
        async with session.begin():
            before = await departments.get(42, session=session)
            payload = CurrentDepartmentRepairApplication.preview(
                {
                    "department": before,
                    "business": Backend().proof(),
                    "observed": set(),
                    "sources": [(Backend().source, [], True)],
                    "environment": Backend().env,
                }
            )
            identity = await ledger.create_gate(payload, session=session)
            await departments.set_gate(before, identity, session)
            await ledger.append(payload, identity, "prepared", session=session)
    try:
        async with database() as session:
            async with session.begin():
                await ledger.finalize(payload, identity, session=session)
                await departments.finish(before, identity, 8, session)
                if rollback:
                    raise RuntimeError("rollback after final updates")
    except RuntimeError:
        assert rollback
    async with database() as session:
        row = await departments.get(42, session=session)
        operation = await session.get(PermissionProjectionOperation, identity)
        completion = await ledger.record(payload["recovery_id"], 1, session=session, stage="finalized")
        assert row["state"] == ("FAILED_CLOSED" if rollback else "CURRENT")
        assert row["version"] == (7 if rollback else 8)
        assert operation.status == ("FAILED_CLOSED" if rollback else "FINALIZED")
        assert (completion is None) == rollback


async def test_tenant_and_audit_content_are_not_inferred_from_primary_key(database):
    ledger = CurrentDepartmentRepairLedger(database)
    p = CurrentDepartmentRepairApplication.preview(
        {
            "department": Backend().department,
            "business": Backend().proof(),
            "observed": set(),
            "sources": [(Backend().source, [], True)],
            "environment": Backend().env,
        }
    )
    async with database() as session:
        async with session.begin():
            await ledger.append(p, 99, "prepared", session=session)
    with pytest.raises(RecoveryBlockedError, match="IDENTITY"):
        await ledger.record(p["recovery_id"], 2)
    async with database() as session:
        with pytest.raises(RecoveryBlockedError, match="CONTENT"):
            async with session.begin():
                await ledger.append(p, 100, "prepared", session=session)


async def test_guarded_finalize_cannot_steal_later_department_binding(database):
    await seed(database)
    repository = CurrentDepartmentRepairRepository(database)
    async with database() as session:
        async with session.begin():
            before = await repository.get(42, session=session)
            with pytest.raises(ValueError, match="FINALIZE_CONFLICT"):
                await repository.finish(before, 100, 8, session)


@pytest.mark.parametrize("empty", [False, True])
async def test_generic_legacy_parser_fails_closed_on_private_receipt(database, empty):
    from bisheng.common.errcode.permission import PermissionPublishNotReadyError, PermissionVersionConflictError
    from bisheng.permission.domain.models import PermissionProjectionTuple
    from bisheng.permission.domain.services.projection_service import restore_projection_plan

    backend = Backend()
    if empty:
        backend.department["parent_id"] = None
        backend.members = []
    p = CurrentDepartmentRepairApplication.preview(
        {
            "department": backend.department,
            "business": backend.proof(),
            "observed": set(),
            "sources": [(Backend().source, [], True)],
            "environment": backend.env,
        }
    )
    ledger = CurrentDepartmentRepairLedger(database)
    async with database() as session:
        async with session.begin():
            identity = await ledger.create_gate(p, session=session)
            operation = await session.get(PermissionProjectionOperation, identity)
            rows = list(
                (
                    await session.exec(
                        select(PermissionProjectionTuple).where(PermissionProjectionTuple.operation_id == identity)
                    )
                ).all()
            )
            with pytest.raises(PermissionPublishNotReadyError if empty else PermissionVersionConflictError):
                restore_projection_plan(operation, rows)


async def test_normal_online_binding_rejects_gate_and_accepts_repaired_current(database):
    from bisheng.common.errcode.permission import PermissionVersionConflictError
    from bisheng.department.domain.services.department_projection_scope import SqlDepartmentProjectionScope
    from bisheng.permission.domain.services.department_change_handler import (
        DepartmentProjectionContext,
        F048DepartmentChangeHandler,
    )

    await seed(database)
    repository, ledger = CurrentDepartmentRepairRepository(database), CurrentDepartmentRepairLedger(database)
    async with database() as session:
        async with session.begin():
            before = await repository.get(42, session=session)
            p = CurrentDepartmentRepairApplication.preview(
                {
                    "department": before,
                    "business": Backend().proof(),
                    "observed": set(),
                    "sources": [(Backend().source, [], True)],
                    "environment": Backend().env,
                }
            )
            identity = await ledger.create_gate(p, session=session)
            await repository.set_gate(before, identity, session)
    handler = F048DepartmentChangeHandler(projection=None)
    context = DepartmentProjectionContext(
        tenant_id=1,
        department_id=42,
        expected_version=7,
        store_id="s",
        model_id="m",
        operator_id=0,
        idempotency_key="normal-after-f078",
    )
    plan = handler.build_members_added_plan(context=context, user_ids=(10,))
    async with database() as session:
        with pytest.raises(PermissionVersionConflictError):
            async with session.begin():
                await SqlDepartmentProjectionScope().bind(session, plan, 1000)
    async with database() as session:
        async with session.begin():
            await ledger.finalize(p, identity, session=session)
            await repository.finish(before, identity, 8, session)
    from dataclasses import replace

    plan = replace(plan, expected_version=8, target_version=9)
    async with database() as session:
        async with session.begin():
            await SqlDepartmentProjectionScope().bind(session, plan, 1000)
            stored = await repository.get(42, session=session)
            assert stored["state"] == "PROJECTING" and stored["operation_id"] == 1000 and stored["version"] == 8


async def test_actual_runtime_owner_sql_fga_and_reentry_compose(database, monkeypatch):
    """Local composition, not a real FGA/Redis or MySQL/DM8 lock result."""
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    from bisheng.api.services.current_department_repair_runtime import CurrentDepartmentRepairRuntime
    from bisheng.database.models.department import UserDepartment
    from bisheng.department.domain.services.current_projection_repair import CurrentDepartmentRepairService
    from bisheng.permission.application.department_recovery_fga import DepartmentRecoveryFGA
    from bisheng.permission.application.department_recovery_runtime import tenant_scope
    from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository
    from bisheng.permission.domain.services.department_recovery_plan import checksum

    await seed(database)
    async with database() as session:
        connection = await session.connection()
        metadata = sa.MetaData()
        sa.Table(
            "department_knowledge_space",
            metadata,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("department_id", sa.Integer),
            sa.Column("tenant_id", sa.Integer),
        )
        sa.Table("user", metadata, sa.Column("user_id", sa.Integer, primary_key=True))
        SQLModel.metadata.tables["department"].to_metadata(metadata)
        members = SQLModel.metadata.tables["user_department"].to_metadata(metadata)
        members.c.id.type = sa.Integer()
        await connection.run_sync(lambda sync: members.create(sync))
        session.add(
            Department(
                id=3,
                tenant_id=1,
                dept_id="e2e-f078-current-root",
                name="root",
                path="/3/",
                permission_projection_state="CURRENT",
            )
        )
        child = await session.get(Department, 42)
        child.path, child.permission_projection_state = "/3/42/", "FAILED_CLOSED"
        source = await session.get(PermissionProjectionOperation, 9)
        source.status = "FAILED_CLOSED"
        session.add(UserDepartment(id=1, user_id=10, department_id=42, is_primary=1, source="manual"))
        await session.commit()

    class FGA:
        def __init__(self):
            self.keys = {
                ("department:2", "parent", "department:42"),
                ("department:42", "child", "department:2"),
                ("user:11", "member", "department:42"),
            }
            self.writes = 0

        async def iter_tuples(self, **query):
            for user, relation, obj in sorted(self.keys):
                if (
                    relation == query["relation"]
                    and (query["object"] == obj or (query["object"] == "department:" and obj.startswith("department:")))
                    and ("user" not in query or user == query["user"])
                ):
                    yield {"user": user, "relation": relation, "object": obj}

        def validate_business_mutation_size(self, count):
            assert count <= 90

        async def write_tuples(self, writes, deletes):
            self.writes += 1
            self.keys.difference_update((r["user"], r["relation"], r["object"]) for r in deletes)
            self.keys.update((r["user"], r["relation"], r["object"]) for r in writes)

    monkeypatch.setattr("bisheng.api.services.current_department_repair_runtime.get_async_db_session", database)
    runtime = CurrentDepartmentRepairRuntime.__new__(CurrentDepartmentRepairRuntime)
    from contextvars import ContextVar

    runtime._session_context = ContextVar("test_runtime_session", default=None)
    runtime.execution_scope = None
    runtime.verify_execution = AsyncMock()
    runtime.session = None
    runtime.departments = CurrentDepartmentRepairRepository(database)
    runtime.business = CurrentDepartmentRepairService(runtime.departments)
    runtime.ledger = CurrentDepartmentRepairLedger(database)
    runtime.projections = ProjectionRepository(database)
    runtime.client = FGA()
    redis = AsyncMock()
    redis.aget.return_value = "ready"
    runtime.fga = DepartmentRecoveryFGA(runtime.client, redis_factory=AsyncMock(return_value=redis))
    environment = {"store_id": "current-store", "model_id": "current-model"}
    runtime.environment = AsyncMock(return_value=environment)
    runtime.backup_evidence = {"environment_fingerprint": checksum(environment), "reference": "test-only"}
    runtime.window_id, runtime.stale_after_seconds = "test-window", 1800
    runtime.wait_for_request_slot = AsyncMock()

    @asynccontextmanager
    async def transaction():
        async with database() as session:
            async with session.begin(), runtime.projections.bind_session(session):
                runtime.session = session
                try:
                    yield
                finally:
                    runtime.session = None

    runtime._session_context = ContextVar("test_runtime_session", default=None)
    runtime.execution_scope = None
    runtime.verify_execution = AsyncMock()
    runtime.session = None

    runtime.transaction = transaction
    application = CurrentDepartmentRepairApplication(runtime)
    with tenant_scope(1):
        p = (await application.inspect_department(42)).payload
        actual_finish = runtime.departments.finish
        runtime.departments.finish = AsyncMock(side_effect=RuntimeError("injected SQL failure"))
        with pytest.raises(RuntimeError, match="injected"):
            await application.recover_department(p, AsyncMock())
        assert runtime.client.writes == 1
        gate = await runtime.departments.get(42)
        assert gate["state"] == "FAILED_CLOSED" and gate["version"] == 7
        runtime.departments.finish = actual_finish
        assert await application.recover_department(p, AsyncMock()) == "FINALIZED"
        assert runtime.client.writes == 1
        assert await application.recover_department(p, AsyncMock()) == "ALREADY_DONE"
        assert (await runtime.departments.get(42))["version"] == 8


async def test_business_failure_context_identifies_missing_parent_without_mutation(database):
    await seed(database)
    repository = CurrentDepartmentRepairRepository(database)
    before = await repository.get(42)
    detail = await repository.failure_context(before)
    assert detail["missing_parent_id"] == 3 and detail["chain"][0]["id"] == 42
    assert await repository.get(42) == before


async def test_legacy_private_source_requires_exact_known_sealed_v2_record():
    from types import SimpleNamespace
    from uuid import NAMESPACE_URL, uuid5

    from bisheng.permission.domain.services.department_recovery_plan import checksum

    preview = {
        "format": "f078.current-department-production.v2",
        "tenant_id": 1,
        "department_id": 42,
        "department": {"version": 7},
        "environment": {"store_id": "s", "model_id": "m"},
        "observed": [],
        "target": [],
        "correction": [],
    }
    preview["confirmation_checksum"] = checksum(preview)
    recovery_id = uuid5(NAMESPACE_URL, f"bisheng:f078:production:v2:{preview['confirmation_checksum']}:identity").hex
    preview["recovery_id"] = recovery_id
    op = SimpleNamespace(
        id=9,
        tenant_id=1,
        idempotency_key=f"f078-current:{recovery_id}",
        scope_key="42",
        expected_version=7,
        target_version=8,
        store_id="s",
        model_id="m",
        request_checksum=preview["confirmation_checksum"],
        before_checksum=checksum([]),
        after_checksum=checksum([]),
    )
    row = SimpleNamespace(
        tenant_id=1,
        action="permission.department.current_repair.prepared",
        audit_metadata={"operation_id": 9, "preview": preview},
    )
    from unittest.mock import AsyncMock

    db = SimpleNamespace(exec=AsyncMock(return_value=SimpleNamespace(first=lambda: row)))
    ledger = CurrentDepartmentRepairLedger()
    await ledger.verify_legacy_record(op, [], session=db)
    row.audit_metadata["preview"]["target"] = [["user:7", "member", "department:42"]]
    with pytest.raises(RecoveryBlockedError, match="SEAL_INVALID"):
        await ledger.verify_legacy_record(op, [], session=db)
