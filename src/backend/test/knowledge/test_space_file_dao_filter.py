"""Tests for optional file_type filter on SpaceFileDao.async_list_children.

Follows the pattern established in test_knowledge_space_file_dao.py:
- Patch get_async_db_session with a fake session that captures the statement.
- Compile the captured statement with SQLite literal_binds to inspect the SQL string.
"""
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
async def test_async_list_children_file_type_zero_adds_filter():
    """file_type=0 should produce a WHERE clause containing file_type = 0."""
    session = _FakeAsyncSession()
    with patch(
        "bisheng.knowledge.domain.models.knowledge_space_file.get_async_db_session",
        return_value=session,
    ):
        await SpaceFileDao.async_list_children(
            knowledge_id=1,
            parent_id=None,
            page=1,
            page_size=10,
            file_type=0,
        )

    sql = _compile_sql(session.statement)
    assert "file_type" in sql
    # SQLite literal_binds renders the integer literal; accept either spacing
    assert "file_type = 0" in sql or "file_type=0" in sql.replace(" ", "")


@pytest.mark.asyncio
async def test_async_list_children_file_type_one_adds_filter():
    """file_type=1 should produce a WHERE clause containing file_type = 1."""
    session = _FakeAsyncSession()
    with patch(
        "bisheng.knowledge.domain.models.knowledge_space_file.get_async_db_session",
        return_value=session,
    ):
        await SpaceFileDao.async_list_children(
            knowledge_id=1,
            parent_id=None,
            page=1,
            page_size=10,
            file_type=1,
        )

    sql = _compile_sql(session.statement)
    assert "file_type" in sql
    assert "file_type = 1" in sql or "file_type=1" in sql.replace(" ", "")


@pytest.mark.asyncio
async def test_async_list_children_file_type_none_does_not_add_extra_filter():
    """file_type=None (default) should NOT add a file_type equality filter."""
    session = _FakeAsyncSession()
    with patch(
        "bisheng.knowledge.domain.models.knowledge_space_file.get_async_db_session",
        return_value=session,
    ):
        await SpaceFileDao.async_list_children(
            knowledge_id=1,
            parent_id=None,
            page=1,
            page_size=10,
            file_type=None,
        )

    # When no file_type is specified the SQL should not contain a standalone
    # equality filter on file_type (the field may appear in ORDER BY, which is fine).
    sql = _compile_sql(session.statement)
    # Presence of "file_type = 0" or "file_type = 1" would indicate a spurious filter.
    assert "file_type = 0" not in sql
    assert "file_type = 1" not in sql
