"""Migration origin affects personal counts, never tenant/storage occupancy."""

from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core import database
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.core.database import tenant_filter
from bisheng.database.models.department import Department
from bisheng.database.models.tenant import Tenant
from bisheng.knowledge.domain.models import knowledge as module
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeDao
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService, SpaceLimitError
from bisheng.role.domain.services.quota_service import QuotaService
from test.knowledge_unification import test_migration_resource_repository as original


@pytest.fixture
async def native(tmp_path, monkeypatch):
    path = tmp_path / "quota.sqlite"
    sync_engine = sa.create_engine(f"sqlite:///{path}")
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    metadata = sa.MetaData()
    models = (Tenant, Department, *original.MODELS.values())
    for model in models:
        model.__table__.to_metadata(metadata)
    metadata.create_all(sync_engine)
    names = {model.__tablename__ for model in models if "tenant_id" in model.__table__.c}
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | names)
    tenant_filter.register_tenant_filter_events()

    @contextmanager
    def sync_session():
        with Session(sync_engine) as session:
            yield session

    @asynccontextmanager
    async def async_session():
        async with AsyncSession(async_engine) as session:
            yield session

    monkeypatch.setattr(module, "get_sync_db_session", sync_session)
    monkeypatch.setattr(module, "get_async_db_session", async_session)
    monkeypatch.setattr(database, "get_async_db_session", async_session)
    rows = [
        original.resource(ident, tenant=tenant, type=kind, user_id=user, migration_origin=origin)
        for ident, tenant, kind, user, origin in (
            (1, 101, 3, 7, None), (2, 101, 3, 7, "run-A"),
            (3, 101, 3, 7, None), (4, 101, 3, 7, "run-A"),
            (5, 101, 3, 7, ""), (6, 101, 0, 7, None),
            (7, 101, 1, 7, None), (8, 101, 2, 7, None),
            (9, 202, 3, 7, None), (10, 202, 3, 7, "run-B"),
            (11, 101, 3, 8, None), (12, 101, 3, 8, "run-A"),
        )
    ]
    with sync_engine.begin() as connection:
        connection.execute(Knowledge.__table__.insert(), rows)
        connection.execute(DepartmentKnowledgeSpace.__table__.insert(), [
            {"id": i, "tenant_id": 101, "department_id": i, "space_id": i + 2, "created_by": 7}
            for i in (1, 2)
        ])
        connection.execute(KnowledgeFile.__table__.insert(), [
            original.file(i, tenant=t, knowledge_id=k, file_size=size, file_source=source, status=status)
            for i, t, k, size, source, status in (
                (1, 101, 1, 100, "channel", 2), (2, 101, 2, 200, "space_upload", 2),
                (3, 101, 2, 1000, "upload", 2), (4, 101, 2, 400, "space_upload", 3),
                (5, 202, 10, 600, "channel", 7),
            )
        ])
    try:
        yield SimpleNamespace(engine=sync_engine)
    finally:
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.mark.parametrize("tenant,user,exclude,expected", [
    (101, 7, True, 2), (101, 7, False, 3), (202, 7, True, 1), (101, 8, True, 1),
])
async def test_real_sync_and_async_creation_counters_exclude_only_migration_origin(native, tenant, user, exclude, expected):
    with tenant_execution_scope(tenant):
        assert KnowledgeDao.count_spaces_by_user(user, exclude_department_spaces=exclude) == expected
        assert await KnowledgeDao.async_count_spaces_by_user(user, exclude_department_spaces=exclude) == expected


@pytest.mark.parametrize("tenant,user,expected", [(101, 7, 3), (202, 7, 3), (101, 8, 1)])
async def test_quota_display_preserves_original_global_per_user_scope(native, tenant, user, expected):
    with tenant_execution_scope(tenant):
        assert await QuotaService.get_user_resource_count(user, "knowledge_space") == expected


async def test_origin_survives_fresh_sessions_and_owner_change(native):
    with native.engine.begin() as connection:
        connection.execute(sa.update(Knowledge).where(Knowledge.id == 2).values(user_id=8))
    with tenant_execution_scope(101):
        assert KnowledgeDao.count_spaces_by_user(7, True) == 2
        assert await KnowledgeDao.async_count_spaces_by_user(8, True) == 1
        assert await QuotaService.get_user_resource_count(8, "knowledge_space") == 1
        assert {row.id for row in KnowledgeDao.get_spaces_by_user(8)} == {2, 11, 12}


@pytest.mark.parametrize("tenant,expected", [(101, 7), (202, 2)])
async def test_tenant_total_keeps_all_migrated_and_department_spaces(native, tenant, expected):
    with tenant_execution_scope(101):
        assert await QuotaService.get_tenant_resource_count(tenant, "knowledge_space") == expected


async def test_storage_keeps_original_sources_failed_files_and_global_user_scope(native):
    with tenant_execution_scope(101):
        assert await QuotaService.get_user_resource_count(7, "knowledge_space_file") == 1300 / 1024**3
        assert await QuotaService.get_tenant_resource_count(101, "knowledge_space_file") == 700 / 1024**3


async def test_real_creation_gate_uses_same_count_without_changing_role_rules(native, monkeypatch):
    service = object.__new__(KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=7, tenant_id=101)
    effective = AsyncMock(return_value=3)
    monkeypatch.setattr(QuotaService, "get_effective_quota", effective)
    with tenant_execution_scope(101):
        assert await service._assert_space_creation_quota() is None
        effective.return_value = 2
        with pytest.raises(SpaceLimitError):
            await service._assert_space_creation_quota()
        effective.return_value = -1
        assert await service._assert_space_creation_quota() is None


async def test_tenant_chain_remains_exhausted_even_when_personal_migrations_exempt(native, monkeypatch):
    tenant = SimpleNamespace(id=101, parent_tenant_id=None, quota_config={"knowledge_space": 7}, status="active", tenant_name="test")
    monkeypatch.setattr("bisheng.database.models.tenant.TenantDao.aget_by_id", AsyncMock(return_value=tenant))
    monkeypatch.setattr("bisheng.database.models.tenant.TenantDao.aget_children_ids_active", AsyncMock(return_value=[]))
    with tenant_execution_scope(101):
        effective, blocker = await QuotaService._apply_tenant_chain_cap(50, 101, "knowledge_space")
        assert effective == 0
        assert blocker is not None and blocker[2:4] == (7, 7)
