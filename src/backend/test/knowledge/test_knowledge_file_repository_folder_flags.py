"""Batch folder descendant status query."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy.dialects import mysql, sqlite

from bisheng.core.database import tenant_filter
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)


def _compile_sql(statement) -> str:
    return str(
        statement.compile(
            dialect=sqlite.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()


async def test_folder_flags_are_returned_by_one_prefix_group_query(monkeypatch):
    result = SimpleNamespace(all=lambda: [(10, 1, 0), (11, 0, 1)])
    session = SimpleNamespace(execute=AsyncMock(return_value=result))
    repository = KnowledgeFileRepositoryImpl(session)

    states = await repository.find_folder_descendant_status_flags(7, {10: "/10", 11: "/11"})

    assert states[10].has_abnormal_files is True
    assert states[10].has_processing_files is False
    assert states[11].has_abnormal_files is False
    assert states[11].has_processing_files is True
    session.execute.assert_awaited_once()
    statement = session.execute.await_args.args[0]
    sql = _compile_sql(statement)
    assert " join " not in sql
    assert "knowledgefile as" not in sql
    assert "group by" in sql
    assert "knowledgefile.knowledge_id = 7" in sql
    assert "knowledgefile.file_level_path = '/10'" in sql
    assert "knowledgefile.file_level_path like '/10/%'" in sql
    assert "in (3, 6, 7)" in sql
    assert "in (1, 4, 5)" in sql

    mysql_sql = str(
        statement.compile(
            dialect=mysql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()
    assert "case when" in mysql_sql
    assert "group by" in mysql_sql

    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", {"knowledgefile"})
    assert tenant_filter._get_tenant_tables_from_statement(statement) == [KnowledgeFile.__table__]


async def test_empty_folder_ids_skip_the_database():
    session = SimpleNamespace(execute=AsyncMock())
    repository = KnowledgeFileRepositoryImpl(session)

    assert await repository.find_folder_descendant_status_flags(7, {}) == {}
    session.execute.assert_not_awaited()
