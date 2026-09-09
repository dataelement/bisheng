"""Complete ancestry, projection fencing, mount paths and fresh membership."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, event
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.department import Department, UserDepartment
from bisheng.department.domain.repositories import permission_context_repository as repository_module
from bisheng.department.domain.repositories.permission_context_repository import DepartmentContextRow
from bisheng.department.domain.services.permission_context import DepartmentPermissionContextProvider


@pytest.fixture
async def database(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    metadata = MetaData()
    Table("user", metadata, Column("user_id", Integer, primary_key=True))
    for name in ("department", "user_department"):
        table = SQLModel.metadata.tables[name].to_metadata(metadata)
        table.c.id.type = Integer()
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)

    @asynccontextmanager
    async def factory():
        with bypass_tenant_filter():
            async with AsyncSession(engine, expire_on_commit=False) as session:
                yield session

    monkeypatch.setattr(repository_module, "get_async_db_session", factory)
    yield engine, factory
    await engine.dispose()


async def test_repository_reads_only_user_ancestry_and_observes_move_and_removal(database):
    engine, factory = database
    async with factory() as session:
        # The shared root and mounted child can belong to different tenants.
        session.add_all(
            [
                Department(id=1, dept_id="root", name="root", tenant_id=1),
                Department(id=2, dept_id="child", name="child", parent_id=1, tenant_id=2),
                Department(id=3, dept_id="leaf", name="leaf", parent_id=2, tenant_id=2),
                Department(id=4, dept_id="other", name="other", tenant_id=2),
                UserDepartment(id=1, user_id=10, department_id=3),
                UserDepartment(id=2, user_id=20, department_id=4),
            ]
        )
        await session.commit()
    reads = []

    def track(_, __, statement, parameters, ___, ____):
        if statement.lstrip().upper().startswith("SELECT"):
            reads.append((statement, parameters))

    event.listen(engine.sync_engine, "before_cursor_execute", track)
    provider = DepartmentPermissionContextProvider()
    assert (await provider.load(10)).subtree_department_ids == (1, 2, 3)
    assert len(reads) == 4
    assert all("WHERE" in statement.upper() for statement, _ in reads)
    async with factory() as session:
        child = await session.get(Department, 2)
        child.parent_id = 4
        await session.commit()
    assert (await provider.load(10)).subtree_department_ids == (2, 3, 4)
    assert (await provider.load(20)).subtree_department_ids == (4,)
    async with factory() as session:
        await session.delete(await session.get(UserDepartment, 1))
        await session.commit()
    assert (await provider.load(10)).subtree_department_ids == ()


@pytest.mark.parametrize(
    "state,status", [("PROJECTING", "active"), ("FAILED_CLOSED", "active"), ("CURRENT", "archived")]
)
async def test_incomplete_facts_are_errors(state, status):
    repository = AsyncMock()
    repository.load_ancestry.return_value = (
        (2,),
        {
            2: DepartmentContextRow(2, 1, 1, "active", "CURRENT"),
            1: DepartmentContextRow(1, None, 1, status, state),
        },
    )
    with pytest.raises(PermissionPublishNotReadyError):
        await DepartmentPermissionContextProvider(repository).load(10)


async def test_cycles_and_missing_ancestors_are_errors():
    repository = AsyncMock()
    for rows in (
        {2: DepartmentContextRow(2, 1, 1, "active", "CURRENT")},
        {
            2: DepartmentContextRow(2, 1, 1, "active", "CURRENT"),
            1: DepartmentContextRow(1, 2, 1, "active", "CURRENT"),
        },
    ):
        repository.load_ancestry.return_value = ((2,), rows)
        with pytest.raises(PermissionPublishNotReadyError):
            await DepartmentPermissionContextProvider(repository).load(10)


async def test_repository_overflow_and_orphan_fail_before_returning_context(database):
    _, factory = database
    async with factory() as session:
        session.add_all([UserDepartment(id=n, user_id=10, department_id=n) for n in range(1, 102)])
        await session.commit()
    with pytest.raises(PermissionPublishNotReadyError, match="100"):
        await DepartmentPermissionContextProvider().load(10)
    async with factory() as session:
        session.add(UserDepartment(id=200, user_id=20, department_id=999))
        await session.commit()
    with pytest.raises(PermissionPublishNotReadyError, match="incomplete"):
        await DepartmentPermissionContextProvider().load(20)
