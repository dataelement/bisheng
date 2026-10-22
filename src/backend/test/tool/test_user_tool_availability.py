from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.models.config import Config
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.tool.domain.repositories import user_availability as repository_module
from bisheng.tool.domain.repositories.user_availability import UserToolAvailabilityRepository
from bisheng.tool.domain.services.user_availability import UserToolAvailabilityService, manages_availability


@pytest.fixture
async def availability_store(tmp_path, monkeypatch):
    path = tmp_path / "tool-availability.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    sync_engine = create_engine(f"sqlite:///{path}")
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Config.__table__.create(sync))

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine) as session:
            yield session

    @contextmanager
    def sync_sessions():
        with Session(sync_engine) as session:
            yield session

    monkeypatch.setattr(repository_module, "get_async_db_session", sessions)
    monkeypatch.setattr(repository_module, "get_sync_db_session", sync_sessions)
    token = set_current_tenant_id(2)
    try:
        yield UserToolAvailabilityRepository()
    finally:
        current_tenant_id.reset(token)
        await engine.dispose()
        sync_engine.dispose()


async def test_availability_persists_and_isolates_accounts_and_tenants(availability_store):
    store = availability_store
    assert store.enabled_sync(7, 38)
    await store.save(7, 38, False)
    assert await store.disabled_ids(7) == {38}
    assert not store.enabled_sync(7, 38)
    assert store.enabled_sync(8, 38)
    token = set_current_tenant_id(3)
    try:
        assert await store.disabled_ids(7) == set()
        assert store.enabled_sync(7, 38)
    finally:
        current_tenant_id.reset(token)
    await store.save(7, 38, True)
    assert await store.disabled_ids(7) == set()
    assert store.enabled_sync(7, 38)


async def test_closed_tool_is_denied_by_async_and_sync_execution_guards(availability_store):
    service = UserToolAvailabilityService(7, availability_store)
    await service.save(38, False)
    with pytest.raises(PermissionError):
        await service.ensure_enabled(38)
    with pytest.raises(PermissionError):
        service.ensure_enabled_sync(38)
    await service.ensure_enabled(1)
    await service.save(38, True)
    await service.ensure_enabled(38)
    service.ensure_enabled_sync(38)


async def test_only_managed_search_tools_read_availability():
    repository = SimpleNamespace(disabled_ids=AsyncMock(return_value={38}))
    service = UserToolAvailabilityService(7, repository)
    ordinary = SimpleNamespace(id=1, is_preset=1, tool_key="get_current_time")
    search = SimpleNamespace(id=38, is_preset=1, tool_key="web_search")
    assert not manages_availability(ordinary)
    assert await service.disabled_ids([ordinary]) == set()
    repository.disabled_ids.assert_not_awaited()
    assert await service.disabled_ids([search]) == {38}


def test_missing_tenant_cannot_read_an_account_setting():
    token = current_tenant_id.set(None)
    try:
        with pytest.raises(PermissionError):
            UserToolAvailabilityRepository.prefix(7)
    finally:
        current_tenant_id.reset(token)
