"""T881: real initial-upload chains, private receipts and caller transactions."""

import asyncio
import importlib
import re
from dataclasses import fields, replace

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
MODELS = (Knowledge, File, Document, Version)


def api():
    return importlib.import_module("bisheng.knowledge.domain.repositories.upload_registration_repository")


def candidate(name="report.txt", **changes):
    return api().NewUploadFile(
        **(
            {
                "file_name": name,
                "file_size": 4,
                "md5": "original-content-digest",
                "split_rule": ' {"chunk_size":800,"_effective_processing":{"private":"exact input"}} ',
                "file_source": "space_upload",
                "user_metadata": {"private": [None, False, 0, 1.5, {"text": "原值"}]},
                "user_id": 7,
                "user_name": "original creator",
                "updater_id": 7,
                "updater_name": "original updater",
            }
            | changes
        )
    )


@pytest.fixture
async def database(native):
    # A real parent BEGIN is necessary: SQLite legacy mode otherwise commits
    # when the first SAVEPOINT is released, unlike the production databases.
    @sa.event.listens_for(native.engine.sync_engine, "begin")
    def parent(connection):
        connection.exec_driver_sql("BEGIN")

    await native.insert(
        Knowledge,
        [original.resource(9700, type=3), original.resource(9701, type=3), original.resource(8000, tenant=202, type=3)],
    )
    await native.insert(
        File,
        [
            original.file(10, knowledge_id=9700, file_type=0, level=0, file_level_path=""),
            original.file(11, knowledge_id=9700, file_type=0, level=1, file_level_path="/10"),
            original.file(20, tenant=202, knowledge_id=8000, file_type=0),
            original.file(21, knowledge_id=9701, file_type=0),
            original.file(30, knowledge_id=9700, file_type=0, file_level_path="not-a-path"),
            original.file(31, knowledge_id=9700, file_type=0, level=1, file_level_path="/999"),
            original.file(32, knowledge_id=9700, file_type=0, level=1, file_level_path="/32"),
            original.file(90, knowledge_id=9700),
        ],
    )
    await native.insert(
        Document, [{"id": 90, "knowledge_id": 9700, "primary_version_id": 90, "file_level_path": "", "level": 0}]
    )
    await native.insert(
        Version, [{"id": 90, "document_id": 90, "knowledge_file_id": 90, "version_no": 1, "is_primary": True}]
    )
    return native


async def contents(session):
    return {
        model.__tablename__: tuple(
            dict(row) for row in (await session.execute(sa.select(model.__table__).order_by(model.id))).mappings()
        )
        for model in MODELS
    }


async def snapshot(database):
    async with AsyncSession(database.engine) as session, session.begin():
        return await contents(session)


async def register(repo, session, rows=None, *, space_id=9700, parent_id=None):
    return await repo.aregister_initial(
        session, space_id=space_id, parent_id=parent_id, files=(candidate(),) if rows is None else rows
    )


