"""Native same-transaction historical relinking; no old self-committing repos."""

import importlib
from dataclasses import FrozenInstanceError, replace

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import bypass_tenant_filter, current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument as Document
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion as Version
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile as File
from test.knowledge_unification import test_migration_resource_repository as original

native = original.native
MODELS = (Knowledge, Document, Version, File)


def api():
    return importlib.import_module("bisheng.knowledge.domain.repositories.knowledge_version_mutation_repository")


def doc(ident, space, primary):
    return {"id": ident, "knowledge_id": space, "primary_version_id": primary, "file_level_path": "/7", "level": 1}


def version(ident, document, file, no=1, primary=True):
    return {"id": ident, "document_id": document, "knowledge_file_id": file, "version_no": no, "is_primary": primary}


@pytest.fixture
async def database(native):
    @sa.event.listens_for(native.engine.sync_engine, "begin")
    def explicit_begin(connection):
        connection.exec_driver_sql("BEGIN")

    await native.insert(
        Knowledge,
        [original.resource(9700, type=3), original.resource(9701, tenant=202, type=3), original.resource(9702, type=3)],
    )
    await native.insert(
        File,
        [
            original.file(
                ident,
                tenant=202 if ident == 901 else 101,
                knowledge_id=9701 if ident == 901 else 9702 if ident == 301 else 9700,
                md5=str(ident),
                similar_status=1,
            )
            for ident in (101, 201, 202, 301, 901)
        ],
    )
    await native.insert(Document, [doc(10, 9700, 1001), doc(20, 9700, 2002), doc(30, 9702, 3001), doc(90, 9701, 9001)])
    await native.insert(
        Version,
        [
            version(1001, 10, 101),
            version(2001, 20, 201, primary=False),
            version(2002, 20, 202, no=3),
            version(3001, 30, 301),
            version(9001, 90, 901),
        ],
    )
    return native


async def snapshot(database):
    async with AsyncSession(database.engine) as session:
        return {
            model.__tablename__: tuple(
                dict(row) for row in (await session.execute(sa.select(model.__table__).order_by(model.id))).mappings()
            )
            for model in MODELS
        }


async def state(repo, session):
    return await repo.alock_link_state(session, knowledge_file_id=101, target_document_id=20)


async def test_link_is_one_caller_transaction_and_preserves_all_other_file_columns(database):
    before = await snapshot(database)
    repo = api().KnowledgeVersionMutationRepository()
    async with AsyncSession(database.engine) as session, session.begin():
        locked = await state(repo, session)
        assert locked.incoming_file.id == 101 and locked.target_document.id == 20
        assert [row.version_no for row in locked.target_versions] == [1, 3]
        assert locked.space.id == 9700 and locked.space.model_transition is None
        with pytest.raises(FrozenInstanceError):
            locked.incoming_file.md5 = "forged"
        result = await repo.arelink(session, state=locked, new_version_no=4)
        assert (result.document_id, result.new_version_no, result.knowledge_id, result.file_name) == (
            20,
            4,
            9700,
            "private-name",
        )
        assert session.in_transaction() and not session.new and not session.dirty
        await session.rollback()
    assert await snapshot(database) == before
    async with AsyncSession(database.engine) as session, session.begin():
        await repo.arelink(session, state=await state(repo, session), new_version_no=4)
    after = await snapshot(database)
    assert not any(row["id"] == 10 for row in after["knowledge_document"])
    versions = [row for row in after["knowledge_document_version"] if row["document_id"] == 20]
    assert len(versions) == 3 and [
        (row["version_no"], row["knowledge_file_id"]) for row in versions if row["is_primary"]
    ] == [(4, 101)]
    primary = next(row for row in versions if row["is_primary"])
    assert next(row for row in after["knowledge_document"] if row["id"] == 20)["primary_version_id"] == primary["id"]
    for old, new in zip(before["knowledgefile"], after["knowledgefile"], strict=True):
        assert {key: val for key, val in old.items() if key != "similar_status"} == {
            key: val for key, val in new.items() if key != "similar_status"
        }
    assert next(row for row in after["knowledgefile"] if row["id"] == 101)["similar_status"] == 2


async def test_merge_and_primary_use_actual_full_chain_and_keep_history(database):
    repo = api().KnowledgeVersionMutationRepository()
    async with AsyncSession(database.engine) as session, session.begin():
        locked = await repo.alock_merge_state(session, current_file_id=201, source_document_id=10)
        assert locked.anchor_file.id == 201 and locked.incoming_file.id == 101
        await repo.arelink(session, state=locked, new_version_no=4)
    async with AsyncSession(database.engine) as session, session.begin():
        locked = await repo.alock_primary_state(session, version_id=2001)
        result = await repo.aset_primary(session, state=locked)
        assert (result.document_id, result.new_primary_version_no) == (20, 1)
    after = await snapshot(database)
    rows = [row for row in after["knowledge_document_version"] if row["document_id"] == 20]
    assert len(rows) == 3 and [row["id"] for row in rows if row["is_primary"]] == [2001]


