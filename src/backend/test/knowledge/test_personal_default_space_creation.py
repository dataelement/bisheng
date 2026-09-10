"""默认个人库并发创建的回归验证。"""

import asyncio
import importlib
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from bisheng.common.errcode.knowledge_space import PersonalDefaultSpaceCreationBusyError
from bisheng.knowledge.domain.models import knowledge as knowledge_model
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.repositories.implementations import knowledge_migration_lock_repository_impl as locks
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.knowledge.domain.services.personal_default_space_creation_guard import PersonalDefaultSpaceCreationGuard

# 共享测试环境预先替换了 redis, 按现有队列测试方式隔离加载真实依赖。
_REDIS_MODULES = {
    name: sys.modules.pop(name) for name in list(sys.modules) if name == "redis" or name.startswith("redis.")
}
try:
    importlib.import_module("redis")
    fakeredis = importlib.import_module("fakeredis")
finally:
    for name in [name for name in list(sys.modules) if name == "redis" or name.startswith("redis.")]:
        sys.modules.pop(name, None)
    sys.modules.update(_REDIS_MODULES)


@pytest.fixture
async def redis_client(monkeypatch):
    redis = fakeredis.FakeAsyncRedis()
    monkeypatch.setattr(locks, "get_redis_client", AsyncMock(return_value=SimpleNamespace(async_connection=redis)))
    yield redis
    await redis.aclose()


def service(user_id=7, tenant_id=1):
    instance = KnowledgeSpaceService.__new__(KnowledgeSpaceService)
    instance.login_user = SimpleNamespace(user_id=user_id, tenant_id=tenant_id, user_name="张三")
    instance.request = None
    instance._resolve_default_tag_library_id = AsyncMock(return_value=12)
    return instance


async def test_concurrent_missing_default_creates_once(redis_client):
    callers = 12
    first_reads = 0
    all_read = asyncio.Event()
    created = []

    async def find():
        nonlocal first_reads
        if first_reads < callers:
            first_reads += 1
            if first_reads == callers:
                all_read.set()
            await all_read.wait()
            return None
        return created[0] if created else None

    async def create(**kwargs):
        # 给其他并发请求充分机会进入创建阶段。
        await asyncio.sleep(0.02)
        space = Knowledge(id=200 + len(created), name="张三的知识库", user_id=7, type=3)
        created.append(space)
        return space

    instances = [service() for _ in range(callers)]
    for instance in instances:
        instance._find_personal_default_space = find
        instance.create_knowledge_space = create
    results = await asyncio.wait_for(asyncio.gather(*(s.ensure_personal_default_space() for s in instances)), timeout=5)
    assert len(created) == 1
    assert {s.id for s in results} == {200}


async def test_existing_space_needs_no_redis(monkeypatch):
    instance = service()
    instance._find_personal_default_space = AsyncMock(return_value=Knowledge(id=100, name="张三的知识库"))
    instance.create_knowledge_space = AsyncMock()
    lock = AsyncMock(side_effect=ConnectionError("Redis offline"))
    monkeypatch.setattr(locks, "get_redis_client", lock)
    assert (await instance.ensure_personal_default_space()).id == 100
    instance.create_knowledge_space.assert_not_awaited()
    lock.assert_not_awaited()


async def test_different_tenants_and_users_do_not_block(redis_client):
    guards = [PersonalDefaultSpaceCreationGuard(tid, uid) for tid, uid in [(1, 7), (1, 8), (2, 7)]]
    entered = 0
    all_entered = asyncio.Event()

    async def operation():
        nonlocal entered
        entered += 1
        if entered == 3:
            all_entered.set()
        await all_entered.wait()
        return "done"

    assert await asyncio.wait_for(asyncio.gather(*(g.run(operation) for g in guards)), 2) == ["done"] * 3
    assert await redis_client.keys("knowledge:personal-default:*") == []


@pytest.mark.parametrize("failure", ["contention", "connection", "timeout"])
async def test_lock_failure_never_creates(redis_client, monkeypatch, failure):
    instance = service()
    instance._find_personal_default_space = AsyncMock(return_value=None)
    instance.create_knowledge_space = AsyncMock()
    monkeypatch.setattr(PersonalDefaultSpaceCreationGuard, "WAIT_SECONDS", 0.04)
    monkeypatch.setattr(PersonalDefaultSpaceCreationGuard, "IO_TIMEOUT_SECONDS", 0.01)
    key = PersonalDefaultSpaceCreationGuard(1, 7).key
    if failure == "contention":
        await redis_client.set(key, "another-owner", ex=60)
    elif failure == "connection":
        monkeypatch.setattr(
            locks.KnowledgeMigrationLockRepositoryImpl, "acquire", AsyncMock(side_effect=ConnectionError())
        )
    else:

        async def stalled(*args, **kwargs):
            await asyncio.Event().wait()

        monkeypatch.setattr(locks.KnowledgeMigrationLockRepositoryImpl, "acquire", stalled)
    with pytest.raises(PersonalDefaultSpaceCreationBusyError):
        await instance.ensure_personal_default_space()
    instance.create_knowledge_space.assert_not_awaited()
    if failure == "contention":
        assert await redis_client.get(key) == b"another-owner"


