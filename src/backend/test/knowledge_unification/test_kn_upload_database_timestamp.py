"""T906: native updater effects, without pretending SQLite is a DM runtime."""

from datetime import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from test.knowledge_unification import test_kn_upload_registration_repository as original

native = original.native
database = original.database
File, Document, Version = original.File, original.Document, original.Version


async def updater(database, *, stamp="2041-03-04 05:06:07", extra=""):
    # SQLite cannot assign NEW columns in a BEFORE trigger. AFTER + a nested
    # UPDATE models the existing DM updater's net persisted unconditional value.
    async with database.engine.begin() as connection:
        await connection.exec_driver_sql(
            "CREATE TRIGGER original_updater AFTER UPDATE ON knowledgefile BEGIN "
            f"UPDATE knowledgefile SET update_time='{stamp}' WHERE id=NEW.id; {extra} END"
        )


async def one(session, file_id):
    rows = await original.contents(session)
    file = next(row for row in rows["knowledgefile"] if row["id"] == file_id)
    version = next(row for row in rows["knowledge_document_version"] if row["knowledge_file_id"] == file_id)
    doc = next(row for row in rows["knowledge_document"] if row["id"] == version["document_id"])
    return file, doc, version


@pytest.mark.parametrize("stamp", ["2001-02-03 04:05:06", "2041-03-04 05:06:07"])
@pytest.mark.parametrize("operation", ["reserve", "materialize"])
async def test_initial_file_receipt_uses_the_actual_database_update_time_without_a_clock_assumption(
    database, stamp, operation
):
    await updater(database, stamp=stamp)
    repo = original.api().UploadRegistrationRepository()
    async with AsyncSession(database.engine) as session, session.begin():
        (first,) = await original.register(repo, session, parent_id=11)
        before = await one(session, first.file.id)
        metadata = {"exact": [False, 0, 0.0, None]}
        if operation == "reserve":
            current = await repo.areserve_object_key(session, registration=first, object_name="initial/owned.txt")
        else:
            current = await repo.aset_materialized(
                session, registration=first, object_name="initial/owned.txt", user_metadata=metadata
            )
        actual = await one(session, current.file.id)
        expected = dict(before[0], object_name="initial/owned.txt", update_time=datetime.fromisoformat(stamp))
        if operation == "materialize":
            expected["user_metadata"] = metadata
        assert actual[0] == expected and actual[1:] == before[1:]
        assert current.file.update_time == expected["update_time"] != first.file.update_time
        assert current.file.model_dump(mode="python") == actual[0]
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.arollback_created(session, registrations=(first,))
        await repo.arollback_created(session, registrations=(current,))


async def test_actual_timestamp_is_part_of_the_ack_and_both_fresh_local_rechecks(database):
    await updater(database)
    repo, before = original.api().UploadRegistrationRepository(), await original.snapshot(database)
    async with AsyncSession(database.engine) as session:
        await session.begin()
        (first,) = await original.register(repo, session)
        current = await repo.areserve_object_key(session, registration=first, object_name="initial/owned.txt")
        await session.commit()
        repo._acknowledge_committed_initial(registrations=(current,))
    async with AsyncSession(database.engine) as session, session.begin():
        local = await repo._arebind_committed_initial(session, registration=current)
        assert local.file.update_time == datetime(2041, 3, 4, 5, 6, 7)
    async with AsyncSession(database.engine) as session, session.begin():
        local = await repo._arebind_committed_initial(session, registration=current)
        await repo.arollback_created(session, registrations=(local,))
    assert await original.snapshot(database) == before


async def test_accepting_initial_database_time_does_not_ignore_a_later_file_time_drift(database):
    await updater(database)
    repo = original.api().UploadRegistrationRepository()
    async with AsyncSession(database.engine) as session:
        await session.begin()
        (first,) = await original.register(repo, session)
        current = await repo.areserve_object_key(session, registration=first, object_name="initial/owned.txt")
        await session.commit()
        repo._acknowledge_committed_initial(registrations=(current,))
    async with database.engine.begin() as connection:
        await connection.exec_driver_sql("DROP TRIGGER original_updater")
        await connection.execute(
            sa.update(File.__table__).where(File.id == current.file.id).values(update_time=datetime(2042, 1, 1))
        )
    before = await original.snapshot(database)
    async with AsyncSession(database.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo._arebind_committed_initial(session, registration=current)
    assert await original.snapshot(database) == before


@pytest.mark.parametrize(
    "assignment",
    [
        "file_size=999",
        "create_time='2001-02-03 04:05:06'",
        "knowledge_id=9701",
        "user_metadata='{}'",
    ],
)
async def test_time_updater_does_not_allow_any_other_file_column_drift_or_half_materialization(database, assignment):
    await updater(database, extra=f"UPDATE knowledgefile SET {assignment} WHERE id=NEW.id;")
    repo = original.api().UploadRegistrationRepository()
    async with AsyncSession(database.engine) as session, session.begin():
        (first,) = await original.register(repo, session)
        before = await original.contents(session)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.areserve_object_key(session, registration=first, object_name="initial/owned.txt")
        assert await original.contents(session) == before
    assert await original.snapshot(database) == before


@pytest.mark.parametrize(
    "table,condition",
    [
        (
            "knowledge_document",
            "id IN (SELECT document_id FROM knowledge_document_version WHERE knowledge_file_id=NEW.id)",
        ),
        ("knowledge_document_version", "knowledge_file_id=NEW.id"),
    ],
)
async def test_materialization_never_absorbs_document_or_version_timestamp_changes(database, table, condition):
    await updater(database, extra=f"UPDATE {table} SET update_time='2001-02-03 04:05:06' WHERE {condition};")
    repo = original.api().UploadRegistrationRepository()
    async with AsyncSession(database.engine) as session, session.begin():
        (first,) = await original.register(repo, session)
        before = await original.contents(session)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.aset_materialized(session, registration=first, object_name="initial/owned.txt")
        assert await original.contents(session) == before
    assert await original.snapshot(database) == before


async def test_initial_document_primary_link_captures_its_own_actual_database_timestamp(database):
    async with database.engine.begin() as connection:
        await connection.exec_driver_sql(
            "CREATE TRIGGER original_document_updater AFTER UPDATE ON knowledge_document BEGIN "
            "UPDATE knowledge_document SET update_time='2001-02-03 04:05:06' WHERE id=NEW.id; END"
        )
    repo = original.api().UploadRegistrationRepository()
    async with AsyncSession(database.engine) as session:
        await session.begin()
        (current,) = await original.register(repo, session)
        file, doc, version = await one(session, current.file.id)
        assert doc["update_time"] == datetime(2001, 2, 3, 4, 5, 6)
        assert doc["primary_version_id"] == version["id"] and file["update_time"] != doc["update_time"]
        await session.commit()
        repo._acknowledge_committed_initial(registrations=(current,))
    async with AsyncSession(database.engine) as session, session.begin():
        local = await repo._arebind_committed_initial(session, registration=current)
        await repo.arollback_created(session, registrations=(local,))
