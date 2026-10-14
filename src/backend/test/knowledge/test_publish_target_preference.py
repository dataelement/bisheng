import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, insert
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import current_tenant_id
from bisheng.database.models.user_link import UserLink
from bisheng.knowledge.domain.repositories.implementations.knowledge_publish_target_preference_repository_impl import (
    KnowledgePublishTargetPreferenceRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_publish_target_preference_service import (
    KnowledgePublishTargetPreferenceService,
)


@pytest.fixture
async def preference_db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    users = Table("user", MetaData(), Column("user_id", Integer, primary_key=True))
    async with engine.begin() as conn:
        await conn.run_sync(users.create)
        await conn.run_sync(UserLink.__table__.create)
        await conn.execute(insert(users).values([{"user_id": 7}, {"user_id": 8}]))

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_publish_target_preference_service.get_async_db_session",
        sessions,
    )
    yield sessions
    await engine.dispose()


async def test_separate_groups_accounts_and_sessions_without_tenant_partition(preference_db):
    service = KnowledgePublishTargetPreferenceService()
    await service.save(user_id=7, source_level="personal", target_space_id=30, target_folder_id=301)
    await service.save(user_id=7, source_level="team", target_space_id=40, target_folder_id=None)
    await service.save(user_id=7, source_level="department", target_space_id=50, target_folder_id=501)
    await service.save(user_id=8, source_level="personal", target_space_id=60, target_folder_id=None)
    # 科室与团队使用相同的向部门发布记录。
    await service.save(user_id=7, source_level="team_ks", target_space_id=41, target_folder_id=411)
    token = current_tenant_id.set(99)
    try:
        another_client = KnowledgePublishTargetPreferenceService()
        assert (await another_client.get(user_id=7, source_level="personal")).target_folder_id == 301
        assert (await another_client.get(user_id=7, source_level="team")).target_space_id == 41
        assert (await another_client.get(user_id=7, source_level="department")).target_space_id == 50
        assert (await another_client.get(user_id=8, source_level="personal")).target_space_id == 60
    finally:
        current_tenant_id.reset(token)
    async with preference_db() as session:
        assert len((await session.exec(select(UserLink))).all()) == 4


async def test_replace_and_duplicate_cleanup_preserve_other_link_types(preference_db):
    now = datetime.now()
    async with preference_db() as session:
        session.add_all(
            [
                UserLink(
                    user_id=7,
                    type="publish_target_personal",
                    type_detail='{"v":1,"space":30,"folder":null}',
                    update_time=now,
                ),
                UserLink(
                    user_id=7,
                    type="publish_target_personal",
                    type_detail='{"v":1,"space":31,"folder":311}',
                    update_time=now - timedelta(minutes=1),
                ),
                UserLink(user_id=7, type="knowledge_space_pin", type_detail="30"),
                UserLink(user_id=8, type="publish_target_personal", type_detail='{"v":1,"space":32,"folder":null}'),
            ]
        )
        await session.commit()
    await KnowledgePublishTargetPreferenceService().save(
        user_id=7,
        source_level="personal",
        target_space_id=31,
        target_folder_id=311,
    )
    async with preference_db() as session:
        rows = (await session.exec(select(UserLink))).all()
        own = [row for row in rows if row.user_id == 7 and row.type == "publish_target_personal"]
        assert len(own) == 1
        assert json.loads(own[0].type_detail) == {"v": 1, "space": 31, "folder": 311}
        assert len(own[0].type_detail) <= 255
        assert {(row.user_id, row.type) for row in rows} == {
            (7, "publish_target_personal"),
            (7, "knowledge_space_pin"),
            (8, "publish_target_personal"),
        }


@pytest.mark.parametrize(
    "detail",
    [
        "broken",
        '{"v":2,"space":30,"folder":null}',
        '{"v":1,"space":true,"folder":null}',
        '{"v":1,"space":30,"folder":-1}',
    ],
)
async def test_invalid_record_is_ignored(preference_db, detail):
    async with preference_db() as session:
        session.add(UserLink(user_id=7, type="publish_target_personal", type_detail=detail))
        await session.commit()
    assert await KnowledgePublishTargetPreferenceService().get(user_id=7, source_level="personal") is None


async def test_save_locks_user_before_reading_or_writing():
    session = AsyncMock()
    session.exec.return_value = Mock(first=Mock(return_value=7), all=Mock(return_value=[]))
    session.add = lambda row: None
    await KnowledgePublishTargetPreferenceRepositoryImpl(session).save_detail(
        user_id=7,
        link_type="publish_target_personal",
        detail='{"v":1,"space":30,"folder":null}',
    )
    first_statement = session.exec.await_args_list[0].args[0]
    assert "FOR UPDATE" in str(first_statement)