async def test_long_creation_renews_lease(redis_client):
    guard = PersonalDefaultSpaceCreationGuard(1, 7)
    guard.TTL_SECONDS = 1
    guard.RENEW_SECONDS = 0.1

    async def operation():
        await asyncio.sleep(1.2)
        other = PersonalDefaultSpaceCreationGuard(1, 7)
        assert not await other.repository.acquire("competitor", ttl_seconds=1)
        return 123

    assert await guard.run(operation) == 123
    assert await redis_client.get(guard.key) is None


@pytest.mark.parametrize("failure", ["lost", "connection"])
async def test_renewal_failure_cancels_creation_before_release(redis_client, monkeypatch, failure):
    guard = PersonalDefaultSpaceCreationGuard(1, 7)
    guard.RENEW_SECONDS = 0.01
    stopped = asyncio.Event()

    async def operation():
        try:
            if failure == "lost":
                await redis_client.set(guard.key, "new-owner", ex=60)
            await asyncio.Event().wait()
        finally:
            stopped.set()

    if failure == "connection":
        monkeypatch.setattr(guard.repository, "renew", AsyncMock(side_effect=ConnectionError()))
    with pytest.raises(PersonalDefaultSpaceCreationBusyError):
        await guard.run(operation)
    assert stopped.is_set()
    assert await redis_client.get(guard.key) == (b"new-owner" if failure == "lost" else None)


@pytest.mark.parametrize("failure", ["cancel", "create"])
async def test_cancel_and_create_failure_release_lock(redis_client, failure):
    guard = PersonalDefaultSpaceCreationGuard(1, 7)
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def operation():
        started.set()
        try:
            if failure == "create":
                raise ValueError("create failed")
            await asyncio.Event().wait()
        finally:
            stopped.set()

    task = asyncio.create_task(guard.run(operation))
    await started.wait()
    if failure == "cancel":
        task.cancel()
    with pytest.raises(asyncio.CancelledError if failure == "cancel" else ValueError):
        await task
    assert stopped.is_set()
    assert await redis_client.get(guard.key) is None
    assert await guard.run(AsyncMock(return_value=200)) == 200


async def test_release_failure_does_not_repeat_creation(redis_client, monkeypatch):
    guard = PersonalDefaultSpaceCreationGuard(1, 7)
    monkeypatch.setattr(guard.repository, "release", AsyncMock(side_effect=ConnectionError()))
    create = AsyncMock(return_value=200)
    assert await guard.run(create) == 200
    create.assert_awaited_once()
    assert 0 < await redis_client.ttl(guard.key) <= guard.TTL_SECONDS


async def test_owner_entry_restores_identity_on_creation_failure(redis_client):
    instance = service()
    original = instance.login_user
    instance._find_personal_default_space = AsyncMock(return_value=None)
    instance.create_knowledge_space = AsyncMock(side_effect=ValueError("create failed"))
    owner = SimpleNamespace(user_id=99, tenant_id=1, user_name="李四")
    with pytest.raises(ValueError, match="create failed"):
        await instance.ensure_personal_default_space_for_owner(owner)
    assert instance.login_user is original
    assert instance.create_knowledge_space.call_args.kwargs["name"] == "李四的知识库"
    assert await redis_client.keys("knowledge:personal-default:*") == []


async def test_duplicate_default_lookup_returns_lowest_id(async_db_session, monkeypatch):
    session = async_db_session
    await session.exec(
        text(
            "INSERT INTO knowledge (id, user_id, name, type, auth_type) "
            "VALUES (200, 7, '张三的知识库', 3, 'PRIVATE'), (100, 7, '张三的知识库', 3, 'PRIVATE')"
        )
    )
    await session.exec(
        text(
            "INSERT INTO knowledge_space_scope (space_id, level, owner_type, owner_id) VALUES (200, 'personal', 'user', 7), (100, 'personal', 'user', 7)"
        )
    )
    # 故意反转无 ORDER BY 查询的结果, 验证结果不依赖数据库默认顺序。
    await session.exec(text("PRAGMA reverse_unordered_selects = ON"))

    @asynccontextmanager
    async def existing_session():
        yield session

    monkeypatch.setattr(knowledge_model, "get_async_db_session", existing_session)
    result = await knowledge_model.KnowledgeDao.async_get_personal_space_by_owner_name(owner_id=7, name="张三的知识库")
    assert result.id == 100
