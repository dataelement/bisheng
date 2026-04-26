from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy.dialects import sqlite

from bisheng.knowledge.domain.models.knowledge_space_file import SpaceFileDao


class _FakeListResult:
    def __init__(self, values=None):
        self._values = values or []

    def all(self):
        return self._values


class _FakeAsyncSession:
    def __init__(self):
        self.statement = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def exec(self, statement):
        self.statement = statement
        return _FakeListResult()

    async def scalar(self, statement):
        self.statement = statement
        return 0


def _compile_sql(statement) -> str:
    return str(
        statement.compile(
            dialect=sqlite.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


@pytest.mark.asyncio
async def test_async_list_children_treats_null_root_path_as_root_level():
    session = _FakeAsyncSession()

    with patch(
        "bisheng.knowledge.domain.models.knowledge_space_file.get_async_db_session",
        return_value=session,
    ):
        await SpaceFileDao.async_list_children(knowledge_id=123, parent_id=None)

    sql = _compile_sql(session.statement)
    assert "file_level_path = ''" in sql
    assert "file_level_path IS NULL" in sql


@pytest.mark.asyncio
async def test_async_count_children_treats_null_root_path_as_root_level():
    session = _FakeAsyncSession()

    with patch(
        "bisheng.knowledge.domain.models.knowledge_space_file.get_async_db_session",
        return_value=session,
    ):
        await SpaceFileDao.async_count_children(knowledge_id=123, parent_id=None)

    sql = _compile_sql(session.statement)
    assert "file_level_path = ''" in sql
    assert "file_level_path IS NULL" in sql


@pytest.mark.asyncio
async def test_async_list_children_allows_root_status_filter():
    session = _FakeAsyncSession()

    with patch(
        "bisheng.knowledge.domain.models.knowledge_space_file.get_async_db_session",
        return_value=session,
    ):
        await SpaceFileDao.async_list_children(
            knowledge_id=123,
            parent_id=None,
            file_status=[1, 2, 4, 5, 6],
        )

    sql = _compile_sql(session.statement)
    assert "file_level_path = ''" in sql
    assert "file_level_path IS NULL" in sql
    assert "concat('', '/', knowledgefile.id)" in sql


@pytest.mark.asyncio
async def test_async_count_children_allows_root_status_filter():
    session = _FakeAsyncSession()

    with patch(
        "bisheng.knowledge.domain.models.knowledge_space_file.get_async_db_session",
        return_value=session,
    ):
        await SpaceFileDao.async_count_children(
            knowledge_id=123,
            parent_id=None,
            file_status=[1, 2, 4, 5, 6],
        )

    sql = _compile_sql(session.statement)
    assert "file_level_path = ''" in sql
    assert "file_level_path IS NULL" in sql
    assert "concat('', '/', knowledgefile.id)" in sql


@pytest.mark.asyncio
async def test_async_list_children_status_filter_uses_nested_parent_path():
    session = _FakeAsyncSession()
    parent = SimpleNamespace(file_level_path="/10")

    with patch(
        "bisheng.knowledge.domain.models.knowledge_space_file.get_async_db_session",
        return_value=session,
    ), patch(
        "bisheng.knowledge.domain.models.knowledge_space_file.KnowledgeFileDao.query_by_id",
        return_value=parent,
    ):
        await SpaceFileDao.async_list_children(
            knowledge_id=123,
            parent_id=20,
            file_status=[1, 2, 4, 5, 6],
        )

    sql = _compile_sql(session.statement)
    assert "file_level_path = '/10/20'" in sql
    assert "concat('/10/20', '/', knowledgefile.id)" in sql


@pytest.mark.asyncio
async def test_async_count_children_status_filter_uses_nested_parent_path():
    session = _FakeAsyncSession()
    parent = SimpleNamespace(file_level_path="/10")

    with patch(
        "bisheng.knowledge.domain.models.knowledge_space_file.get_async_db_session",
        return_value=session,
    ), patch(
        "bisheng.knowledge.domain.models.knowledge_space_file.KnowledgeFileDao.query_by_id",
        return_value=parent,
    ):
        await SpaceFileDao.async_count_children(
            knowledge_id=123,
            parent_id=20,
            file_status=[1, 2, 4, 5, 6],
        )

    sql = _compile_sql(session.statement)
    assert "file_level_path = '/10/20'" in sql
    assert "concat('/10/20', '/', knowledgefile.id)" in sql
