"""Real SQLite sessions for tenant regression tests; no production services."""

from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import Integer, MetaData, PrimaryKeyConstraint, create_engine
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context import tenant
from bisheng.core.database.tenant_filter import register_tenant_filter_events
from test.app_publish.conftest import _sqlite_ddl_quirks


@contextmanager
def management_scope(home=1, target=2):
    with tenant.tenant_execution_scope(home), tenant.management_tenant_scope(target):
        yield


@pytest.fixture
async def managed_db(tmp_path):
    register_tenant_filter_events()
    path = tmp_path / "managed.sqlite"
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    sync_engine = create_engine(f"sqlite:///{path}")

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    @contextmanager
    def sync_sessions():
        with Session(sync_engine, expire_on_commit=False) as session:
            yield session

    metadata = MetaData()

    def clone(table):
        if table.name in metadata.tables:
            return metadata.tables[table.name]
        copied = table.to_metadata(metadata)
        for fk in table.foreign_keys:
            clone(fk.column.table)
        return copied

    async def create(*models):
        tables = []
        for model in models:
            table = clone(model.__table__)
            if "id" in table.c and table.c.id.autoincrement is True:
                table.c.id.type = Integer()
                if len(table.primary_key.columns) > 1:
                    table.constraints.remove(table.primary_key)
                    for column in table.c:
                        column.primary_key = column.name == "id"
                    table.append_constraint(PrimaryKeyConstraint(table.c.id))
            tables.append(table)
        with _sqlite_ddl_quirks(tables):
            async with engine.begin() as connection:
                for table in tables:
                    await connection.run_sync(lambda conn, table=table: table.create(conn, checkfirst=True))

    yield SimpleNamespace(sessions=sessions, sync_sessions=sync_sessions, create=create)
    await engine.dispose()
    sync_engine.dispose()
