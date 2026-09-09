import importlib
from contextlib import asynccontextmanager

import pytest


class FakeRedis:
    def __init__(self):
        self.values: dict[str, object] = {}

    async def aget(self, key: str):
        return self.values.get(key)

    async def aset(self, key: str, value, expiration: int = 3600):
        self.values[key] = value
        return True

    async def asetNx(self, key: str, value, expiration: int = 3600):
        if key in self.values:
            return False
        self.values[key] = value
        return True

    async def adelete(self, key: str):
        return int(self.values.pop(key, None) is not None)


@pytest.fixture
async def open_api_db(monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
    from bisheng.database.models.tenant import UserTenant
    from bisheng.open_api.domain.models import (
        ApiCredential,
        ApiCredentialDelegateScope,
        OpenApiTenantSetting,
        ServiceAccount,
    )
    from bisheng.user.domain.models.user import User

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(User.__table__.create)
        await connection.run_sync(UserTenant.__table__.create)
        await connection.run_sync(ServiceAccount.__table__.create)
        await connection.run_sync(ApiCredential.__table__.create)
        await connection.run_sync(ApiCredentialDelegateScope.__table__.create)
        await connection.run_sync(OpenApiTenantSetting.__table__.create)
    tenant_token = set_current_tenant_id(1)

    @asynccontextmanager
    async def session_factory():
        session = AsyncSession(engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    for module_name in (
        "bisheng.open_api.domain.repositories.credential_repository",
        "bisheng.open_api.domain.repositories.delegate_scope_repository",
        "bisheng.open_api.domain.repositories.owner_repository",
        "bisheng.open_api.domain.repositories.service_account_repository",
        "bisheng.open_api.domain.repositories.tenant_setting_repository",
    ):
        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, "get_async_db_session", session_factory)
    yield session_factory
    current_tenant_id.reset(tenant_token)
    await engine.dispose()


@pytest.fixture
def fake_redis(monkeypatch):
    redis = FakeRedis()

    async def get_fake_redis():
        return redis

    for module_name in (
        "bisheng.open_api.domain.services.credential_service",
        "bisheng.open_api.domain.services.credential_validator",
        "bisheng.open_api.domain.services.tenant_setting_service",
    ):
        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, "get_redis_client", get_fake_redis)
    return redis


@pytest.fixture
def audit_events(monkeypatch):
    events: list[dict] = []

    async def record(**kwargs):
        events.append(kwargs)
        return kwargs

    service_module = importlib.import_module("bisheng.open_api.domain.services.service_account_service")
    monkeypatch.setattr(service_module.AuditLogDao, "ainsert_v2", record)
    return events
