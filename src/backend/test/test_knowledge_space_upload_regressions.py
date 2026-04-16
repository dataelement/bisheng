import pytest
from sqlalchemy.dialects import sqlite

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao


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


def test_get_file_by_condition_excludes_failed_and_timeout_duplicates(monkeypatch):
    session = _SyncSession()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.get_sync_db_session",
        lambda: _SyncSessionCtx(session),
    )

    KnowledgeFileDao.get_file_by_condition(knowledge_id=1, file_name="failed.docx", md5_="abc123")

    sql = _compile_sql(session.statement)
    assert "knowledgefile.knowledge_id = 1" in sql
    assert "knowledgefile.file_name = 'failed.docx'" in sql
    assert "knowledgefile.md5 = 'abc123'" in sql
    assert "knowledgefile.status NOT IN (3, 6)" in sql


@pytest.mark.asyncio
async def test_get_repeat_file_excludes_failed_and_timeout_duplicates(monkeypatch):
    session = _AsyncSession()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.get_async_db_session",
        lambda: _AsyncSessionCtx(session),
    )

    await KnowledgeFileDao.get_repeat_file(knowledge_id=1, file_name="failed.docx", md5_="abc123")

    sql = _compile_sql(session.statement)
    assert "knowledgefile.knowledge_id = 1" in sql
    assert "knowledgefile.status NOT IN (3, 6)" in sql
    assert "knowledgefile.md5 = 'abc123'" in sql
    assert "knowledgefile.file_name = 'failed.docx'" in sql
