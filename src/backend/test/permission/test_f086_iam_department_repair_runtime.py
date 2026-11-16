"""Real local SQL UOW + Owner + maintenance runtime; network/FGA/Redis are fake."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlmodel import SQLModel

from bisheng.api.services.iam_department_repair_runtime import IamDepartmentRepairRuntime
from bisheng.database.models.department import Department, UserDepartment
from bisheng.department.domain.repositories.iam_oneoff_repository import IamOneoffDepartmentRepository
from bisheng.department.domain.services.current_projection_repair import CurrentDepartmentRepairService
from bisheng.department.domain.services.iam_oneoff_repair import IamOneoffDepartmentService
from bisheng.permission.application.current_department_repair import CurrentDepartmentRepairApplication
from bisheng.permission.application.department_recovery_fga import DepartmentRecoveryFGA
from bisheng.permission.application.department_recovery_runtime import tenant_scope
from bisheng.permission.domain.models import PermissionProjectionOperation
from bisheng.permission.domain.repositories.current_department_repair_repository import CurrentDepartmentRepairLedger
from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository
from bisheng.permission.domain.services.department_recovery_plan import checksum
from test.permission import test_f086_current_department_repair_repository as repository_tests

IDENTITY = 98765  # deliberately outside the six historical IDs


@pytest.fixture
async def iam_database():
    async for factory in repository_tests.database.__wrapped__():
        yield factory


async def seed(factory):
    async with factory() as db:
        connection = await db.connection()
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
        for identity, parent, path, status, deleted, external in (
            (1, None, "/1/", "active", 0, "1"),
            (2, 1, "/1/2/", "archived", 1, "2"),
            (3, 1, "/1/3/", "active", 0, "300"),
            (IDENTITY, 2, f"/1/2/{IDENTITY}/", "active", 0, "4294956307"),
        ):
            db.add(
                Department(
                    id=identity,
                    dept_id=str(identity),
                    tenant_id=1,
                    name=str(identity),
                    parent_id=parent,
                    path=path,
                    status=status,
                    is_deleted=deleted,
                    source="wecom",
                    external_id=external,
                    permission_projection_state="FAILED_CLOSED" if identity == IDENTITY else "CURRENT",
                    permission_projection_version=7 if identity == IDENTITY else 0,
                    permission_projection_operation_id=9 if identity == IDENTITY else None,
                )
            )
        db.add(UserDepartment(id=1, user_id=10, department_id=IDENTITY, is_primary=0, source="wecom"))
        db.add(
            PermissionProjectionOperation(
                id=9,
                tenant_id=1,
                idempotency_key="original",
                request_checksum="a" * 64,
                before_checksum="b" * 64,
                after_checksum="c" * 64,
                operation_type="DEPARTMENT_MOVE",
                scope_type="department",
                scope_key=str(IDENTITY),
                expected_version=7,
                target_version=8,
                store_id="old-store",
                model_id="old-model",
                status="FAILED_CLOSED",
                operator_id=0,
            )
        )
        await db.commit()


class FGA:
    def __init__(self):
        self.keys = {
            ("department:2", "parent", f"department:{IDENTITY}"),
            (f"department:{IDENTITY}", "child", "department:2"),
            ("user:11", "member", f"department:{IDENTITY}"),
            ("user:55", "admin", f"department:{IDENTITY}"),
        }
        self.writes = 0

    async def iter_tuples(self, **query):
        for user, relation, obj in sorted(self.keys):
            if (
                relation == query["relation"]
                and (obj == query["object"] or query["object"] == "department:")
                and ("user" not in query or query["user"] == user)
            ):
                yield {"user": user, "relation": relation, "object": obj}

    def validate_business_mutation_size(self, count):
        assert count <= 90

    async def write_tuples(self, writes, deletes):
        self.writes += 1
        self.keys.difference_update((r["user"], r["relation"], r["object"]) for r in deletes)
        self.keys.update((r["user"], r["relation"], r["object"]) for r in writes)


def runtime(factory, client, monkeypatch):
    monkeypatch.setattr("bisheng.api.services.current_department_repair_runtime.get_async_db_session", factory)
    instance = IamDepartmentRepairRuntime.__new__(IamDepartmentRepairRuntime)
    from contextvars import ContextVar

    instance._session_context = ContextVar("test_session", default=None)
    instance.execution_scope = None
    instance.verify_execution = AsyncMock()
    instance.session = None
    instance.departments = IamOneoffDepartmentRepository(factory)
    instance.business = CurrentDepartmentRepairService(instance.departments)
    instance.iam_business = IamOneoffDepartmentService(instance.departments)
    rows = {
        "4294956307": {"id": "4294956307", "parentid": "300", "enable": 1},
        "300": {"id": "300", "parentid": "1", "enable": 1},
    }
    instance.iam_lookup = SimpleNamespace(
        local_source="wecom",
        source_fingerprint="test-iam",
        department=AsyncMock(side_effect=lambda identity: rows[identity]),
    )
    instance.iam_targets = set()
    instance.ledger = CurrentDepartmentRepairLedger(factory)
    instance.projections = ProjectionRepository(factory)
    instance.client = client
    redis = AsyncMock()
    redis.aget.return_value = "ready"
    instance.fga = DepartmentRecoveryFGA(client, redis_factory=AsyncMock(return_value=redis))
    environment = {"store_id": "current-store", "model_id": "current-model"}
    instance.environment = AsyncMock(return_value=environment)
    instance.backup_evidence = {"environment_fingerprint": checksum(environment), "reference": "test"}
    instance.window_id, instance.stale_after_seconds = "test-window", 1800
    instance.wait_for_request_slot = AsyncMock()

    @asynccontextmanager
    async def transaction():
        async with factory() as db:
            async with db.begin(), instance.projections.bind_session(db):
                instance.session = db
                try:
                    yield
                finally:
                    instance.session = None

    instance._session_context = ContextVar("test_session", default=None)
    instance.execution_scope = None
    instance.verify_execution = AsyncMock()
    instance.session = None

    instance.transaction = transaction
    return instance


async def test_current_archived_department_with_raw_membership_is_reported(iam_database):
    await seed(iam_database)
    async with iam_database() as db:
        db.add(UserDepartment(id=2, user_id=20, department_id=2, is_primary=0, source="wecom"))
        await db.commit()
    assert await IamOneoffDepartmentRepository(iam_database).inactive_membership_departments() == {2}


async def test_readonly_preview_t1_rollback_t2_failure_and_restart_reentry(iam_database, monkeypatch):
    database = iam_database
    await seed(database)
    client = FGA()
    backend = runtime(database, client, monkeypatch)
    app = CurrentDepartmentRepairApplication(backend)
    with tenant_scope(1):
        preview = (await app.inspect_department(IDENTITY)).payload
        assert preview["classification"] == "RECOVER_REPARENT"
        assert preview["reparent"]["target"]["parent_id"] == 3
        assert preview["business"]["direct_members"] == [10]
        assert (await backend.departments.get(IDENTITY))["parent_id"] == 2 and client.writes == 0
        append = backend.ledger.append
        backend.ledger.append = AsyncMock(side_effect=RuntimeError("T1 failure"))
        with pytest.raises(RuntimeError, match="T1 failure"):
            await app.recover_department(preview, AsyncMock())
        assert (await backend.departments.get(IDENTITY))["parent_id"] == 2
        assert await backend.record(preview["recovery_id"]) is None and client.writes == 0
        backend.ledger.append = append
        backend.departments.finish = AsyncMock(side_effect=RuntimeError("T2 SQL failure"))
        with pytest.raises(RuntimeError, match="T2 SQL failure"):
            await app.recover_department(preview, AsyncMock())
        row = await backend.departments.get(IDENTITY)
        assert row["parent_id"] == 3 and row["state"] == "FAILED_CLOSED" and row["version"] == 7
        assert client.writes == 1
        assert ("user:55", "admin", f"department:{IDENTITY}") in client.keys
        restarted = runtime(database, client, monkeypatch)
        await restarted.prepare_external_facts(preview)
        readonly_resume = await restarted.snapshot(IDENTITY)
        assert checksum(readonly_resume["business"]) == preview["business_checksum"]
        resumed = CurrentDepartmentRepairApplication(restarted)
        assert await resumed.recover_department(preview, AsyncMock()) == "FINALIZED"
        assert client.writes == 1
        assert await resumed.recover_department(preview, AsyncMock()) == "ALREADY_DONE"
        final = await restarted.departments.get(IDENTITY)
        assert final["state"] == "CURRENT" and final["version"] == 8 and final["parent_id"] == 3