async def test_original_link_allows_source_with_no_version_row(database):
    async with database.engine.begin() as connection:
        await connection.execute(sa.delete(Version).where(Version.id == 1001))
        await connection.execute(sa.delete(Document).where(Document.id == 10))
    repo = api().KnowledgeVersionMutationRepository()
    async with AsyncSession(database.engine) as session, session.begin():
        locked = await state(repo, session)
        assert locked.source_document is None and locked.source_versions == ()
        await repo.arelink(session, state=locked, new_version_no=4)
    after = await snapshot(database)
    assert len([row for row in after["knowledge_document_version"] if row["knowledge_file_id"] == 101]) == 1


@pytest.mark.parametrize("failure", range(1, 7))
async def test_every_relink_write_failure_rolls_back_all_three_tables(database, failure):
    before, seen = await snapshot(database), []

    def fault(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            seen.append(statement)
            if len(seen) == failure:
                raise RuntimeError("controlled native write failure")

    sa.event.listen(database.engine.sync_engine, "after_cursor_execute", fault)
    try:
        repo = api().KnowledgeVersionMutationRepository()
        with pytest.raises(RuntimeError, match="controlled native"):
            async with AsyncSession(database.engine) as session, session.begin():
                await repo.arelink(session, state=await state(repo, session), new_version_no=4)
    finally:
        sa.event.remove(database.engine.sync_engine, "after_cursor_execute", fault)
    assert len(seen) == failure and await snapshot(database) == before


@pytest.mark.parametrize("case", ["forged", "copy", "other_repo", "other_session", "other_tx", "consumed", "wrong_no"])
async def test_locked_facts_are_instance_and_native_transaction_bound(database, case):
    repo = api().KnowledgeVersionMutationRepository()
    async with AsyncSession(database.engine) as session:
        await session.begin()
        locked = await state(repo, session)
        if case == "other_tx":
            await session.rollback()
            await session.begin()
        if case == "consumed":
            await repo.arelink(session, state=locked, new_version_no=4)
        supplied = replace(locked) if case == "copy" else object() if case == "forged" else locked
        chosen = api().KnowledgeVersionMutationRepository() if case == "other_repo" else repo
        if case == "other_session":
            async with AsyncSession(database.engine) as other, other.begin():
                with pytest.raises(KnowledgeOperationPlanConflictError):
                    await chosen.arelink(other, state=supplied, new_version_no=4)
        else:
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await chosen.arelink(session, state=supplied, new_version_no=5 if case == "wrong_no" else 4)
        await session.rollback()


@pytest.mark.parametrize(
    "case",
    ["foreign_file", "missing_file", "duplicate_reference", "primary_pointer", "source_document_missing", "file_kind"],
)
async def test_invalid_actual_link_graph_is_rejected_without_writes(database, case):
    async with database.engine.begin() as connection:
        if case == "foreign_file":
            await connection.execute(sa.update(File).where(File.id == 201).values(tenant_id=202))
        elif case == "missing_file":
            await connection.execute(sa.delete(File).where(File.id == 201))
        elif case == "duplicate_reference":
            await connection.execute(sa.insert(Version), version(4001, 30, 201, no=2, primary=False))
        elif case == "primary_pointer":
            await connection.execute(sa.update(Document).where(Document.id == 20).values(primary_version_id=1001))
        elif case == "source_document_missing":
            await connection.execute(sa.delete(Document).where(Document.id == 10))
        else:
            await connection.execute(sa.update(File).where(File.id == 201).values(file_type=0))
    before = await snapshot(database)
    repo = api().KnowledgeVersionMutationRepository()
    with pytest.raises(KnowledgeOperationPlanConflictError):
        async with AsyncSession(database.engine) as session, session.begin():
            await repo.arelink(session, state=await state(repo, session), new_version_no=4)
    assert await snapshot(database) == before


@pytest.mark.parametrize("case", ["bypass", "missing_tenant", "no_tx", "not_native"])
async def test_scope_rejected_before_sql(database, case):
    repo = api().KnowledgeVersionMutationRepository()
    async with AsyncSession(database.engine) as session:
        if case != "no_tx":
            await session.begin()
        token = set_current_tenant_id(None) if case == "missing_tenant" else None
        database.queries.clear()
        try:
            with pytest.raises(KnowledgeOperationPlanConflictError):
                if case == "bypass":
                    with bypass_tenant_filter():
                        await state(repo, session)
                else:
                    await state(repo, object() if case == "not_native" else session)
            assert not database.queries
        finally:
            if token is not None:
                current_tenant_id.reset(token)


async def test_pending_current_rows_are_not_overwritten_and_unrelated_pending_does_not_flush(database):
    repo = api().KnowledgeVersionMutationRepository()
    async with AsyncSession(database.engine) as session, session.begin():
        dirty = await session.get(Document, 20)
        dirty.primary_version_id = 1001
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await state(repo, session)
        assert dirty.primary_version_id == 1001 and dirty in session.dirty
        await session.rollback()
    async with AsyncSession(database.engine) as session, session.begin():
        stale = await session.get(Document, 20)
        session.expire(stale, ["primary_version_id"])
        pending = File(**original.file(9999, knowledge_id=9702))
        session.add(pending)
        flushes = []
        sa.event.listen(session.sync_session, "before_flush", lambda *args: flushes.append(1))
        await repo.arelink(session, state=await state(repo, session), new_version_no=4)
        assert pending in session.new and not flushes
        assert "primary_version_id" in sa.inspect(stale).unloaded
        await session.rollback()


async def test_same_transaction_core_drift_cannot_reuse_stale_locked_facts(database):
    repo = api().KnowledgeVersionMutationRepository()
    async with AsyncSession(database.engine) as session, session.begin():
        locked = await state(repo, session)
        await session.execute(sa.update(File.__table__).where(File.id == 101).values(md5="changed"))
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.arelink(session, state=locked, new_version_no=4)


async def test_hint_cannot_authorize_deleting_a_source_that_changed_before_locking(database):
    await database.insert(File, [original.file(203, knowledge_id=9700, md5="other-file")])
    changed = []

    def drift(connection, _cursor, sql, _parameters, _context, _many):
        if not changed and sql.startswith("SELECT knowledge_document.id") and "JOIN knowledge" in sql:
            changed.append(True)
            connection.execute(sa.update(Version.__table__).where(Version.id == 1001).values(knowledge_file_id=203))

    sa.event.listen(database.engine.sync_engine, "after_cursor_execute", drift)
    try:
        repo = api().KnowledgeVersionMutationRepository()
        async with AsyncSession(database.engine) as session, session.begin():
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await repo.arelink(session, state=await state(repo, session), new_version_no=4)
            assert changed == [True]
            assert (await session.execute(sa.select(Document.id).where(Document.id == 10))).scalar_one() == 10
            await session.rollback()
    finally:
        sa.event.remove(database.engine.sync_engine, "after_cursor_execute", drift)


@pytest.mark.parametrize("count", [401, 1001])
async def test_whole_chain_uses_bounded_linear_scalar_batches(database, count):
    await database.insert(
        File, [original.file(10000 + i, knowledge_id=9700, md5=f"historical-{i}") for i in range(count)]
    )
    await database.insert(Version, [version(10000 + i, 20, 10000 + i, no=4 + i, primary=False) for i in range(count)])
    repo = api().KnowledgeVersionMutationRepository()
    async with AsyncSession(database.engine) as session, session.begin():
        database.queries.clear()
        locked = await state(repo, session)
        assert len(locked.target_versions) == count + 2
        await repo.arelink(session, state=locked, new_version_no=count + 4)
        assert len(database.queries) <= 80
        assert max(len(params) for _, params in database.queries) <= 205
        assert all(
            not any(field in sql.lower() for field in ("split_rule", "user_metadata", "abstract", "object_name"))
            for sql, _ in database.queries
        )
        assert all("knowledge.model_transition IS NOT NULL" not in sql for sql, _ in database.queries)
        print(
            {
                "chain": count + 2,
                "selects": len(database.queries),
                "max_parameters": max(len(params) for _, params in database.queries),
            }
        )
        await session.rollback()


@pytest.mark.parametrize("stored", ["sql_null", "json_null", "empty_object", "transition"])
async def test_native_nullable_json_transition_uses_typed_value_and_keeps_empty_object_busy(database, stored):
    from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError
    from bisheng.knowledge.domain.services.knowledge_processing_guard import require_space_processing_idle

    value = {
        "sql_null": sa.null(),
        "json_null": sa.literal("null", type_=sa.Text()),
        "empty_object": {},
        "transition": {"operation_id": "native-transition"},
    }[stored]
    async with database.engine.begin() as connection:
        await connection.execute(
            sa.update(Knowledge.__table__).where(Knowledge.id == 9700).values(model_transition=value)
        )
    before = await snapshot(database)
    busy = stored in {"empty_object", "transition"}
    repo = api().KnowledgeVersionMutationRepository()
    async with AsyncSession(database.engine) as session, session.begin():
        physical = (
            await session.execute(
                sa.select(sa.cast(Knowledge.__table__.c.model_transition, sa.Text())).where(Knowledge.id == 9700)
            )
        ).scalar_one()
        if stored == "sql_null":
            assert physical is None
        elif stored == "json_null":
            assert physical == "null"  # Persisted JSON null is distinct from SQL NULL.
        locked = await state(repo, session)
        assert locked.space.model_transition is (True if busy else None)
        if busy:
            with pytest.raises(KnowledgeProcessingConflictError):
                require_space_processing_idle(locked.space, operation="link_version")
        else:
            require_space_processing_idle(locked.space, operation="link_version")
        await session.rollback()
    assert await snapshot(database) == before