async def test_actual_autoincrement_file_doc_v1_same_path_and_raw_rules_are_preserved(database):
    module, before = api(), await snapshot(database)
    repo, supplied = module.UploadRegistrationRepository(), candidate()
    async with AsyncSession(database.engine) as session, session.begin():
        registered = (await register(repo, session, (supplied,), parent_id=11))[0]
        assert registered.file.id > 90 and registered.document_id > 90 and registered.version_id > 90
        assert (registered.file.knowledge_id, registered.file.file_type, registered.file.status) == (9700, 1, 5)
        assert (registered.file.file_level_path, registered.file.level) == ("/10/11", 2)
        assert registered.file.split_rule == supplied.split_rule
        assert registered.file.user_metadata == supplied.user_metadata
        supplied.user_metadata["private"].append("caller later mutation")
        actual = await contents(session)
        file = next(row for row in actual["knowledgefile"] if row["id"] == registered.file.id)
        doc = next(row for row in actual["knowledge_document"] if row["id"] == registered.document_id)
        version = next(row for row in actual["knowledge_document_version"] if row["id"] == registered.version_id)
        assert file["split_rule"] == supplied.split_rule and "caller later mutation" not in repr(file["user_metadata"])
        assert (doc["knowledge_id"], doc["file_level_path"], doc["level"], doc["primary_version_id"]) == (
            9700,
            "/10/11",
            2,
            version["id"],
        )
        assert (version["document_id"], version["knowledge_file_id"], version["version_no"], version["is_primary"]) == (
            doc["id"],
            file["id"],
            1,
            True,
        )
        assert doc["create_time"] and doc["update_time"] and version["create_time"] and version["update_time"]
        assert all("private" not in repr(value) for value in (registered, supplied))
        assert [field.name for field in fields(supplied)] == [
            "file_name",
            "file_size",
            "md5",
            "split_rule",
            "file_source",
            "user_metadata",
            "user_id",
            "user_name",
            "updater_id",
            "updater_name",
        ]
        assert not hasattr(supplied, "__dict__")
    after = await snapshot(database)
    for model in MODELS:
        key = model.__tablename__
        old_ids = {row["id"] for row in before[key]}
        assert tuple(row for row in after[key] if row["id"] in old_ids) == before[key]


async def test_caller_rollback_removes_real_chain_and_zero_byte_input_is_not_a_new_format_policy(database):
    before, repo = await snapshot(database), api().UploadRegistrationRepository()
    async with AsyncSession(database.engine) as session, session.begin():
        result = await register(repo, session, (candidate(file_size=0),))
        assert result[0].file.file_size == 0
        await session.rollback()
    assert await snapshot(database) == before


async def test_materialize_issues_a_current_receipt_and_cleanup_is_only_the_new_chain(database):
    before, repo = await snapshot(database), api().UploadRegistrationRepository()
    async with AsyncSession(database.engine) as session, session.begin():
        (first,) = await register(repo, session)
        source_time = first.file.update_time
        materialized = await repo.aset_materialized(
            session, registration=first, object_name=f"original/{first.file.id}.txt"
        )
        assert materialized.file.object_name == f"original/{first.file.id}.txt"
        assert (
            materialized.file.user_metadata == first.file.user_metadata and materialized.file.update_time == source_time
        )
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.arollback_created(session, registrations=(first,))
        await repo.arollback_created(session, registrations=(materialized,))
    assert await snapshot(database) == before


