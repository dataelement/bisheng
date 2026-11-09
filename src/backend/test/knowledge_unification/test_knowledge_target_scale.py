"""Native knowledge tombstone batches; SQLite does not prove MySQL lock scheduling."""

import math
from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import ResourceReferenceConflictError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories import reference_target_repository as module
from bisheng.resource_reference.application.contracts import SourceKey, TargetKey, TransactionIdentity
from bisheng.resource_reference.domain.models.resource_reference_tombstone import (
    ResourceReferenceTombstone as Tombstone,
)
from test.knowledge_unification import test_knowledge_reference_owner as original

owner_tenant = original.owner_tenant
engine = original.engine
SOURCE = SourceKey(101, "assistant", "scale", "current")


def tombstone(kind, ident, owner=101):
    return {
        "tenant_id": owner,
        "target_type": kind,
        "target_id": str(ident),
        "target_tenant_id": owner,
        "operation_id": f"delete-{kind}-{ident}-{owner}",
        "operation_type": "force_delete",
        "stage": "deleting",
        "actor_type": "user",
        "actor_id": "11",
    }


def rows(count):
    ids = tuple(range(1000, 1000 + count))
    return ids, (
        (Knowledge, [{"id": i, "tenant_id": 101, "user_id": 11, "name": f"space-{i}", "type": 3} for i in (1, 2)]),
        (
            KnowledgeFile,
            [{"id": i, "tenant_id": 101, "user_id": 11, "knowledge_id": 1, "file_name": f"file-{i}"} for i in ids],
        ),
        (Tombstone, [tombstone("knowledge_file", i) for i in ids] + [tombstone("knowledge_space", 1)]),
    )


@asynccontextmanager
async def native(count=1):
    database = create_async_engine("sqlite+aiosqlite://")
    ids, data = rows(count)
    try:
        async with database.begin() as connection:
            await connection.run_sync(lambda conn: SQLModel.metadata.create_all(conn, tables=original.TABLES))
            for model, values in data:
                await connection.execute(sa.insert(model.__table__), values)
        async with AsyncSession(database) as session, session.begin():
            yield session, ids
    finally:
        await database.dispose()


class Reads:
    def __init__(self, session):
        self.session = session.sync_session if isinstance(session, AsyncSession) else session
        self.bind, self.tombstones, self.dml, self.business_locks = self.session.get_bind(), [], [], []

    def cursor(self, _conn, _cursor, sql, params, _context, _many):
        keyword = sql.lstrip().split(None, 1)[0].upper()
        if keyword in {"INSERT", "UPDATE", "DELETE"}:
            self.dml.append(keyword)
        if keyword == "SELECT" and "FROM resource_reference_tombstone" in sql:
            self.tombstones.append((sql, params))

    def orm(self, state):
        if state.is_select and state.statement._for_update_arg is not None:
            entities = {item.get("entity") for item in state.statement.column_descriptions}
            if Knowledge in entities or KnowledgeFile in entities:
                self.business_locks.append(Knowledge if Knowledge in entities else KnowledgeFile)

    def __enter__(self):
        self.transaction = TransactionIdentity.capture(self.session)
        sa.event.listen(self.bind, "before_cursor_execute", self.cursor)
        sa.event.listen(self.session, "do_orm_execute", self.orm)
        return self

    def __exit__(self, *_):
        sa.event.remove(self.bind, "before_cursor_execute", self.cursor)
        sa.event.remove(self.session, "do_orm_execute", self.orm)
        self.transaction.assert_current(self.session)
        assert not self.dml


def assert_observations(actual, ids):
    assert tuple(int(row.key.target_id) for row in actual) == ids
    assert all(row.exists and row.target_tenant_id == 101 and row.target_space_id == "1" for row in actual)
    assert all(row.deletion.operation_id == f"delete-knowledge_file-{row.key.target_id}-101" for row in actual)
    assert all(row.ancestor_deletion.operation_id == "delete-knowledge_space-1-101" for row in actual)


