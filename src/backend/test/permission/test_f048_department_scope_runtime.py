"""Durable business scope for F048 department identity projections."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.permission import (
    PermissionPublishNotReadyError,
    PermissionVersionConflictError,
)
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.department import Department
from bisheng.department.domain.services import (
    department_projection_scope as scope_module,
)
from bisheng.department.domain.services import (
    department_service as service_module,
)
from bisheng.department.domain.services.department_projection_scope import (
    DEPARTMENT_PROJECTION_CURRENT,
    DEPARTMENT_PROJECTION_PROJECTING,
    PreparedDepartmentProjection,
    SqlDepartmentProjectionScope,
)
from bisheng.department.domain.services.department_service import (
    DepartmentTopologyProjectionService,
)
from bisheng.permission.domain.services.projection_plan import (
    ProjectionPlan,
    ProjectionTupleDelta,
)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


@pytest.fixture(autouse=True)
def tenant_context() -> AsyncIterator[None]:
    with bypass_tenant_filter():
        yield


@pytest.fixture
async def session_factory() -> AsyncIterator[SessionFactory]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata = sa.MetaData()
    table = SQLModel.metadata.tables["department"].to_metadata(metadata)
    table.c.id.type = sa.Integer()
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(
            engine,
            expire_on_commit=False,
        ) as session:
            yield session

    yield factory
    await engine.dispose()


def _plan() -> ProjectionPlan:
    return ProjectionPlan(
        tenant_id=7,
        idempotency_key="department-scope-v1",
        operation_type="DEPARTMENT_MEMBERS_ADD",
        scope_type="department",
        scope_key="11",
        expected_version=0,
        target_version=1,
        store_id="store-live",
        model_id="model-f048",
        operator_id=0,
        change_item_count=1,
        deltas=(
            ProjectionTupleDelta(
                phase="COMMIT",
                sequence=0,
                action="WRITE",
                user="user:31",
                relation="member",
                object="department:11",
            ),
        ),
    )


def _topology_plan(
    department: Department,
    *,
    operation_id: int,
    action: str,
) -> ProjectionPlan:
    department_id = int(department.id or 0)
    expected_version = int(department.permission_projection_version or 0)
    return ProjectionPlan(
        tenant_id=int(department.tenant_id),
        idempotency_key=f"department-topology-{operation_id}",
        operation_type=action,
        scope_type="department",
        scope_key=str(department_id),
        expected_version=expected_version,
        target_version=expected_version + 1,
        store_id="store-live",
        model_id="model-f048",
        operator_id=0,
        change_item_count=1,
        deltas=(
            ProjectionTupleDelta(
                phase="COMMIT",
                sequence=0,
                action="WRITE",
                user="department:1",
                relation="parent",
                object=f"department:{department_id}",
            ),
        ),
    )


def _wire_topology_runtime(
    *,
    monkeypatch,
    session_factory: SessionFactory,
    operation_id: int,
    expected_operation_type: str,
    expected_status_at_bind: str,
) -> list[str]:
    scope = SqlDepartmentProjectionScope()
    events: list[str] = []

    class Runtime:
        async def bind(
            self,
            session: AsyncSession,
            prepared: PreparedDepartmentProjection,
        ) -> None:
            row = (
                await session.exec(
                    select(Department).where(
                        Department.id == int(prepared.plan.scope_key),
                    )
                )
            ).one()
            assert row.status == expected_status_at_bind
            await scope.bind(
                session,
                prepared.plan,
                prepared.operation_id,
            )
            events.append("bind")

        async def execute(
            self,
            prepared: PreparedDepartmentProjection,
        ) -> None:
            await scope.reserve(
                prepared.plan,
                prepared.operation_id,
            )
            events.append("execute")
            await scope.finalize(
                prepared.plan,
                prepared.operation_id,
            )

        async def abandon(
            self,
            prepared: PreparedDepartmentProjection,
            error: Exception,
        ) -> None:
            del prepared, error
            events.append("abandon")

    runtime = Runtime()

    async def prepare_projection(
        *,
        department: Department,
        login_user,
        operation_type: str,
        operation_facts,
        plan_builder,
    ):
        del login_user, operation_facts, plan_builder
        assert operation_type == expected_operation_type
        plan = _topology_plan(
            department,
            operation_id=operation_id,
            action=operation_type,
        )
        return service_module._PreparedDepartmentProjection(
            runtime=runtime,
            prepared=PreparedDepartmentProjection(
                plan=plan,
                operation_id=operation_id,
            ),
        )

    monkeypatch.setattr(
        service_module,
        "get_async_db_session",
        session_factory,
    )
    monkeypatch.setattr(
        scope_module,
        "get_async_db_session",
        session_factory,
    )
    monkeypatch.setattr(
        service_module,
        "_prepare_department_projection",
        prepare_projection,
    )
    return events


async def test_department_scope_binds_competes_and_finalizes_idempotently(
    session_factory: SessionFactory,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        scope_module,
        "get_async_db_session",
        session_factory,
    )
    async with session_factory() as session:
        async with session.begin():
            session.add(
                Department(
                    id=11,
                    tenant_id=7,
                    dept_id="BS@11",
                    name="R&D",
                    parent_id=1,
                    path="/1/11/",
                    source="local",
                    status="active",
                )
            )

    scope = SqlDepartmentProjectionScope()
    plan = _plan()
    async with session_factory() as session:
        async with session.begin():
            await scope.bind(session, plan, 41)

    await scope.reserve(plan, 41)
    assert await scope.is_expected_version(plan, 41)
    assert not await scope.is_expected_version(plan, 42)

    async with session_factory() as session:
        async with session.begin():
            with pytest.raises(PermissionVersionConflictError):
                await scope.bind(session, plan, 42)

    await scope.finalize(plan, 41)
    await scope.finalize(plan, 41)
    async with session_factory() as session:
        row = (await session.exec(select(Department).where(Department.id == 11))).one()
    assert row.permission_projection_version == 1
    assert row.permission_projection_state == DEPARTMENT_PROJECTION_CURRENT
    assert row.permission_projection_operation_id == 41

    with pytest.raises(PermissionPublishNotReadyError):
        await scope.reserve(plan, 41)


async def test_department_scope_rejects_unbound_prepared_operation(
    session_factory: SessionFactory,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        scope_module,
        "get_async_db_session",
        session_factory,
    )
    async with session_factory() as session:
        async with session.begin():
            session.add(
                Department(
                    id=11,
                    tenant_id=7,
                    dept_id="BS@11",
                    name="R&D",
                    parent_id=1,
                    path="/1/11/",
                    source="local",
                    status="active",
                )
            )

    scope = SqlDepartmentProjectionScope()
    with pytest.raises(PermissionPublishNotReadyError):
        await scope.reserve(_plan(), 41)

    async with session_factory() as session:
        row = (await session.exec(select(Department).where(Department.id == 11))).one()
    assert row.permission_projection_state != DEPARTMENT_PROJECTION_PROJECTING


async def test_synced_department_create_binds_before_projection_execute(
    session_factory: SessionFactory,
    monkeypatch,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            session.add(
                Department(
                    id=1,
                    tenant_id=1,
                    dept_id="BS@root",
                    name="Root",
                    path="/1/",
                    source="local",
                    status="active",
                )
            )

    events = _wire_topology_runtime(
        monkeypatch=monkeypatch,
        session_factory=session_factory,
        operation_id=51,
        expected_operation_type="DEPARTMENT_CREATE",
        expected_status_at_bind="active",
    )
    created = await DepartmentTopologyProjectionService.aupsert_synced_department(
        source="wecom",
        external_id="100",
        name="Engineering",
        parent_id=1,
        parent_path="/1/",
        sort_order=3,
        last_sync_ts=100,
    )

    assert events == ["bind", "execute"]
    async with session_factory() as session:
        row = (
            await session.exec(
                select(Department).where(
                    Department.id == int(created.id),
                )
            )
        ).one()
    assert row.path == f"/1/{row.id}/"
    assert row.permission_projection_version == 1
    assert row.permission_projection_state == DEPARTMENT_PROJECTION_CURRENT
    assert row.permission_projection_operation_id == 51


async def test_synced_department_archive_binds_business_state_before_execute(
    session_factory: SessionFactory,
    monkeypatch,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            session.add(
                Department(
                    id=11,
                    tenant_id=1,
                    dept_id="WECOM@100",
                    external_id="100",
                    name="Engineering",
                    parent_id=1,
                    path="/1/11/",
                    source="wecom",
                    status="active",
                )
            )

    events = _wire_topology_runtime(
        monkeypatch=monkeypatch,
        session_factory=session_factory,
        operation_id=52,
        expected_operation_type="DEPARTMENT_ARCHIVE",
        expected_status_at_bind="archived",
    )
    archived = await DepartmentTopologyProjectionService.aarchive_synced_department(
        department_id=11,
        last_sync_ts=200,
    )

    assert archived is not None
    assert events == ["bind", "execute"]
    async with session_factory() as session:
        row = (await session.exec(select(Department).where(Department.id == 11))).one()
    assert row.status == "archived"
    assert row.is_deleted == 1
    assert row.permission_projection_version == 1
    assert row.permission_projection_state == DEPARTMENT_PROJECTION_CURRENT
    assert row.permission_projection_operation_id == 52


async def test_synced_department_resurrection_restores_same_parent_edge(
    session_factory: SessionFactory,
    monkeypatch,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            session.add(
                Department(
                    id=11,
                    tenant_id=1,
                    dept_id="WECOM@100",
                    external_id="100",
                    name="Old",
                    parent_id=1,
                    path="/1/11/",
                    source="wecom",
                    status="archived",
                    is_deleted=1,
                )
            )

    events = _wire_topology_runtime(
        monkeypatch=monkeypatch,
        session_factory=session_factory,
        operation_id=53,
        expected_operation_type="DEPARTMENT_CREATE",
        expected_status_at_bind="active",
    )
    await DepartmentTopologyProjectionService.aupsert_synced_department(
        source="wecom",
        external_id="100",
        name="Restored",
        parent_id=1,
        parent_path="/1/",
        sort_order=1,
        last_sync_ts=300,
    )

    assert events == ["bind", "execute"]
    async with session_factory() as session:
        row = (await session.exec(select(Department).where(Department.id == 11))).one()
    assert row.status == "active"
    assert row.is_deleted == 0
    assert row.permission_projection_version == 1
    assert row.permission_projection_operation_id == 53
