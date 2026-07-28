"""Regression: soft-deleted KnowledgeFile rows must not affect active inventory."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import sqlite

from bisheng.common.errcode.knowledge_space import SpaceFileNotFoundError, SpaceFolderNotFoundError
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileDao
from bisheng.knowledge.domain.models.knowledge_space_file import SpaceFileDao
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.role.domain.services.quota_service import _RESOURCE_COUNT_TEMPLATES


class _ScalarResult:
    def __init__(self, value=0):
        self._value = value

    def all(self):
        return []

    def first(self):
        return None


class _AsyncSession:
    def __init__(self):
        self.statement = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def exec(self, statement):
        self.statement = statement
        return _ScalarResult()

    async def scalar(self, statement):
        self.statement = statement
        return 0

    async def execute(self, statement):
        self.statement = statement
        return SimpleNamespace(scalar_one=lambda: 0, scalars=lambda: SimpleNamespace(first=lambda: None))


class _SyncSession:
    def __init__(self):
        self.statement = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def exec(self, statement):
        self.statement = statement
        return _ScalarResult()

    def scalar(self, statement):
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
async def test_count_by_name_methods_exclude_soft_deleted(monkeypatch):
    session = _AsyncSession()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_space_file.get_async_db_session",
        lambda: session,
    )

    await SpaceFileDao.count_folder_by_name(1, "b", "")
    assert "knowledgefile.deleted_at IS NULL" in _compile_sql(session.statement)

    await SpaceFileDao.count_file_by_name(1, "a.pdf")
    assert "knowledgefile.deleted_at IS NULL" in _compile_sql(session.statement)

    await SpaceFileDao.count_file_by_name_in_path(1, "a.pdf", "/10")
    assert "knowledgefile.deleted_at IS NULL" in _compile_sql(session.statement)


def test_ensure_space_file_and_folder_reject_soft_deleted():
    soft_file = SimpleNamespace(
        id=1,
        knowledge_id=19,
        file_type=FileType.FILE.value,
        deleted_at=datetime(2026, 7, 28),
    )
    soft_folder = SimpleNamespace(
        id=2,
        knowledge_id=19,
        file_type=FileType.DIR.value,
        deleted_at=datetime(2026, 7, 28),
    )
    with pytest.raises(SpaceFileNotFoundError):
        KnowledgeSpaceService._ensure_space_file(soft_file, 19)
    with pytest.raises(SpaceFolderNotFoundError):
        KnowledgeSpaceService._ensure_space_folder(soft_folder, 19)


@pytest.mark.asyncio
async def test_cursor_and_encoding_and_upload_size_exclude_soft_deleted(monkeypatch):
    session = _AsyncSession()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.get_async_db_session",
        lambda: session,
    )

    await KnowledgeFileDao.aget_file_by_space_filters_cursor(knowledge_ids=[19], limit=20)
    assert "knowledgefile.deleted_at IS NULL" in _compile_sql(session.statement)

    await KnowledgeFileDao.acount_by_file_encoding("SG-RPT-001")
    assert "knowledgefile.deleted_at IS NULL" in _compile_sql(session.statement)

    await KnowledgeFileDao.aget_files_by_file_encoding("SG-RPT-001", knowledge_id=19)
    assert "knowledgefile.deleted_at IS NULL" in _compile_sql(session.statement)

    await KnowledgeFileDao.aget_user_upload_total_file_size(1)
    assert "knowledgefile.deleted_at IS NULL" in _compile_sql(session.statement)

    await KnowledgeFileDao.alist_user_uploaded_files(user_id=1)
    assert "knowledgefile.deleted_at IS NULL" in _compile_sql(session.statement)

    await KnowledgeFileDao.aget_folders_by_space(19)
    assert "knowledgefile.deleted_at IS NULL" in _compile_sql(session.statement)

    await KnowledgeFileDao.acount_file_by_filters(19)
    assert "knowledgefile.deleted_at IS NULL" in _compile_sql(session.statement)

    await KnowledgeFileDao.async_count_file_by_filters(19)
    assert "knowledgefile.deleted_at IS NULL" in _compile_sql(session.statement)


def test_sync_list_count_and_rebuild_exclude_soft_deleted(monkeypatch):
    session = _SyncSession()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.get_sync_db_session",
        lambda: session,
    )

    KnowledgeFileDao.get_file_by_filters(19)
    assert "knowledgefile.deleted_at IS NULL" in _compile_sql(session.statement)

    KnowledgeFileDao.count_file_by_filters(19)
    assert "knowledgefile.deleted_at IS NULL" in _compile_sql(session.statement)

    KnowledgeFileDao.get_user_upload_total_file_size(1)
    assert "knowledgefile.deleted_at IS NULL" in _compile_sql(session.statement)

    KnowledgeFileDao.get_files_by_multiple_status(19, [1, 2])
    assert "knowledgefile.deleted_at IS NULL" in _compile_sql(session.statement)


def test_quota_templates_exclude_soft_deleted():
    assert "deleted_at IS NULL" in _RESOURCE_COUNT_TEMPLATES["knowledge_space_file"]
    assert "deleted_at IS NULL" in _RESOURCE_COUNT_TEMPLATES["storage_gb"]


def test_distribution_canonical_name_sql_excludes_soft_deleted():
    import inspect

    from bisheng.knowledge.domain.services.knowledge_document_distribution_service import (
        KnowledgeDocumentDistributionService,
    )

    src = inspect.getsource(KnowledgeDocumentDistributionService._ensure_canonical_name_available)
    assert "deleted_at" in src


def test_md5_existence_checks_exclude_soft_deleted():
    import inspect

    from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
        KnowledgeFileRepositoryImpl,
    )

    src = inspect.getsource(KnowledgeFileRepositoryImpl.has_visible_content_in_space)
    assert src.count("deleted_at") >= 2
