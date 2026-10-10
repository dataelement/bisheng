"""F064: document-KB outer list abnormal file flag and filter."""

from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from bisheng.common.schemas.api import PageInfiniteCursorData
from bisheng.knowledge.domain.models import knowledge as knowledge_module
from bisheng.knowledge.domain.models import knowledge_file as knowledge_file_module
from bisheng.knowledge.domain.models.knowledge import (
    Knowledge,
    KnowledgeDao,
    KnowledgeState,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    ABNORMAL_FILE_STATUSES,
    KnowledgeFileDao,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.services import knowledge_service as ks_mod
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService


class _EmptyResult:
    def all(self):
        return []


class _ListResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _CapturingSession:
    def __init__(self, rows=None):
        self.statement = None
        self._rows = rows or []

    async def exec(self, statement):
        self.statement = statement
        return _ListResult(self._rows) if self._rows else _EmptyResult()


def _session_factory(session):
    @asynccontextmanager
    async def _context():
        yield session

    return _context


def _knowledge(kid: int, *, knowledge_type: KnowledgeTypeEnum = KnowledgeTypeEnum.NORMAL) -> Knowledge:
    stamp = datetime(2026, 9, 10, 8, 0)
    return Knowledge(
        id=kid,
        user_id=41,
        tenant_id=7,
        name=f"kb-{kid}",
        type=knowledge_type.value,
        state=KnowledgeState.PUBLISHED.value,
        create_time=stamp,
        update_time=stamp,
    )


def _compile(statement) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": True})).lower()


@pytest.mark.asyncio
async def test_async_exists_abnormal_files_batch_empty():
    assert await KnowledgeFileDao.async_exists_abnormal_files_batch([]) == set()


@pytest.mark.asyncio
async def test_async_exists_abnormal_files_batch_query_and_ids(monkeypatch):
    session = _CapturingSession(rows=[11, 13])
    monkeypatch.setattr(knowledge_file_module, "get_async_db_session", _session_factory(session))

    found = await KnowledgeFileDao.async_exists_abnormal_files_batch([11, 12, 13])

    assert found == {11, 13}
    sql = _compile(session.statement)
    assert "knowledgefile" in sql
    for status in ABNORMAL_FILE_STATUSES:
        assert str(status) in sql
    assert str(KnowledgeFileStatus.PROCESSING.value) not in sql.split("in (")[-1]


@pytest.mark.asyncio
async def test_aget_all_knowledge_has_abnormal_adds_exists(monkeypatch):
    session = _CapturingSession()
    monkeypatch.setattr(knowledge_module, "get_async_db_session", _session_factory(session))

    await KnowledgeDao.aget_all_knowledge(
        knowledge_type=KnowledgeTypeEnum.NORMAL,
        has_abnormal=True,
        limit=21,
        cursor=None,
    )

    sql = _compile(session.statement)
    assert "exists" in sql
    assert "knowledgefile" in sql
    for status in ABNORMAL_FILE_STATUSES:
        assert str(status) in sql


@pytest.mark.asyncio
async def test_aget_all_knowledge_without_filter_skips_exists(monkeypatch):
    session = _CapturingSession()
    monkeypatch.setattr(knowledge_module, "get_async_db_session", _session_factory(session))

    await KnowledgeDao.aget_all_knowledge(
        knowledge_type=KnowledgeTypeEnum.NORMAL,
        limit=21,
        cursor=None,
    )

    sql = _compile(session.statement)
    assert "exists" not in sql


@pytest.mark.asyncio
async def test_aconvert_marks_only_document_kb_abnormal(monkeypatch):
    async def _fake_batch(ids):
        assert 1 in ids
        assert 2 not in ids
        return {1}

    monkeypatch.setattr(KnowledgeFileDao, "async_exists_abnormal_files_batch", _fake_batch)
    monkeypatch.setattr(ks_mod.UserDao, "get_user_by_ids", lambda ids: [])

    rows = await KnowledgeService.aconvert_knowledge_read(
        login_user=MagicMock(),
        knowledge_list=[
            _knowledge(1),
            _knowledge(2, knowledge_type=KnowledgeTypeEnum.QA),
        ],
        action_map={1: {"visible"}, 2: {"visible"}},
    )

    assert rows[0].has_abnormal_files is True
    assert rows[1].has_abnormal_files is False


@pytest.mark.asyncio
async def test_get_knowledge_qa_abnormal_filter_returns_empty():
    page = await KnowledgeService.get_knowledge(
        request=MagicMock(),
        login_user=MagicMock(user_id=1),
        knowledge_type=KnowledgeTypeEnum.QA,
        has_abnormal=True,
        page_size=10,
    )

    assert isinstance(page, PageInfiniteCursorData)
    assert page.data == []
    assert page.has_more is False
    assert page.next_cursor is None
    assert page.page_size == 10
