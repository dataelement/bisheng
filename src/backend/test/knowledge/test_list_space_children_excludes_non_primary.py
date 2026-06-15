"""Integration tests: list_space_children excludes non-primary versions and returns version info.

Two test areas:
1. DAO level — SpaceFileDao.async_list_children with exclude_file_ids parameter.
2. Service level — KnowledgeSpaceService._enrich_with_version_info sets version fields.
"""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy.dialects import sqlite
from sqlmodel import select


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

    async def execute(self, statement):
        self.statement = statement
        return _FakeListResult()


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
async def test_async_list_children_exclude_file_ids_adds_notin_clause():
    """exclude_file_ids must produce a NOT IN clause in the generated SQL."""
    from bisheng.knowledge.domain.models.knowledge_space_file import SpaceFileDao

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
            exclude_file_ids=[100, 101],
        )

    sql = _compile_sql(session.statement)
    # SQLite compiles NOT IN differently; accept both "NOT IN" and "notin_"
    assert "100" in sql and "101" in sql, f"exclude ids not in SQL: {sql}"
    assert "NOT IN" in sql.upper(), f"NOT IN clause missing: {sql}"


@pytest.mark.asyncio
async def test_async_list_children_no_exclude_file_ids_no_notin_clause():
    """When exclude_file_ids is None (default) no NOT IN clause should appear."""
    from bisheng.knowledge.domain.models.knowledge_space_file import SpaceFileDao

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
        )

    sql = _compile_sql(session.statement)
    assert "NOT IN" not in sql.upper(), f"Unexpected NOT IN clause in SQL: {sql}"


@pytest.mark.asyncio
async def test_async_list_children_empty_exclude_file_ids_no_notin_clause():
    """When exclude_file_ids is an empty list no NOT IN clause should appear."""
    from bisheng.knowledge.domain.models.knowledge_space_file import SpaceFileDao

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
            exclude_file_ids=[],  # empty list → no filter
        )

    sql = _compile_sql(session.statement)
    assert "NOT IN" not in sql.upper(), f"Unexpected NOT IN clause for empty list: {sql}"


# ---------------------------------------------------------------------------
# Repository-level integration test using real async_db_session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_non_primary_file_ids_returns_correct_ids(async_db_session):
    """find_non_primary_file_ids returns only the non-primary file ids."""
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
        KnowledgeDocumentVersionRepositoryImpl,
    )

    # Create a document with two versions: V1=non-primary, V2=primary
    doc = KnowledgeDocument(knowledge_id=1)
    async_db_session.add(doc)
    await async_db_session.commit()
    await async_db_session.refresh(doc)

    vA1 = KnowledgeDocumentVersion(document_id=doc.id, knowledge_file_id=100, version_no=1, is_primary=False)
    vA2 = KnowledgeDocumentVersion(document_id=doc.id, knowledge_file_id=101, version_no=2, is_primary=True)
    async_db_session.add_all([vA1, vA2])
    await async_db_session.commit()

    repo = KnowledgeDocumentVersionRepositoryImpl(async_db_session)
    result = await repo.find_non_primary_file_ids()

    assert set(result) == {100}, f"Expected {{100}}, got {set(result)}"


@pytest.mark.asyncio
async def test_find_primary_versions_by_file_ids_returns_primary_only(async_db_session):
    """find_primary_versions_by_file_ids returns only is_primary=True rows."""
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
        KnowledgeDocumentVersionRepositoryImpl,
    )

    doc = KnowledgeDocument(knowledge_id=1)
    async_db_session.add(doc)
    await async_db_session.commit()
    await async_db_session.refresh(doc)

    vA1 = KnowledgeDocumentVersion(document_id=doc.id, knowledge_file_id=100, version_no=1, is_primary=False)
    vA2 = KnowledgeDocumentVersion(document_id=doc.id, knowledge_file_id=101, version_no=2, is_primary=True)
    async_db_session.add_all([vA1, vA2])
    await async_db_session.commit()

    repo = KnowledgeDocumentVersionRepositoryImpl(async_db_session)
    rows = await repo.find_primary_versions_by_file_ids([100, 101])

    assert len(rows) == 1, f"Expected 1 primary row, got {len(rows)}"
    assert rows[0].knowledge_file_id == 101
    assert rows[0].version_no == 2
    assert rows[0].is_primary is True


# ---------------------------------------------------------------------------
# Service enrichment helper test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enrich_with_version_info_sets_fields(async_db_session):
    """_enrich_with_version_info sets _version_no, _is_multi_version, _has_similar on file items.

    We avoid importing KnowledgeSpaceService at module level (its deep import chain
    is pre-mocked by conftest) by loading it via importlib at test runtime, following
    the same pattern used in test_add_file_creates_document_v1.py.
    """
    import importlib
    import sys

    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
        KnowledgeDocumentVersionRepositoryImpl,
    )

    # Insert supporting DB rows
    doc_multi = KnowledgeDocument(knowledge_id=1)  # will have 2 versions
    doc_single = KnowledgeDocument(knowledge_id=1)  # will have 1 version
    async_db_session.add_all([doc_multi, doc_single])
    await async_db_session.commit()
    await async_db_session.refresh(doc_multi)
    await async_db_session.refresh(doc_single)

    # doc_multi: V1=non-primary (file_id=100), V2=primary (file_id=101)
    vm1 = KnowledgeDocumentVersion(document_id=doc_multi.id, knowledge_file_id=100, version_no=1, is_primary=False)
    vm2 = KnowledgeDocumentVersion(document_id=doc_multi.id, knowledge_file_id=101, version_no=2, is_primary=True)
    # doc_single: V1=primary (file_id=200)
    vs1 = KnowledgeDocumentVersion(document_id=doc_single.id, knowledge_file_id=200, version_no=1, is_primary=True)
    async_db_session.add_all([vm1, vm2, vs1])
    await async_db_session.commit()

    repo = KnowledgeDocumentVersionRepositoryImpl(async_db_session)

    # Load KnowledgeSpaceService via importlib (its import chain requires stubs from test_knowledge_space_service.py
    # helpers; here we rely on the premock_import_chain already run by conftest.py).
    # We bypass __init__ using object.__new__ after loading the real class.
    from test.knowledge.test_knowledge_space_service import _load_service_class
    KnowledgeSpaceService = _load_service_class()
    svc = object.__new__(KnowledgeSpaceService)
    svc.version_repo = repo

    # Construct fake file objects (only id, file_type, similar_status are needed)
    kf_101 = SimpleNamespace(id=101, file_type=1, similar_status=0)  # multi-version primary
    kf_200 = SimpleNamespace(id=200, file_type=1, similar_status=1)  # single-version, has_similar

    # Patch get_async_db_session so the inner count query uses our in-memory session
    @asynccontextmanager
    async def _session_ctx():
        yield async_db_session

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
        new=_session_ctx,
    ):
        result = await svc._enrich_with_version_info([kf_101, kf_200])

    # kf_101: primary V2 of doc_multi (which has 2 versions total)
    assert getattr(kf_101, "_version_no", None) == 2
    assert getattr(kf_101, "_is_multi_version", False) is True
    assert getattr(kf_101, "_has_similar", None) is False

    # kf_200: primary V1 of doc_single (only 1 version)
    assert getattr(kf_200, "_version_no", None) == 1
    assert getattr(kf_200, "_is_multi_version", False) is False
    assert getattr(kf_200, "_has_similar", None) is True  # similar_status=1
