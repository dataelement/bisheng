"""F130 隔离 SQL 夹具, 不连接真实目录或权限服务。"""

import socket
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import strict_tenant_filter, tenant_execution_scope
from bisheng.database.models.audit_log import AuditLog
from bisheng.database.models.department import Department
from bisheng.database.models.role import Role
from bisheng.database.models.role_access import RoleAccess
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.role.domain.models.external_basic_role import RoleExternalBasicRole
from bisheng.tenant.domain.models.external_provision import TenantExternalProvision
from bisheng.user.domain.models.external_basic_access import UserExternalBasicAccess
from bisheng.user.domain.models.external_identity_projection import UserExternalIdentityProjection
from bisheng.user.domain.models.user import User
from test.fixtures.table_definitions import TABLE_USER_ROLE


@pytest.fixture
async def onboarding_store(tmp_path, monkeypatch):
    from bisheng.common.services.config_service import settings
    from bisheng.core.database.tenant_filter import register_tenant_filter_events

    monkeypatch.setattr(settings.multi_tenant, "enabled", True)
    register_tenant_filter_events()

    def reject_network(*args, **kwargs):
        raise AssertionError("F130 Mock tests forbid network connections")

    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_network)
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "owner.sqlite"))
    tables = [
        m.__table__
        for m in (
            Tenant,
            Department,
            Role,
            RoleAccess,
            UserTenant,
            User,
            AuditLog,
            TenantExternalProvision,
            RoleExternalBasicRole,
            UserExternalBasicAccess,
            UserExternalIdentityProjection,
        )
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=tables))
        await connection.execute(
            text(
                TABLE_USER_ROLE.replace(
                    "role_id INTEGER NOT NULL,", "role_id INTEGER NOT NULL, tenant_id INTEGER NOT NULL DEFAULT 1,"
                )
            )
        )

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    sync_engine = create_engine("sqlite:///" + str(tmp_path / "owner.sqlite"))
    from contextlib import contextmanager

    @contextmanager
    def sync_sessions():
        with Session(sync_engine, expire_on_commit=False) as session:
            yield session

    from bisheng.database.models import role, role_access
    from bisheng.role.domain.services import role_service
    from bisheng.user.domain.models import user_role

    for module in (role_service, role, role_access, user_role):
        monkeypatch.setattr(module, "get_async_db_session", sessions)
        if hasattr(module, "get_sync_db_session"):
            monkeypatch.setattr(module, "get_sync_db_session", sync_sessions)

    with tenant_execution_scope(1), strict_tenant_filter():
        async with sessions() as session:
            session.add(Tenant(id=1, tenant_code="root", tenant_name="Root", root_dept_id=1))
            session.add(Department(id=1, dept_id="ROOT", name="Root", tenant_id=1, path="/1/"))
            session.add_all([Role(id=i, role_name="builtin-" + str(i), tenant_id=1) for i in (1, 2)])
            await session.commit()
        try:
            yield SimpleNamespace(sessions=sessions, engine=engine)
        finally:
            await engine.dispose()
            sync_engine.dispose()
