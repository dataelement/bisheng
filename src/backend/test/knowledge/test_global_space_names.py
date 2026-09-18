"""跨租户名称、个人名称分配与默认库复用回归。"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from bisheng.core.context.tenant import (
    current_tenant_id,
    is_tenant_filter_bypassed,
    set_current_tenant_id,
)
from bisheng.core.database.tenant_filter import register_tenant_filter_events
from bisheng.knowledge.domain.models import knowledge as knowledge_model
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.repositories.implementations.knowledge_repository_impl import KnowledgeRepositoryImpl
from bisheng.knowledge.domain.services import knowledge_space_service as service_module
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def service():
    instance = KnowledgeSpaceService.__new__(KnowledgeSpaceService)
    instance.login_user = SimpleNamespace(user_id=7, tenant_id=1, user_name="张三")
    return instance


@pytest.fixture(autouse=True)
def service_database(monkeypatch):
    @asynccontextmanager
    async def database():
        yield SimpleNamespace()

    monkeypatch.setattr(service_module, "get_async_db_session", database)


@pytest.mark.parametrize(
    "external_id,occupied,expected",
    [
        ("zhangsan0174", [False], "张三的知识库"),
        ("zhangsan0174", [True, False], "张三0174的知识库"),
        ("a7", [True, False], "张三a7的知识库"),
        (None, [True, False], "张三7的知识库"),
        ("zhangsan0174", [True, True, True, False], "张三0174654321的知识库"),
    ],
)
async def test_personal_name_candidates(monkeypatch, external_id, occupied, expected):
    exists = AsyncMock(side_effect=occupied)
    monkeypatch.setattr(KnowledgeRepositoryImpl, "personal_space_name_exists_globally", exists, raising=False)
    monkeypatch.setattr(
        service_module.UserDao, "aget_user", AsyncMock(return_value=SimpleNamespace(external_id=external_id))
    )
    random_values = iter([23456, 554321])
    monkeypatch.setattr("secrets.randbelow", lambda _: next(random_values))
    assert await service()._allocate_personal_default_space_name() == expected
    assert exists.await_count == len(occupied)


async def test_default_lookup_reuses_random_suffix(monkeypatch):
    existing = Knowledge(id=88, user_id=7, name="张三0174123456的知识库", type=3)
    monkeypatch.setattr(
        knowledge_model.KnowledgeDao, "async_get_personal_space_by_owner_name", AsyncMock(return_value=None)
    )
    find = AsyncMock(return_value=existing)
    monkeypatch.setattr(KnowledgeRepositoryImpl, "find_personal_default_space_by_owner", find, raising=False)
    assert (await service()._find_personal_default_space()).id == 88
    find.assert_awaited_once_with(7)


async def test_random_candidates_exhausted_raise_without_accepting_duplicate(monkeypatch):
    from bisheng.common.errcode.knowledge_space import SpaceNameAllocationBusyError

    exists = AsyncMock(return_value=True)
    monkeypatch.setattr(KnowledgeRepositoryImpl, "personal_space_name_exists_globally", exists)
    monkeypatch.setattr(
        service_module.UserDao, "aget_user", AsyncMock(return_value=SimpleNamespace(external_id="0174"))
    )
    with pytest.raises(SpaceNameAllocationBusyError):
        await service()._allocate_personal_default_space_name()
    assert exists.await_count == 22


async def test_long_name_keeps_suffix_within_storage_limit(monkeypatch):
    monkeypatch.setattr(
        KnowledgeRepositoryImpl, "personal_space_name_exists_globally", AsyncMock(side_effect=[True, True, False])
    )
    monkeypatch.setattr(
        service_module.UserDao, "aget_user", AsyncMock(return_value=SimpleNamespace(external_id="0174"))
    )
    monkeypatch.setattr("secrets.randbelow", lambda _: 23456)
    instance = service()
    instance.login_user.user_name = "张" * 200
    name = await instance._allocate_personal_default_space_name()
    assert len(name) == 200
    assert name.endswith("0174123456的知识库")


async def test_global_query_failure_restores_tenant_filter():
    session = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("DB unavailable")))
    with pytest.raises(RuntimeError, match="DB unavailable"):
        await KnowledgeRepositoryImpl(session).personal_space_name_exists_globally("张三的知识库")
    assert not is_tenant_filter_bypassed()


async def test_personal_repository_cross_tenant_check_and_owner_scoped_reuse(async_db_session):
    session = async_db_session
    await session.exec(
        text(
            "INSERT INTO knowledge (id, tenant_id, user_id, name, type, auth_type, is_favorite) VALUES (1, 1, 7, '我的收藏', 3, 'PRIVATE', 1), (2, 2, 8, '张三的知识库', 3, 'PRIVATE', 0), (3, 1, 7, '张三0174123456的知识库', 3, 'PRIVATE', 0), (4, 1, 7, '我的收藏', 3, 'PRIVATE', 0)"
        )
    )
    await session.exec(
        text(
            "INSERT INTO knowledge_space_scope (tenant_id, space_id, level, owner_type, owner_id) VALUES (1, 1, 'personal', 'user', 7), (2, 2, 'personal', 'user', 8), (1, 3, 'personal', 'user', 7), (1, 4, 'personal', 'user', 7)"
        )
    )
    await session.commit()
    register_tenant_filter_events()
    token = set_current_tenant_id(1)
    try:
        repository = KnowledgeRepositoryImpl(session)
        assert await repository.personal_space_name_exists_globally("张三的知识库") is True
        assert not is_tenant_filter_bypassed()
        assert await repository.find_personal_default_space_by_owner(8) is None
        assert (await repository.find_personal_default_space_by_owner(7)).id == 3
    finally:
        current_tenant_id.reset(token)


@pytest.mark.parametrize("level", ["public", "department", "team", "team_ks", None, "personal"])
async def test_name_query_crosses_tenant_and_restores_filter(async_db_session, monkeypatch, level):
    session = async_db_session
    await session.exec(
        text(
            "INSERT INTO knowledge (id, tenant_id, user_id, name, type, auth_type) VALUES (90, 2, 9, '已占用', 3, 'PRIVATE')"
        )
    )
    if level:
        await session.exec(
            text(
                "INSERT INTO knowledge_space_scope (tenant_id, space_id, level, owner_type, owner_id) VALUES (2, 90, :level, 'user', 9)"
            ),
            params={"level": level},
        )
    await session.commit()

    @asynccontextmanager
    async def database():
        yield session

    monkeypatch.setattr(knowledge_model, "get_async_db_session", database)
    register_tenant_filter_events()
    token = set_current_tenant_id(1)
    try:
        found = await knowledge_model.KnowledgeDao.async_get_non_personal_space_by_name(name=" 已占用 ")
        assert bool(found) is (level != "personal")
        assert not is_tenant_filter_bypassed()
        assert (
            await knowledge_model.KnowledgeDao.async_get_non_personal_space_by_name(name="已占用", exclude_id=90)
            is None
        )
    finally:
        current_tenant_id.reset(token)
