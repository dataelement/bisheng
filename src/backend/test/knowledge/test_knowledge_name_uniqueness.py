from contextlib import asynccontextmanager, contextmanager

import pytest

from bisheng.knowledge.domain.models import knowledge as knowledge_module
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeDao, KnowledgeTypeEnum


def test_get_knowledge_by_name_scopes_duplicate_check_by_type(db_session, monkeypatch):
    db_session.add_all(
        [
            Knowledge(
                id=9101,
                user_id=7,
                tenant_id=1,
                name="shared-name",
                type=KnowledgeTypeEnum.QA.value,
            ),
            Knowledge(
                id=9102,
                user_id=8,
                tenant_id=1,
                name="shared-name",
                type=KnowledgeTypeEnum.NORMAL.value,
            ),
        ]
    )
    db_session.flush()

    @contextmanager
    def get_test_session():
        yield db_session

    monkeypatch.setattr(knowledge_module, "get_sync_db_session", get_test_session)

    assert (
        KnowledgeDao.get_knowledge_by_name(
            "shared-name",
            user_id=7,
            knowledge_type=KnowledgeTypeEnum.NORMAL,
        )
        is None
    )
    duplicate = KnowledgeDao.get_knowledge_by_name(
        "shared-name",
        user_id=7,
        knowledge_type=KnowledgeTypeEnum.QA,
    )
    assert duplicate.id == 9101


@pytest.mark.asyncio
async def test_aget_knowledge_by_name_scopes_duplicate_check_by_type(
    async_db_session,
    monkeypatch,
):
    async_db_session.add_all(
        [
            Knowledge(
                id=9201,
                user_id=7,
                tenant_id=1,
                name="shared-name",
                type=KnowledgeTypeEnum.QA.value,
            ),
            Knowledge(
                id=9202,
                user_id=8,
                tenant_id=1,
                name="shared-name",
                type=KnowledgeTypeEnum.NORMAL.value,
            ),
        ]
    )
    await async_db_session.flush()

    @asynccontextmanager
    async def get_test_session():
        yield async_db_session

    monkeypatch.setattr(knowledge_module, "get_async_db_session", get_test_session)

    assert (
        await KnowledgeDao.aget_knowledge_by_name(
            "shared-name",
            user_id=7,
            knowledge_type=KnowledgeTypeEnum.NORMAL,
        )
        is None
    )
    duplicate = await KnowledgeDao.aget_knowledge_by_name(
        "shared-name",
        user_id=7,
        knowledge_type=KnowledgeTypeEnum.QA,
    )
    assert duplicate.id == 9201
