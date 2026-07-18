from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import sqlite

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService


def _compile_sql(statement) -> str:
    return str(
        statement.compile(
            dialect=sqlite.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


class _SyncResult:
    def __init__(self, statement):
        self.statement = statement

    def all(self):
        return []


class _AsyncResult:
    def __init__(self, statement):
        self.statement = statement

    def first(self):
        return None


class _SyncSession:
    def __init__(self):
        self.statement = None

    def exec(self, statement):
        self.statement = statement
        return _SyncResult(statement)


class _AsyncSession:
    def __init__(self):
        self.statement = None

    async def exec(self, statement):
        self.statement = statement
        return _AsyncResult(statement)


class _SyncSessionCtx:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, exc, tb):
        return False


class _AsyncSessionCtx:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_get_file_by_condition_matches_name_or_md5_regardless_of_status(monkeypatch):
    session = _SyncSession()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.get_sync_db_session",
        lambda: _SyncSessionCtx(session),
    )

    KnowledgeFileDao.get_file_by_condition(knowledge_id=1, file_name="failed.docx", md5_="abc123")

    sql = _compile_sql(session.statement)
    assert "knowledgefile.knowledge_id = 1" in sql
    assert "knowledgefile.md5 = 'abc123' OR knowledgefile.file_name = 'failed.docx'" in sql
    assert "knowledgefile.status" not in sql.split("WHERE", 1)[1]


def test_get_file_by_condition_returns_all_target_files_for_copy(monkeypatch):
    session = _SyncSession()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.get_sync_db_session",
        lambda: _SyncSessionCtx(session),
    )

    KnowledgeFileDao.get_file_by_condition(knowledge_id=1)

    sql = _compile_sql(session.statement)
    assert "knowledgefile.knowledge_id = 1" in sql
    assert "knowledgefile.status" not in sql.split("WHERE", 1)[1]


def test_process_one_file_uses_one_query_and_preserves_md5_precedence(monkeypatch, tmp_path):
    uploaded_file = tmp_path / "abc123.pdf"
    uploaded_file.write_bytes(b"duplicate content")

    name_duplicate = SimpleNamespace(id=10, md5="other-md5", file_name="report.pdf")
    content_duplicate = SimpleNamespace(id=11, md5="abc123", file_name="other.pdf")
    get_duplicates = MagicMock(return_value=[name_duplicate, content_duplicate])
    minio_client = MagicMock()

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_service.file_download",
        lambda _file_path: (str(uploaded_file), "stored.pdf"),
    )
    monkeypatch.setattr(KnowledgeService, "get_upload_file_original_name", MagicMock(return_value="report.pdf"))
    monkeypatch.setattr(KnowledgeFileDao, "get_file_by_condition", get_duplicates)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_service.get_minio_storage_sync",
        lambda: minio_client,
    )
    monkeypatch.setattr(KnowledgeService, "remove_unused_file", MagicMock())

    result = KnowledgeService.process_one_file(
        login_user=SimpleNamespace(user_id=1, user_name="tester"),
        knowledge=SimpleNamespace(id=1, tenant_id=1),
        file_info=SimpleNamespace(file_path="unused", excel_rule=None),
        split_rule={},
    )

    get_duplicates.assert_called_once_with(
        knowledge_id=1,
        md5_="abc123",
        file_name="report.pdf",
    )
    assert result is content_duplicate
    minio_client.put_object_tmp_sync.assert_called_once()


@pytest.mark.asyncio
async def test_get_repeat_file_matches_name_or_md5_regardless_of_status(monkeypatch):
    session = _AsyncSession()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.get_async_db_session",
        lambda: _AsyncSessionCtx(session),
    )

    await KnowledgeFileDao.get_repeat_file(knowledge_id=1, file_name="failed.docx", md5_="abc123")

    sql = _compile_sql(session.statement)
    assert "knowledgefile.knowledge_id = 1" in sql
    assert "knowledgefile.md5 = 'abc123' OR knowledgefile.file_name = 'failed.docx'" in sql
    assert "knowledgefile.status" not in sql.split("WHERE", 1)[1]