@pytest.mark.parametrize("point", ["document", "version", "primary"])
async def test_native_trigger_registration_failure_caught_then_outer_commit_has_no_partial_chain(database, point):
    repo, before = api().UploadRegistrationRepository(), await snapshot(database)
    table = "knowledge_document_version" if point == "version" else "knowledge_document"
    event = "UPDATE" if point == "primary" else "INSERT"
    async with database.engine.begin() as conn:
        await conn.exec_driver_sql(
            f"CREATE TRIGGER fail_register BEFORE {event} ON {table} BEGIN SELECT RAISE(ABORT, 'native registration failure'); END"
        )
    async with AsyncSession(database.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await register(repo, session)
        assert session.in_transaction()
    assert await snapshot(database) == before


async def test_materialize_native_trigger_tamper_rolls_back_only_materialization_and_can_cleanup(database):
    repo = api().UploadRegistrationRepository()
    async with database.engine.begin() as conn:
        await conn.exec_driver_sql(
            "CREATE TRIGGER poison_materialization AFTER UPDATE OF object_name ON knowledgefile BEGIN UPDATE knowledgefile SET file_size=999 WHERE id=NEW.id; END"
        )
    async with AsyncSession(database.engine) as session, session.begin():
        (receipt,) = await register(repo, session)
        before = await contents(session)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.aset_materialized(session, registration=receipt, object_name="original/owned.txt")
        assert await contents(session) == before
    assert await snapshot(database) == before


@pytest.mark.parametrize("parent", [20, 21, 30, 31, 32, 90, 999])
async def test_foreign_other_space_file_or_malformed_folder_never_creates_rows(database, parent):
    repo, before = api().UploadRegistrationRepository(), await snapshot(database)
    async with AsyncSession(database.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await register(repo, session, parent_id=parent)
    assert await snapshot(database) == before


@pytest.mark.parametrize("changes", [{"tenant_id": 202}, {"type": 0}, {"type": 1}, {"type": 2}])
async def test_scope_or_kind_cannot_register_into_another_resource(database, changes):
    repo = api().UploadRegistrationRepository()
    async with database.engine.begin() as conn:
        await conn.execute(sa.update(Knowledge).where(Knowledge.id == 9700).values(**changes))
    before = await snapshot(database)
    async with AsyncSession(database.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await register(repo, session)
    assert await snapshot(database) == before


async def test_empty_and_invalid_batches_and_missing_context_have_zero_sql_or_flush(database):
    repo, row = api().UploadRegistrationRepository(), candidate()
    async with AsyncSession(database.engine) as session, session.begin():
        database.queries.clear()
        assert await register(repo, session, ()) == ()
        await repo.arollback_created(session, registrations=())
        assert not database.queries and not session.new and not session.dirty
        for rows in ([row], (object(),), (row,) * 201):
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await register(repo, session, rows)
        for value in (0, -1, True, 1.0):
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await register(repo, session, space_id=value)
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await register(repo, session, parent_id=value)
        with bypass_tenant_filter(), pytest.raises(KnowledgeOperationPlanConflictError):
            await register(repo, session)
        token = set_current_tenant_id(None)
        try:
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await register(repo, session)
        finally:
            current_tenant_id.reset(token)
        assert not database.queries and not session.new and not session.dirty
    async with AsyncSession(database.engine) as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await register(repo, session)


async def test_pending_caller_state_is_neither_flushed_nor_discarded(database):
    repo, flushes = api().UploadRegistrationRepository(), []
    async with AsyncSession(database.engine, autoflush=True) as session, session.begin():
        old = await session.get(File, 10)
        old.file_name = "caller dirty name"
        pending = File(knowledge_id=9700, file_name="caller pending")
        session.add(pending)
        sa.event.listen(session.sync_session, "before_flush", lambda *args: flushes.append(True))
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await register(repo, session)
        assert pending in session.new and pending.tenant_id is None and pending.id is None
        assert old in session.dirty and old.file_name == "caller dirty name" and not flushes
        await session.rollback()


@pytest.mark.parametrize("forgery", ["copy", "bare_ids", "different_repo", "rollback", "commit"])
async def test_only_this_repository_original_session_transaction_receipt_can_cleanup(database, forgery):
    repo = api().UploadRegistrationRepository()
    async with AsyncSession(database.engine) as session:
        await session.begin()
        (receipt,) = await register(repo, session)
        if forgery == "copy":
            attempted = replace(receipt)
        elif forgery == "bare_ids":
            attempted = {
                "file_id": receipt.file.id,
                "document_id": receipt.document_id,
                "version_id": receipt.version_id,
            }
        else:
            attempted = receipt
        if forgery in {"rollback", "commit"}:
            await getattr(session, forgery)()
            await session.begin()
        active = api().UploadRegistrationRepository() if forgery == "different_repo" else repo
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await active.arollback_created(session, registrations=(attempted,))
        await session.rollback()


@pytest.mark.parametrize(
    "changes",
    [
        {"file_name": "drift"},
        {"status": 2},
        {"split_rule": "different"},
        {"user_metadata": {"different": True}},
        {"knowledge_id": 9701},
        {"tenant_id": 202},
    ],
)
async def test_materialize_and_cleanup_cannot_erase_current_file_facts_after_drift(database, changes):
    repo = api().UploadRegistrationRepository()
    async with AsyncSession(database.engine) as session, session.begin():
        (receipt,) = await register(repo, session)
        await session.execute(sa.update(File.__table__).where(File.id == receipt.file.id).values(**changes))
        before = await contents(session)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.aset_materialized(session, registration=receipt, object_name="original/new")
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.arollback_created(session, registrations=(receipt,))
        assert await contents(session) == before


async def test_receipt_cannot_delete_a_chain_that_has_become_history(database):
    repo = api().UploadRegistrationRepository()
    async with AsyncSession(database.engine) as session, session.begin():
        (receipt,) = await register(repo, session)
        extra = File(knowledge_id=9700, tenant_id=101, file_name="new parsed version", status=2)
        session.add(extra)
        await session.flush()
        historical = Version(document_id=receipt.document_id, knowledge_file_id=extra.id, version_no=2, is_primary=True)
        session.add(historical)
        await session.flush()
        await session.execute(
            sa.update(Version.__table__).where(Version.id == receipt.version_id).values(is_primary=False)
        )
        await session.execute(
            sa.update(Document.__table__)
            .where(Document.id == receipt.document_id)
            .values(primary_version_id=historical.id)
        )
        before = await contents(session)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.arollback_created(session, registrations=(receipt,))
        assert await contents(session) == before


async def test_native_cancellation_after_document_insert_cannot_leave_half_a_chain(database):
    repo, before = api().UploadRegistrationRepository(), await snapshot(database)
    inserted = []

    def document_seen(_conn, _cursor, sql, _params, _context, _many):
        if sql.lstrip().upper().startswith("INSERT INTO KNOWLEDGE_DOCUMENT "):
            inserted.append(True)

    class CancelAfterCompletedSQL(AsyncSession):
        async def flush(self, *args, **kwargs):
            await super().flush(*args, **kwargs)
            if inserted:
                # Cancel after the real native INSERT has returned. Raising from
                # a driver event instead means connection loss to SQLAlchemy.
                asyncio.current_task().cancel()
                await asyncio.sleep(0)

    sa.event.listen(database.engine.sync_engine, "after_cursor_execute", document_seen)
    try:
        async with CancelAfterCompletedSQL(database.engine) as session, session.begin():
            with pytest.raises(asyncio.CancelledError):
                await register(repo, session)
    finally:
        sa.event.remove(database.engine.sync_engine, "after_cursor_execute", document_seen)
    assert await snapshot(database) == before


async def test_200_real_initial_versions_have_bounded_reads_and_no_cartesian_links(database):
    repo = api().UploadRegistrationRepository()
    async with AsyncSession(database.engine) as session, session.begin():
        database.queries.clear()
        result = await register(repo, session, tuple(candidate(f"file-{i}.txt") for i in range(200)), parent_id=11)
        registration_reads = tuple(database.queries)
        assert len(result) == 200
        assert (
            len({value.file.id for value in result})
            == len({value.document_id for value in result})
            == len({value.version_id for value in result})
            == 200
        )
        assert len(registration_reads) <= 18
        assert all(
            part.count("?") <= 200 for sql, _ in registration_reads for part in re.findall(r"\bIN \(([^)]+)\)", sql)
        )
        rows = await contents(session)
        documents = {row["id"]: row for row in rows["knowledge_document"]}
        versions = {row["id"]: row for row in rows["knowledge_document_version"]}
        assert all(
            documents[item.document_id]["primary_version_id"] == item.version_id
            and versions[item.version_id]["knowledge_file_id"] == item.file.id
            for item in result
        )
        print(f"initial registration count=200 SELECT={len(registration_reads)}")
        await repo.arollback_created(session, registrations=result)


async def test_historical_deep_but_consistent_folder_path_is_not_a_new_upload_depth_limit(database):
    rows = [
        original.file(
            100 + i,
            knowledge_id=9700,
            file_type=0,
            level=i,
            file_level_path="" if i == 0 else "/" + "/".join(str(100 + n) for n in range(i)),
        )
        for i in range(11)
    ]
    await database.insert(File, rows)
    repo = api().UploadRegistrationRepository()
    async with AsyncSession(database.engine) as session, session.begin():
        (receipt,) = await register(repo, session, parent_id=110)
        assert receipt.file.level == 11 and receipt.file.file_level_path == "/" + "/".join(
            str(i) for i in range(100, 111)
        )


@pytest.mark.parametrize("field", ["document_id", "version_id"])
async def test_issued_receipt_ids_cannot_be_retyped_to_equal_floats(database, field):
    repo = api().UploadRegistrationRepository()
    async with AsyncSession(database.engine) as session, session.begin():
        (receipt,) = await register(repo, session)
        object.__setattr__(receipt, field, float(getattr(receipt, field)))
        before = await contents(session)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.arollback_created(session, registrations=(receipt,))
        assert await contents(session) == before


async def test_failed_materialization_and_cleanup_leave_the_original_receipt_usable(database):
    before, repo = await snapshot(database), api().UploadRegistrationRepository()
    async with AsyncSession(database.engine) as session, session.begin():
        (receipt,) = await register(repo, session)
        initial = await contents(session)
        await session.execute(
            sa.text(
                "CREATE TRIGGER fail_materialize BEFORE UPDATE OF object_name ON knowledgefile BEGIN SELECT RAISE(ABORT, 'native materialization failure'); END"
            )
        )
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.aset_materialized(session, registration=receipt, object_name="original/key")
        assert await contents(session) == initial
        await session.execute(sa.text("DROP TRIGGER fail_materialize"))
        ready = await repo.aset_materialized(
            session, registration=receipt, object_name="original/key", user_metadata={"exact": [False, 0, 0.0, None]}
        )
        assert ready.file.user_metadata == {"exact": [False, 0, 0.0, None]}
        assert ready.file.update_time == receipt.file.update_time
        materialized = await contents(session)
        await session.execute(
            sa.text(
                "CREATE TRIGGER fail_cleanup BEFORE DELETE ON knowledge_document BEGIN SELECT RAISE(ABORT, 'native cleanup failure'); END"
            )
        )
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.arollback_created(session, registrations=(ready,))
        assert await contents(session) == materialized
        await session.execute(sa.text("DROP TRIGGER fail_cleanup"))
        await repo.arollback_created(session, registrations=(ready,))
    assert await snapshot(database) == before


async def test_cleanup_checks_every_receipt_before_touching_an_earlier_valid_chain(database):
    repo = api().UploadRegistrationRepository()
    async with AsyncSession(database.engine) as session, session.begin():
        one, two = await register(repo, session, (candidate("one"), candidate("two")))
        await session.execute(sa.update(File.__table__).where(File.id == two.file.id).values(status=2))
        before = await contents(session)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.arollback_created(session, registrations=(one, two))
        assert await contents(session) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"file_size": True},
        {"file_size": 0.0},
        {"file_size": -1},
        {"user_id": True},
        {"updater_id": 7.0},
        {"split_rule": {}},
        {"user_metadata": {"not_json": (1, 2)}},
        {"user_metadata": {"not_finite": float("nan")}},
    ],
)
async def test_input_types_are_not_coerced_and_rejection_has_zero_native_io(database, changes):
    repo, statements = api().UploadRegistrationRepository(), []

    def seen(_conn, _cursor, sql, _params, _context, _many):
        statements.append(sql)

    async with AsyncSession(database.engine) as session, session.begin():
        sa.event.listen(database.engine.sync_engine, "before_cursor_execute", seen)
        try:
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await register(repo, session, (candidate(**changes),))
            assert not statements and not session.new and not session.dirty
        finally:
            sa.event.remove(database.engine.sync_engine, "before_cursor_execute", seen)
