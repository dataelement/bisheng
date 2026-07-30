from contextlib import asynccontextmanager

import pytest

from bisheng.knowledge.domain.models import knowledge as knowledge_module
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum


class _EmptyResult:
    def all(self):
        return []


class _CapturingSession:
    def __init__(self):
        self.statement = None

    async def exec(self, statement):
        self.statement = statement
        return _EmptyResult()


def _session_factory(session):
    @asynccontextmanager
    async def _context():
        yield session

    return _context


@pytest.mark.asyncio
async def test_first_user_cursor_page_applies_limit(monkeypatch):
    session = _CapturingSession()
    monkeypatch.setattr(knowledge_module, "get_async_db_session", _session_factory(session))

    await KnowledgeDao.aget_user_knowledge(
        user_id=7,
        knowledge_id_extra=[1, 2, 3],
        knowledge_type=KnowledgeTypeEnum.NORMAL,
        page=0,
        limit=21,
        cursor=None,
    )

    assert session.statement._limit_clause.value == 21


@pytest.mark.asyncio
async def test_first_admin_cursor_page_applies_limit(monkeypatch):
    session = _CapturingSession()
    monkeypatch.setattr(knowledge_module, "get_async_db_session", _session_factory(session))

    await KnowledgeDao.aget_all_knowledge(
        knowledge_type=KnowledgeTypeEnum.NORMAL,
        page=0,
        limit=21,
        cursor=None,
    )

    assert session.statement._limit_clause.value == 21
