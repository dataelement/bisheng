"""全局名称锁使用真实 Redis 协议验证并发及失败路径。"""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.knowledge_space import SpaceNameAllocationBusyError, SpaceNameDuplicateError
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.repositories.implementations.knowledge_repository_impl import KnowledgeRepositoryImpl
from bisheng.knowledge.domain.services import knowledge_space_service as service_module
from bisheng.knowledge.domain.services.knowledge_space_name_guard import (
    KnowledgeSpaceNameGuard,
    serialize_space_name_write,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from test.knowledge.test_personal_default_space_creation import redis_client as _redis_client

redis_client = _redis_client


async def test_concurrent_names_are_serialized(redis_client):
    names = set()

    @serialize_space_name_write()
    async def create(tenant_id, name):
        if name in names:
            raise SpaceNameDuplicateError()
        await asyncio.sleep(0.02)
        names.add(name)
        return tenant_id

    results = await asyncio.gather(*(create(tid, "同名库") for tid in range(1, 5)), return_exceptions=True)
    assert sum(isinstance(result, int) for result in results) == 1
    assert sum(isinstance(result, SpaceNameDuplicateError) for result in results) == 3
    assert await redis_client.get(KnowledgeSpaceNameGuard().key) is None


async def test_rename_and_create_share_lock(redis_client):
    occupied = set()

    async def write(name):
        if name in occupied:
            raise SpaceNameDuplicateError()
        await asyncio.sleep(0.02)
        occupied.add(name)

    create = serialize_space_name_write()(write)

    @serialize_space_name_write(only_when_named=True)
    async def rename(space_id, name=None):
        await write(name)

    results = await asyncio.gather(create("目标"), rename(1, "目标"), return_exceptions=True)
    assert results.count(None) == 1
    assert sum(isinstance(result, SpaceNameDuplicateError) for result in results) == 1


@pytest.mark.parametrize("failure", ["busy", "connection"])
async def test_busy_guard_never_calls_write(redis_client, monkeypatch, failure):
    guard = KnowledgeSpaceNameGuard()
    guard.WAIT_SECONDS = 0.02
    await redis_client.set(guard.key, "other-owner", ex=60)
    if failure == "connection":
        monkeypatch.setattr(guard.repository, "acquire", AsyncMock(side_effect=ConnectionError("Redis offline")))
    operation = AsyncMock()
    with pytest.raises(SpaceNameAllocationBusyError):
        await guard.run(operation)
    operation.assert_not_awaited()
    assert await redis_client.get(guard.key) == b"other-owner"


async def test_unnamed_update_does_not_require_name_lock(monkeypatch):
    monkeypatch.setattr(KnowledgeSpaceNameGuard, "run", AsyncMock(side_effect=AssertionError("unexpected lock")))

    @serialize_space_name_write(only_when_named=True)
    async def update(space_id, name=None):
        return space_id

    assert await update(7) == 7


@pytest.mark.parametrize("level", [KnowledgeSpaceLevelEnum.PERSONAL, KnowledgeSpaceLevelEnum.TEAM])
async def test_different_tenants_cannot_create_duplicate_names(redis_client, monkeypatch, level):
    created = []

    @asynccontextmanager
    async def session():
        yield SimpleNamespace()

    async def exists(name):
        return any(row.name == name for row in created)

    async def insert(request, login_user, knowledge, **kwargs):
        await asyncio.sleep(0.01)
        knowledge.id = len(created) + 1
        created.append(knowledge)
        return knowledge

    async def find_non_personal(*, name, exclude_id=None):
        return next((row for row in created if row.name == name and row.id != exclude_id), None)

    monkeypatch.setattr(service_module, "get_async_db_session", session)
    monkeypatch.setattr(service_module, "_require_not_write_frozen", AsyncMock())
    monkeypatch.setattr(KnowledgeRepositoryImpl, "personal_space_name_exists_globally", AsyncMock(side_effect=exists))
    monkeypatch.setattr(
        service_module.UserDao, "aget_user", AsyncMock(return_value=SimpleNamespace(external_id="zhangsan0174"))
    )
    monkeypatch.setattr(
        service_module.LLMService,
        "get_workbench_llm",
        AsyncMock(return_value=SimpleNamespace(embedding_model=SimpleNamespace(id=1))),
    )
    monkeypatch.setattr(service_module.KnowledgeService, "acreate_knowledge_base", insert)
    monkeypatch.setattr(
        service_module.KnowledgeDao, "async_get_non_personal_space_by_name", AsyncMock(side_effect=find_non_personal)
    )
    monkeypatch.setattr(
        service_module.KnowledgeDao, "async_get_personal_space_by_owner_name", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(service_module.SpaceChannelMemberDao, "async_insert_member", AsyncMock())
    monkeypatch.setattr(service_module.OwnerService, "write_owner_tuple", AsyncMock())
    monkeypatch.setattr(service_module.KnowledgeAuditTelemetryService, "audit_create_knowledge_space", AsyncMock())
    instances = []
    for uid in (7, 8, 9):
        svc = KnowledgeSpaceService.__new__(KnowledgeSpaceService)
        svc.login_user = SimpleNamespace(user_id=uid, tenant_id=uid, user_name="张三")
        svc.request = None
        svc._created_space_scope_by_id = {}
        svc._resolve_space_scope_on_create = AsyncMock(return_value=(level, "user", uid))
        svc._create_space_scope = AsyncMock()
        svc._enqueue_knowledge_space_index_init = lambda *args: None
        svc._enqueue_default_scope_permissions = lambda **kwargs: None
        instances.append(svc)
    rows = await asyncio.gather(
        *(svc.create_knowledge_space(name="张三的知识库", space_level=level, system_managed=True) for svc in instances),
        return_exceptions=True,
    )
    if level == KnowledgeSpaceLevelEnum.PERSONAL:
        assert len({row.name for row in rows}) == 3
        assert "张三的知识库" in {row.name for row in rows}
        assert "张三0174的知识库" in {row.name for row in rows}
        assert all(row.name.startswith("张三") and row.name.endswith("的知识库") for row in rows)
    else:
        assert len(created) == 1
        assert sum(isinstance(row, SpaceNameDuplicateError) for row in rows) == 2
