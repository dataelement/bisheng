"""A tenant view keeps shared role definitions but excludes foreign custom roles."""

from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context import tenant
from bisheng.core.database import tenant_filter
from bisheng.database.models.role import Role, RoleDao
from test.app_publish.conftest import _sqlite_ddl_quirks


@pytest.mark.parametrize("global_view,expected", [(False, {2, 4}), (True, {2, 3, 4, 5})])
async def test_catalog_and_custom_roles_follow_the_view(monkeypatch, global_view, expected):
    from bisheng.database.models import role as module

    tenant_filter.register_tenant_filter_events()
    engine = create_async_engine("sqlite+aiosqlite://")
    with _sqlite_ddl_quirks([Role.__table__]):
        async with engine.begin() as conn:
            await conn.run_sync(Role.__table__.create)

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as s:
            yield s

    monkeypatch.setattr(module, "get_async_db_session", sessions)
    with tenant.bypass_tenant_filter():
        async with sessions() as s:
            for ident, tid, kind in [(2, 1, "global"), (3, 1, "tenant"), (4, 2, "tenant"), (5, 3, "tenant")]:
                s.add(Role(id=ident, role_name=str(ident), tenant_id=tid, role_type=kind))
            await s.commit()
    bindings = [
        (tenant.current_tenant_id, 1),
        (tenant._admin_scope_tenant_id, None if global_view else 2),
        (tenant._is_management_api, True),
        (tenant.visible_tenant_ids, frozenset({2})),
        (tenant._management_all_tenants, global_view),
    ]
    tokens = [(v, v.set(value)) for v, value in bindings]
    try:
        rows = await RoleDao.aget_visible_roles(None if global_view else 2)
        assert {r.id for r in rows} == expected
        assert (await RoleDao.aget_role_by_id(2)).role_type == "global"
        foreign = await RoleDao.aget_role_by_id(5)
        assert (foreign is not None) == global_view
    finally:
        for var, token in reversed(tokens):
            var.reset(token)
        await engine.dispose()


def test_user_role_mapping_is_shared_with_domain_import():
    from bisheng.database.models.user_role import UserRole
    from bisheng.user.domain.models.user_role import UserRole as DomainUserRole

    assert DomainUserRole is UserRole
    assert UserRole.__tablename__ == "userrole"
    assert not UserRole.__table__.c.tenant_id.nullable
