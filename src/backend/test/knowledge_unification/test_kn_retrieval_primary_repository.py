"""Native bounded retrieval joins, C3, and context lifetime verification."""

import math
from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.engine.default import DefaultDialect

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import bypass_tenant_filter, set_current_tenant_id
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.retrieval_file_repository import KnowledgeRetrievalFileRepository
from test.knowledge_unification.test_kn_rebuild_write_entries import (
    concrete_tenant as concrete_tenant,
)
from test.knowledge_unification.test_kn_rebuild_write_entries import (
    writes as writes,
)


@contextmanager
def observed(session):
    statements = []

    def statement(connection, cursor, sql, parameters, context, many):
        if sql.lstrip().upper().startswith("SELECT"):
            statements.append((sql, parameters))

    engine = session.bind.sync_engine
    sa.event.listen(engine, "before_cursor_execute", statement)
    try:
        yield statements
    finally:
        sa.event.remove(engine, "before_cursor_execute", statement)


async def test_foreign_root_and_file_owner_mismatch_never_qualify(writes):
    session = writes.session
    await session.execute(
        sa.insert(Knowledge.__table__).values(id=90, name="foreign", type=3, tenant_id=202, user_id=7)
    )
    await session.execute(
        sa.insert(KnowledgeFile.__table__),
        [
            {
                "id": 901,
                "knowledge_id": 90,
                "tenant_id": 101,
                "user_id": 7,
                "file_name": "foreign.txt",
                "file_type": 1,
                "status": 2,
            },
            {
                "id": 902,
                "knowledge_id": 19,
                "tenant_id": 202,
                "user_id": 7,
                "file_name": "wrong-owner.txt",
                "file_type": 1,
                "status": 2,
            },
        ],
    )
    await session.execute(
        sa.insert(KnowledgeDocument.__table__),
        [
            {"id": 950, "knowledge_id": 90, "primary_version_id": 970},
            {"id": 951, "knowledge_id": 19, "primary_version_id": 971},
        ],
    )
    await session.execute(
        sa.insert(KnowledgeDocumentVersion.__table__),
        [
            {"id": 970, "document_id": 950, "knowledge_file_id": 901, "version_no": 1, "is_primary": True},
            {"id": 971, "document_id": 951, "knowledge_file_id": 902, "version_no": 1, "is_primary": True},
        ],
    )
    await session.commit()
    repository = KnowledgeRetrievalFileRepository()
    assert await repository.alist_successful_files(session, space_id=90) == set()
    assert await repository.alist_successful_files(session, space_id=19, file_ids=[902]) == set()


@pytest.mark.parametrize("bad", [[True], [101, True], [False], ["101"], [0], [2**64]])
async def test_typed_candidate_ids_reject_before_sql(writes, bad):
    with observed(writes.session) as queries, pytest.raises(KnowledgeOperationPlanConflictError):
        await KnowledgeRetrievalFileRepository().alist_successful_files(writes.session, space_id=19, file_ids=bad)
    assert queries == []


async def test_empty_candidates_do_not_open_a_transaction(writes):
    assert not writes.session.in_transaction()
    assert (
        await KnowledgeRetrievalFileRepository().alist_successful_files(writes.session, space_id=19, file_ids=[])
        == set()
    )
    assert not writes.session.in_transaction()


@pytest.mark.parametrize("change", ["tenant", "transaction", "pending"])
async def test_native_read_rechecks_context_after_actual_query(writes, monkeypatch, change):
    session = writes.session
    execute = session.execute

    async def drift(statement, *args, **kwargs):
        result = await execute(statement, *args, **kwargs)
        if change == "tenant":
            set_current_tenant_id(202)
        elif change == "transaction":
            await session.rollback()
            await session.connection()
        else:
            session.add(Knowledge(id=99, name="pending", type=3, tenant_id=101, user_id=7))
        return result

    monkeypatch.setattr(session, "execute", drift)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await KnowledgeRetrievalFileRepository().alist_successful_files(session, space_id=19, file_ids=[101])


async def test_bypass_is_refused_without_query(writes):
    with (
        observed(writes.session) as queries,
        bypass_tenant_filter(),
        pytest.raises(KnowledgeOperationPlanConflictError),
    ):
        await KnowledgeRetrievalFileRepository().alist_successful_files(writes.session, space_id=19)
    assert queries == []


@pytest.mark.parametrize("count", [401, 10001])
async def test_actual_many_file_reads_use_bounded_seek_and_indexed_exists(writes, count, record_property):
    session = writes.session
    ids = list(range(10000, 10000 + count))
    for start in range(0, count, 200):
        batch = ids[start : start + 200]
        await session.execute(
            sa.insert(KnowledgeFile.__table__),
            [
                {
                    "id": ident,
                    "tenant_id": 101,
                    "knowledge_id": 19,
                    "user_id": 7,
                    "file_name": f"{ident}.txt",
                    "file_type": 1,
                    "status": 2,
                }
                for ident in batch
            ],
        )
        await session.execute(
            sa.insert(KnowledgeDocument.__table__),
            [{"id": ident + 20000, "knowledge_id": 19, "primary_version_id": ident + 40000} for ident in batch],
        )
        await session.execute(
            sa.insert(KnowledgeDocumentVersion.__table__),
            [
                {
                    "id": ident + 40000,
                    "document_id": ident + 20000,
                    "knowledge_file_id": ident,
                    "version_no": 1,
                    "is_primary": True,
                }
                for ident in batch
            ],
        )
    await session.commit()
    repository = KnowledgeRetrievalFileRepository()
    with observed(session) as all_queries:
        assert await repository.alist_successful_files(session, space_id=19) == set(ids) | {101, 102}
    with observed(session) as candidate_queries:
        assert await repository.alist_successful_files(session, space_id=19, file_ids=ids) == set(ids)
    assert len(all_queries) == math.ceil((count + 2) / 200)
    assert len(candidate_queries) == math.ceil(count / 200)
    assert max(len(parameters) for _, parameters in candidate_queries) <= 212
    sql = repository._query(19).compile(dialect=session.bind.dialect, compile_kwargs={"literal_binds": True})
    plan = (await session.execute(sa.text("EXPLAIN QUERY PLAN " + str(sql)))).all()
    steps = "\n".join(row[-1] for row in plan)
    assert "SEARCH other_file_version USING" in steps
    assert "SCAN other_file_version" not in steps
    assert "SCAN knowledge_document_version" not in steps
    record_property("count", count)
    record_property("all_selects", len(all_queries))
    record_property("candidate_selects", len(candidate_queries))
    record_property("max_bind", max(len(parameters) for _, parameters in candidate_queries))


@pytest.mark.parametrize("dialect", [DefaultDialect(), mysql.dialect()])
def test_query_compiles_without_dialect_specific_functions(dialect):
    sql = str(KnowledgeRetrievalFileRepository._query(19).compile(dialect=dialect)).upper()
    assert "EXISTS" in sql and "OTHER_FILE_VERSION" in sql
    assert "JSON_" not in sql and "CAST(" not in sql