@pytest.mark.parametrize("path,count", [("owner", 401), ("owner", 10001), ("prelock", 401)])
def test_native_sync_tombstone_query_budget(engine, path, count):
    ids, data = rows(count)
    with Session(engine) as session, session.begin():
        for model, values in data:
            session.execute(sa.insert(model.__table__), values)
    with Session(engine) as session, session.begin():
        repository = module.KnowledgeReferenceTargetRepository()
        keys = tuple(TargetKey("knowledge_file", i) for i in reversed(ids))
        with Reads(session) as reads:
            if path == "prelock":
                repository.prelock_targets(session, keys, (SOURCE,))
                proof = session.info[repository._prelock_key]
                assert len(proof[2]) == count and len(proof[5]) == count + 1
            else:
                assert_observations(repository.lock_targets(session, keys, None, "owner_query"), ids)
        assert len(reads.tombstones) == math.ceil((count + 1) / 200)
        assert max(len(params) for _, params in reads.tombstones) <= 800
        assert reads.business_locks == [Knowledge] + [KnowledgeFile] * math.ceil(count / 200)
        assert not session.new and not session.dirty and not session.deleted


@pytest.mark.parametrize("path,count", [("owner", 401), ("owner", 10001), ("prelock", 401)])
async def test_native_async_tombstone_query_budget(path, count):
    async with native(count) as (session, ids):
        repository = module.KnowledgeReferenceTargetRepository()
        keys = tuple(TargetKey("knowledge_file", i) for i in reversed(ids))
        with Reads(session) as reads:
            if path == "prelock":
                await repository.aprelock_targets(session, keys, (SOURCE,))
                proof = session.info[repository._prelock_key]
                assert len(proof[2]) == count and len(proof[5]) == count + 1
            else:
                assert_observations(await repository.alock_targets(session, keys, None, "owner_query"), ids)
        assert len(reads.tombstones) == math.ceil((count + 1) / 200)
        assert max(len(params) for _, params in reads.tombstones) <= 800
        assert reads.business_locks == [Knowledge] + [KnowledgeFile] * math.ceil(count / 200)
        assert not session.new and not session.dirty and not session.deleted


async def test_exact_type_id_owner_predicates_never_cross_pair_native_decoys():
    async with native() as (session, _):
        await session.execute(sa.delete(Tombstone.__table__))
        triples = (("knowledge_file", 1, 101), ("knowledge_space", 2, 202))
        decoys = (("knowledge_file", 1, 202), ("knowledge_space", 2, 101), ("knowledge_file", 2, 101))
        await session.execute(sa.insert(Tombstone.__table__), [tombstone(*row) for row in triples + decoys])
        wanted = {(TargetKey(kind, ident), owner) for kind, ident, owner in triples}
        statements = tuple(module.KnowledgeReferenceTargetRepository._tombstone_statements(wanted))
        assert len(statements) == 1 and statements[0]._for_update_arg is not None
        with bypass_tenant_filter(), Reads(session):
            result = tuple((await session.execute(statements[0])).scalars())
        assert {(row.target_type, row.target_id, row.target_tenant_id, row.tenant_id) for row in result} == {
            (kind, str(ident), owner, owner) for kind, ident, owner in triples
        }


async def test_complete_tombstone_set_uses_global_string_index_order_before_batching():
    async with native() as (session, _):
        ids = (*range(1000, 1201), 2)
        wanted = {(TargetKey("knowledge_file", ident), 101) for ident in ids}
        statements = tuple(module.KnowledgeReferenceTargetRepository._tombstone_statements(wanted))
        assert len(statements) == 2
        ordered = []
        for statement in statements:
            assert statement._for_update_arg is not None
            assert tuple(str(c) for c in statement._order_by_clauses) == (
                "resource_reference_tombstone.target_type",
                "resource_reference_tombstone.target_id",
                "resource_reference_tombstone.target_tenant_id",
            )
            for value in statement.compile().params.values():
                if isinstance(value, list):
                    assert len(value) <= 200
                    ordered.extend(value)
        assert ordered == sorted(str(ident) for ident in ids)
        assert not session.new and not session.dirty


@pytest.mark.parametrize("owner", [None, 0, -1, True, "101"])
def test_producer_rejects_unproven_owner_before_any_statement(owner):
    with pytest.raises(ResourceReferenceInvalidError):
        tuple(
            module.KnowledgeReferenceTargetRepository._tombstone_statements(((TargetKey("knowledge_file", 1), owner),))
        )


