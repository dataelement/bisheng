"""Integration test: search_space_children excludes non-primary versions and returns version info.

Two test areas:
1. DAO level — KnowledgeFileDao.aget_file_by_filters with exclude_file_ids parameter.
2. Repository level — find_non_primary_file_ids provides the exclusion list.
"""
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from sqlalchemy.dialects import sqlite

# ---------------------------------------------------------------------------
# Fake session for SQL-inspection tests (no real DB)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# DAO SQL-level tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aget_file_by_filters_exclude_file_ids_adds_notin_clause():
    """exclude_file_ids must produce a NOT IN clause in the generated SQL."""
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao

    session = _FakeAsyncSession()

    @asynccontextmanager
    async def _session_ctx():
        yield session

    with patch(
        "bisheng.knowledge.domain.models.knowledge_file.get_async_db_session",
        new=_session_ctx,
    ):
        await KnowledgeFileDao.aget_file_by_filters(
            knowledge_id=1,
            exclude_file_ids=[100, 101],
        )

    sql = _compile_sql(session.statement)
    assert "100" in sql and "101" in sql, f"exclude ids not in SQL: {sql}"
    assert "NOT IN" in sql.upper(), f"NOT IN clause missing: {sql}"


@pytest.mark.asyncio
async def test_aget_file_by_filters_no_exclude_no_notin_clause():
    """When exclude_file_ids is None (default) no NOT IN clause should appear."""
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao

    session = _FakeAsyncSession()

    @asynccontextmanager
    async def _session_ctx():
        yield session

    with patch(
        "bisheng.knowledge.domain.models.knowledge_file.get_async_db_session",
        new=_session_ctx,
    ):
        await KnowledgeFileDao.aget_file_by_filters(knowledge_id=1)

    sql = _compile_sql(session.statement)
    assert "NOT IN" not in sql.upper(), f"Unexpected NOT IN clause in SQL: {sql}"


@pytest.mark.asyncio
async def test_aget_file_by_filters_empty_exclude_no_notin_clause():
    """When exclude_file_ids is an empty list no NOT IN clause should appear."""
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao

    session = _FakeAsyncSession()

    @asynccontextmanager
    async def _session_ctx():
        yield session

    with patch(
        "bisheng.knowledge.domain.models.knowledge_file.get_async_db_session",
        new=_session_ctx,
    ):
        await KnowledgeFileDao.aget_file_by_filters(
            knowledge_id=1,
            exclude_file_ids=[],  # empty list → no filter
        )

    sql = _compile_sql(session.statement)
    assert "NOT IN" not in sql.upper(), f"Unexpected NOT IN clause for empty list: {sql}"


@pytest.mark.asyncio
async def test_aget_file_by_filters_file_type_adds_file_type_clause():
    """file_type must filter before pagination so directories are excluded correctly."""
    from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileDao

    session = _FakeAsyncSession()

    @asynccontextmanager
    async def _session_ctx():
        yield session

    with patch(
        "bisheng.knowledge.domain.models.knowledge_file.get_async_db_session",
        new=_session_ctx,
    ):
        await KnowledgeFileDao.aget_file_by_filters(
            knowledge_id=1,
            file_type=FileType.FILE.value,
        )

    sql = _compile_sql(session.statement)
    assert "file_type = 1" in sql, f"file_type filter missing: {sql}"


@pytest.mark.asyncio
async def test_acount_file_by_filters_file_type_adds_file_type_clause():
    """The count query must use the same file_type filter as the list query."""
    from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileDao

    session = _FakeAsyncSession()

    @asynccontextmanager
    async def _session_ctx():
        yield session

    with patch(
        "bisheng.knowledge.domain.models.knowledge_file.get_async_db_session",
        new=_session_ctx,
    ):
        await KnowledgeFileDao.acount_file_by_filters(
            knowledge_id=1,
            file_type=FileType.FILE.value,
        )

    sql = _compile_sql(session.statement)
    assert "file_type = 1" in sql, f"file_type count filter missing: {sql}"


@pytest.mark.asyncio
async def test_aget_files_by_file_encoding_filters_code_space_and_file_type():
    """OpenAPI file detail lookup must locate files by code while excluding folders."""
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao

    session = _FakeAsyncSession()

    @asynccontextmanager
    async def _session_ctx():
        yield session

    with patch(
        "bisheng.knowledge.domain.models.knowledge_file.get_async_db_session",
        new=_session_ctx,
    ):
        await KnowledgeFileDao.aget_files_by_file_encoding(
            file_encoding="SGGF-RPT-QM-20260400000007",
            knowledge_id=7,
        )

    sql = _compile_sql(session.statement)
    assert "file_encoding = 'SGGF-RPT-QM-20260400000007'" in sql, f"file_encoding filter missing: {sql}"
    assert "knowledge_id = 7" in sql, f"knowledge_id filter missing: {sql}"
    assert "file_type = 1" in sql, f"file_type filter missing: {sql}"


# ---------------------------------------------------------------------------
# Repository-level integration test using real async_db_session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_repo_find_non_primary_returns_excluded_ids(async_db_session):
    """The data we'd pass into exclude_file_ids comes from the version repo."""
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
        KnowledgeDocumentVersionRepositoryImpl,
    )

    doc = KnowledgeDocument(knowledge_id=1)
    async_db_session.add(doc)
    await async_db_session.commit()
    await async_db_session.refresh(doc)

    v1 = KnowledgeDocumentVersion(document_id=doc.id, knowledge_file_id=100, version_no=1, is_primary=False)
    v2 = KnowledgeDocumentVersion(document_id=doc.id, knowledge_file_id=101, version_no=2, is_primary=True)
    async_db_session.add_all([v1, v2])
    await async_db_session.commit()

    repo = KnowledgeDocumentVersionRepositoryImpl(async_db_session)
    excluded = await repo.find_non_primary_file_ids()
    assert set(excluded) == {100}
