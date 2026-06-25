from unittest.mock import patch

import pytest
from sqlalchemy.dialects import sqlite

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao


class _FakeListResult:
    def __init__(self, values=None):
        self._values = values or []

    def all(self):
        return self._values


class _FakeAsyncSession:
    def __init__(self, rows=None):
        self.statement = None
        self._rows = rows or []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def exec(self, statement):
        self.statement = statement
        return _FakeListResult(self._rows)


def _compile_sql(statement) -> str:
    return str(
        statement.compile(
            dialect=sqlite.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


@pytest.mark.asyncio
async def test_count_root_files_batch_empty_returns_empty_dict():
    # No DB round-trip when the id list is empty.
    assert await KnowledgeFileDao.async_count_root_files_batch([]) == {}


@pytest.mark.asyncio
async def test_count_root_files_batch_filters_root_files_only_all_statuses():
    session = _FakeAsyncSession()

    with patch(
        "bisheng.knowledge.domain.models.knowledge_file.get_async_db_session",
        return_value=session,
    ):
        await KnowledgeFileDao.async_count_root_files_batch([1, 2, 3])

    sql = _compile_sql(session.statement)
    # Root directory: empty path OR NULL path (matches folder/list semantics).
    assert "file_level_path = ''" in sql
    assert "file_level_path IS NULL" in sql
    # Only files, never folders.
    assert "knowledgefile.file_type = 1" in sql
    # Batched per-space aggregation.
    assert "knowledgefile.knowledge_id IN (1, 2, 3)" in sql
    assert "GROUP BY knowledgefile.knowledge_id" in sql
    # Raw count across ALL statuses — no status predicate.
    assert "status" not in sql


@pytest.mark.asyncio
async def test_count_root_files_batch_maps_rows_to_counts():
    session = _FakeAsyncSession(rows=[(1, 5), (3, 0)])

    with patch(
        "bisheng.knowledge.domain.models.knowledge_file.get_async_db_session",
        return_value=session,
    ):
        result = await KnowledgeFileDao.async_count_root_files_batch([1, 2, 3])

    assert result == {1: 5, 3: 0}