def test_producer_rejects_model_targets_and_empty_set_has_no_sql():
    assert tuple(module.KnowledgeReferenceTargetRepository._tombstone_statements(())) == ()
    with pytest.raises(ResourceReferenceInvalidError):
        tuple(module.KnowledgeReferenceTargetRepository._tombstone_statements(((TargetKey("model", 1), 101),)))


async def test_missing_bind_does_not_guess_owner_but_owner_query_keeps_original_scope():
    async with native() as (session, _):
        await session.execute(sa.insert(Tombstone.__table__), tombstone("knowledge_file", 999999))
        repository = module.KnowledgeReferenceTargetRepository()
        key = TargetKey("knowledge_file", 999999)
        with Reads(session) as bind:
            actual = await repository.alock_targets(session, (key,), SOURCE, "bind")
        assert not actual[0].exists and actual[0].target_tenant_id is None and actual[0].deletion is None
        assert not bind.tombstones
        with Reads(session) as query:
            actual = await repository.alock_targets(session, (key,), None, "owner_query")
        assert not actual[0].exists and actual[0].target_tenant_id == 101
        assert actual[0].deletion.operation_id == "delete-knowledge_file-999999-101"
        assert len(query.tombstones) == 1


async def test_populate_existing_preserves_complete_revision_and_deletion_refresh():
    async with native() as (session, ids):
        repository, key = module.KnowledgeReferenceTargetRepository(), TargetKey("knowledge_file", ids[0])
        first = (await repository.alock_targets(session, (key,), None, "owner_query"))[0]
        cached = (
            await session.execute(sa.select(Tombstone).where(Tombstone.target_type == "knowledge_file"))
        ).scalar_one()
        connection = await session.connection()
        await connection.execute(
            sa.update(Tombstone.__table__).where(Tombstone.id == cached.id).values(operation_id="changed-operation")
        )
        assert cached.operation_id != "changed-operation"
        with Reads(session):
            second = (await repository.alock_targets(session, (key,), None, "owner_query"))[0]
        assert second.deletion.operation_id == cached.operation_id == "changed-operation"
        assert first.target_revision != second.target_revision
        file = await session.get(KnowledgeFile, ids[0])
        parent = await session.get(Knowledge, 1)
        ancestor = (
            await session.execute(sa.select(Tombstone).where(Tombstone.target_type == "knowledge_space"))
        ).scalar_one()
        assert second.target_revision == module.revision(file, parent, cached, ancestor)


async def test_prelock_late_parent_still_rejects_before_any_late_business_or_tombstone_lock():
    async with native(401) as (session, ids):
        repository = module.KnowledgeReferenceTargetRepository()
        keys = tuple(TargetKey("knowledge_file", ident) for ident in ids)
        await repository.aprelock_targets(session, keys, (SOURCE,))
        await session.execute(
            sa.update(KnowledgeFile.__table__).where(KnowledgeFile.id == ids[-1]).values(knowledge_id=2)
        )
        with Reads(session) as reads, pytest.raises(ResourceReferenceConflictError):
            await repository.alock_targets(session, keys, SOURCE, "bind")
        assert not reads.business_locks and not reads.tombstones
        await session.rollback()


@pytest.mark.parametrize("kind", ["extra", "duplicate"])
async def test_native_unexpected_or_duplicate_result_is_rejected(kind):
    async with native() as (session, ids):
        if kind == "extra":
            await session.execute(sa.insert(Tombstone.__table__), tombstone("knowledge_file", 999999))

        def corrupt_result(state):
            if state.is_select and "FROM resource_reference_tombstone" in str(state.statement):
                # Native SQL fault injection, not a fake Repo/result: deliberately
                # widen the lookup or duplicate its ORM rows using the real table.
                statement = sa.select(Tombstone)
                if kind == "duplicate":
                    alias = Tombstone.__table__.alias("duplicate_transport")
                    statement = statement.join(alias, alias.c.tenant_id == Tombstone.tenant_id)
                state.statement = statement.with_for_update()

        sa.event.listen(session.sync_session, "do_orm_execute", corrupt_result)
        try:
            with pytest.raises(ResourceReferenceInvalidError):
                await module.KnowledgeReferenceTargetRepository().alock_targets(
                    session, (TargetKey("knowledge_file", ids[0]),), None, "owner_query"
                )
        finally:
            sa.event.remove(session.sync_session, "do_orm_execute", corrupt_result)
