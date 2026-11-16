"""AC-08, AC-17, AC-19: isolation and lease/session ownership."""

from contextlib import asynccontextmanager

import pytest

from bisheng.core.context import tenant
from bisheng.core.lock.token_safe_redis_lock import RedisLockLostError, TokenSafeRedisLock
from bisheng.permission.domain.repositories.catalog_repository import _RepositorySessionMixin


def test_exact_tenant_cancels_outer_bypass_and_admin_override():
    old = tenant.set_current_tenant_id(3)
    admin = tenant.set_admin_scope_tenant_id(9)
    try:
        with tenant.bypass_tenant_filter():
            with tenant.exact_tenant_filter(7):
                assert tenant.get_current_tenant_id() == 7
                assert not tenant.is_tenant_filter_bypassed()
                assert tenant.is_strict_tenant_filter()
            assert tenant.is_tenant_filter_bypassed()
            assert tenant.get_current_tenant_id() == 9
    finally:
        tenant.current_tenant_id.reset(old)
        tenant._admin_scope_tenant_id.reset(admin)


async def test_session_binding_is_nested_and_restored():
    @asynccontextmanager
    async def factory():
        yield "default"

    repo = _RepositorySessionMixin(factory)
    async with repo.bind_session("outer"):
        async with repo._session(write=True) as session:
            assert session == "outer"
        with pytest.raises(RuntimeError):
            async with repo.bind_session("inner"):
                raise RuntimeError("rollback")
        async with repo._session() as session:
            assert session == "outer"
    async with repo._session() as session:
        assert session == "default"


async def test_remote_lock_token_must_be_verified_before_mutation():
    class Redis:
        async def eval(self, *args):
            return 0

    lock = TokenSafeRedisLock(Redis(), "d:7:11", ttl_seconds=30, renewal_interval_seconds=10)
    lock._owned = True
    with pytest.raises(RedisLockLostError):
        await lock.verify_owned()


async def test_actual_operation_probe_sql_is_tenant_filtered_inside_outer_bypass():
    from contextlib import asynccontextmanager

    import sqlalchemy as sa
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel import SQLModel
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.core.database import tenant_filter
    from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository

    engine = create_async_engine("sqlite+aiosqlite://")
    metadata = sa.MetaData()
    table = SQLModel.metadata.tables["permission_projection_operation"].to_metadata(metadata)
    table.c.id.type = sa.Integer()
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    tenant_filter.register_tenant_filter_events()
    tenant_filter._tenant_aware_tables.add("permission_projection_operation")
    captured = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def record(conn, cursor, statement, parameters, context, executemany):
        captured.append((statement, parameters))

    @asynccontextmanager
    async def factory():
        async with AsyncSession(engine) as db:
            yield db

    try:
        with tenant.bypass_tenant_filter():
            with tenant.exact_tenant_filter(7):
                assert await ProjectionRepository(factory).adepartment_active_ids(11) == []
            assert tenant.is_tenant_filter_bypassed()
        assert len(captured) == 4
        for sql, parameters in captured:
            assert "tenant_id = ?" in sql and 7 in parameters
            assert "status IN" not in sql and "ORDER BY" not in sql and "error_message" not in sql
    finally:
        await engine.dispose()
