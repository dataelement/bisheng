from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy.dialects import sqlite

from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFileDao,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileProjectionStatus,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.models.knowledge_space_file import SpaceFileDao
from bisheng.knowledge.domain.services.knowledge_space_service import (
    KnowledgeSpaceService,
)
from bisheng.role.domain.services.quota_service import (
    _RESOURCE_COUNT_TEMPLATES,
)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def one(self):
        return self._rows[0]


class _Session:
    def __init__(self, rows):
        self.rows = rows
        self.statement = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def exec(self, statement):
        self.statement = statement
        return _Result(self.rows)

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
async def test_domain_statistics_dedupe_entries_by_canonical_document():
    session = _Session(
        [
            (10, 100, 1, "SGGF-RPT-QM-20260700000001"),
            (20, 100, 2, "SGGF-RPT-QM-20260700000001"),
            (30, None, 2, "SGGF-RPT-QM-20260700000002"),
        ]
    )
    with patch(
        "bisheng.knowledge.domain.models.knowledge_file.get_async_db_session",
        return_value=session,
    ):
        counts = await KnowledgeFileDao.async_count_files_by_domain_scopes({"QM": {1, 2}})

    assert counts == {"QM": 2}
    sql = _compile_sql(session.statement)
    assert "entry_status = 'active'" in sql
    assert "knowledge_document_version.is_primary IS 0" in sql


@pytest.mark.asyncio
async def test_folder_entry_count_uses_active_inventory_predicate():
    session = _Session([])
    with patch(
        "bisheng.knowledge.domain.models.knowledge_space_file.get_async_db_session",
        return_value=session,
    ):
        await SpaceFileDao.async_count_children(
            knowledge_id=1,
            parent_id=None,
        )

    sql = _compile_sql(session.statement)
    assert "entry_status = 'active'" in sql
    assert "entry_type IN ('manager', 'publish', 'share')" in sql
    assert "knowledge_document_version.is_primary IS 0" in sql
    assert "knowledgefile.deleted_at IS NULL" in sql


@pytest.mark.asyncio
async def test_active_inventory_predicate_excludes_soft_deleted():
    from sqlalchemy.dialects import sqlite
    from sqlmodel import select

    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileDao

    stmt = select(KnowledgeFile.id).where(KnowledgeFileDao.active_inventory_predicate())
    sql = str(
        stmt.compile(
            dialect=sqlite.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "knowledgefile.deleted_at IS NULL" in sql


def test_capacity_queries_exclude_logic_entries():
    for key in ("knowledge_space_file", "storage_gb"):
        sql = _RESOURCE_COUNT_TEMPLATES[key]
        assert "entry_type" in sql
        assert "'publish','share','projection_tombstone'" in sql


def test_qa_scope_requires_distribution_projection_ready():
    base = {
        "knowledge_id": 1,
        "file_type": FileType.FILE.value,
        "status": KnowledgeFileStatus.SUCCESS.value,
        "reference_document_id": 100,
        "entry_status": KnowledgeFileEntryStatus.ACTIVE.value,
        "entry_type": KnowledgeFileEntryType.SHARE.value,
        "desired_content_generation": 2,
        "applied_content_generation": 2,
        "desired_entry_generation": 1,
        "applied_entry_generation": 1,
    }
    pending = SimpleNamespace(
        **base,
        projection_status=KnowledgeFileProjectionStatus.PENDING.value,
    )
    ready = SimpleNamespace(
        **base,
        projection_status=KnowledgeFileProjectionStatus.READY.value,
    )

    assert KnowledgeSpaceService._is_qa_scope_file(pending, 1) is False
    assert KnowledgeSpaceService._is_qa_scope_file(ready, 1) is True
