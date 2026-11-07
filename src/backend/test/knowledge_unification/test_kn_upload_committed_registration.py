"""T887: actual root commit evidence, explicit ACK and fresh local receipts."""

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from test.knowledge_unification import test_kn_upload_registration_repository as original

native = original.native
database = original.database
File, Document, Version = original.File, original.Document, original.Version


async def reserved(repo, session, *, parent_id=None):
    (registration,) = await original.register(repo, session, parent_id=parent_id)
    return await repo.areserve_object_key(
        session, registration=registration, object_name=f"initial/{registration.file.id}/original.txt"
    )


async def commit(repo, database, *, acknowledge=True):
    async with AsyncSession(database.engine) as session:
        await session.begin()
        receipt = await reserved(repo, session)
        await session.commit()
        if acknowledge:
            assert repo._acknowledge_committed_initial(registrations=(receipt,)) is None
        return receipt


async def test_reserved_key_is_sql_only_preserves_all_other_native_facts_and_cannot_replace(database):
    repo = original.api().UploadRegistrationRepository()
    async with AsyncSession(database.engine) as session, session.begin():
        (initial,) = await original.register(repo, session)
        before = await original.contents(session)
        result = await repo.areserve_object_key(session, registration=initial, object_name="initial/owned.txt")
        after = await original.contents(session)
        expected = dict(next(row for row in before["knowledgefile"] if row["id"] == initial.file.id))
        expected["object_name"] = "initial/owned.txt"
        assert next(row for row in after["knowledgefile"] if row["id"] == initial.file.id) == expected
        assert all(after[key] == before[key] for key in before if key != "knowledgefile")
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.areserve_object_key(session, registration=result, object_name="replacement")
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.arollback_created(session, registrations=(initial,))
        await repo.arollback_created(session, registrations=(result,))


async def test_acknowledged_original_can_be_rechecked_twice_with_fresh_native_transactions(database):
    repo = original.api().UploadRegistrationRepository()
    before = await original.snapshot(database)
    receipt = await commit(repo, database)
    async with AsyncSession(database.engine) as session, session.begin():
        local = await repo._arebind_committed_initial(session, registration=receipt)
        assert local is not receipt and local.file.model_dump() == receipt.file.model_dump()
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.arollback_created(session, registrations=(receipt,))
    # Merely committing the first read transaction does not consume the original.
    async with AsyncSession(database.engine) as session, session.begin():
        second = await repo._arebind_committed_initial(session, registration=receipt)
        await repo.arollback_created(session, registrations=(second,))
    assert await original.snapshot(database) == before


@pytest.mark.parametrize("kind", ["still_open", "savepoint", "rollback", "rollback_then_empty_commit", "other_session"])
async def test_only_the_exact_original_root_commit_can_be_acknowledged(database, kind):
    repo = original.api().UploadRegistrationRepository()
    async with AsyncSession(database.engine) as session:
        await session.begin()
        receipt = await reserved(repo, session)
        if kind == "savepoint":
            async with session.begin_nested():
                pass
        elif kind in {"rollback", "rollback_then_empty_commit"}:
            await session.rollback()
            if kind == "rollback_then_empty_commit":
                await session.commit()
        elif kind == "other_session":
            async with AsyncSession(database.engine) as other:
                await other.commit()
        with pytest.raises(KnowledgeOperationPlanConflictError):
            repo._acknowledge_committed_initial(registrations=(receipt,))
        await session.rollback()


async def test_nested_commit_does_not_consume_the_later_exact_root_observation(database):
    repo = original.api().UploadRegistrationRepository()
    async with AsyncSession(database.engine) as session:
        await session.begin()
        receipt = await reserved(repo, session)
        async with session.begin_nested():
            pass
        await session.commit()
        repo._acknowledge_committed_initial(registrations=(receipt,))
    async with AsyncSession(database.engine) as other, other.begin():
        assert (await repo._arebind_committed_initial(other, registration=receipt)).file.id == receipt.file.id


@pytest.mark.parametrize("wrapper_unknown", [False, True])
async def test_root_after_commit_without_the_explicit_app_ack_never_authorizes_rebind(database, wrapper_unknown):
    repo = original.api().UploadRegistrationRepository()

    class UnknownCommit(AsyncSession):
        async def commit(self):
            await super().commit()
            if wrapper_unknown:
                raise OSError("ACK lost after the actual root commit")

    async with UnknownCommit(database.engine) as session:
        await session.begin()
        receipt = await reserved(repo, session)
        if wrapper_unknown:
            with pytest.raises(OSError):
                await session.commit()
        else:
            await session.commit()
    before = await original.snapshot(database)
    assert any(row["id"] == receipt.file.id for row in before["knowledgefile"])
    async with AsyncSession(database.engine) as session, session.begin():
        database.queries.clear()
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo._arebind_committed_initial(session, registration=receipt)
        assert not database.queries
    assert await original.snapshot(database) == before


@pytest.mark.parametrize("forgery", ["copy", "other_repo", "float_id", "file_mutated", "foreign"])
async def test_ack_is_for_original_unchanged_typed_objects_in_the_original_concrete_scope(database, forgery):
    repo = original.api().UploadRegistrationRepository()
    receipt = await commit(repo, database, acknowledge=False)
    target = receipt
    if forgery == "copy":
        target = replace(receipt)
    elif forgery == "other_repo":
        repo = original.api().UploadRegistrationRepository()
    elif forgery == "float_id":
        object.__setattr__(receipt, "version_id", float(receipt.version_id))
    elif forgery == "file_mutated":
        receipt.file.file_name = "changed receipt"
    token = set_current_tenant_id(202 if forgery == "foreign" else 101)
    try:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            repo._acknowledge_committed_initial(registrations=(target,))
    finally:
        current_tenant_id.reset(token)


async def test_same_original_session_or_a_copied_receipt_cannot_be_fresh_rebound(database):
    repo = original.api().UploadRegistrationRepository()
    async with AsyncSession(database.engine) as session:
        await session.begin()
        receipt = await reserved(repo, session)
        await session.commit()
        repo._acknowledge_committed_initial(registrations=(receipt,))
        await session.begin()
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo._arebind_committed_initial(session, registration=receipt)
        await session.rollback()
    async with AsyncSession(database.engine) as other, other.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo._arebind_committed_initial(other, registration=replace(receipt))


@pytest.mark.parametrize("part", ["rename", "metadata", "status", "document", "version", "history", "alias", "parent"])
async def test_fresh_rebind_reads_all_three_actual_rows_and_rejects_drift_without_writing(database, part):
    repo = original.api().UploadRegistrationRepository()
    receipt = await commit(repo, database)
    async with database.engine.begin() as connection:
        if part == "rename":
            await connection.execute(
                sa.update(File.__table__).where(File.id == receipt.file.id).values(file_name="renamed")
            )
        elif part == "metadata":
            await connection.execute(
                sa.update(File.__table__).where(File.id == receipt.file.id).values(user_metadata={"different": True})
            )
        elif part == "status":
            await connection.execute(sa.update(File.__table__).where(File.id == receipt.file.id).values(status=1))
        elif part == "document":
            await connection.execute(
                sa.update(Document.__table__)
                .where(Document.id == receipt.document_id)
                .values(update_time=receipt.file.update_time + timedelta(seconds=1))
            )
        elif part == "version":
            await connection.execute(
                sa.update(Version.__table__).where(Version.id == receipt.version_id).values(version_no=2)
            )
        elif part == "history":
            await connection.execute(
                Version.__table__.insert(),
                {"document_id": receipt.document_id, "knowledge_file_id": 90, "version_no": 2, "is_primary": False},
            )
        elif part == "alias":
            await connection.execute(
                Document.__table__.insert(),
                {"knowledge_id": 9701, "file_level_path": "", "level": 0, "primary_version_id": receipt.version_id},
            )
        else:
            await connection.execute(
                sa.update(original.original.Knowledge.__table__)
                .where(original.original.Knowledge.id == 9700)
                .values(type=0)
            )
    before = await original.snapshot(database)
    async with AsyncSession(database.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo._arebind_committed_initial(session, registration=receipt)
    assert await original.snapshot(database) == before


async def test_fresh_rebind_cannot_flush_or_erase_unrelated_caller_pending(database):
    repo = original.api().UploadRegistrationRepository()
    receipt = await commit(repo, database)
    async with AsyncSession(database.engine) as session, session.begin():
        pending = File(knowledge_id=9700, file_name="unrelated pending")
        session.add(pending)
        database.queries.clear()
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo._arebind_committed_initial(session, registration=receipt)
        assert pending in session.new and pending.id is None and pending.tenant_id is None and not database.queries
        await session.rollback()


async def test_rebound_local_receipt_is_not_new_committed_initial_authority(database):
    repo = original.api().UploadRegistrationRepository()
    receipt = await commit(repo, database)
    async with AsyncSession(database.engine) as session:
        await session.begin()
        local = await repo._arebind_committed_initial(session, registration=receipt)
        await session.commit()
        with pytest.raises(KnowledgeOperationPlanConflictError):
            repo._acknowledge_committed_initial(registrations=(local,))


async def test_200_original_receipts_share_only_one_instance_root_observer_and_keep_registration_budget(
    database, monkeypatch
):
    repo, events = original.api().UploadRegistrationRepository(), []
    listen = sa.event.listen

    def observed(target, name, *args, **kwargs):
        if name in {"after_commit", "after_transaction_end"}:
            events.append((target, name))
        return listen(target, name, *args, **kwargs)

    monkeypatch.setattr(sa.event, "listen", observed)
    async with AsyncSession(database.engine) as session:
        await session.begin()
        database.queries.clear()
        receipts = await original.register(
            repo, session, tuple(original.candidate(f"file-{i}") for i in range(200)), parent_id=11
        )
        assert len(database.queries) <= 7
        assert [name for target, name in events if target is session.sync_session].count("after_commit") == 1
        assert [name for target, name in events if target is session.sync_session].count("after_transaction_end") == 1
        await session.commit()
        database.queries.clear()
        repo._acknowledge_committed_initial(registrations=receipts)
        assert not database.queries
        await asyncio.sleep(0)  # Instance observers retire after root event dispatch.
        assert (
            not session.sync_session.dispatch.after_commit and not session.sync_session.dispatch.after_transaction_end
        )
    async with AsyncSession(database.engine) as other, other.begin():
        database.queries.clear()
        assert (await repo._arebind_committed_initial(other, registration=receipts[-1])).file.id == receipts[-1].file.id
        assert len(database.queries) <= 6


@pytest.mark.parametrize("changes", [{"tenant_id": 202}, {"type": 0}, {"type": 1}, {"type": 2}])
async def test_upload_root_lock_is_actual_detached_current_type3_only(database, changes):
    repo = original.api().UploadRegistrationRepository()
    async with AsyncSession(database.engine) as session, session.begin():
        row = await repo.alock_space_for_upload(session, space_id=9700)
        assert row.id == 9700 and row.type == 3 and row.tenant_id == 101
        assert sa.inspect(row).transient
        assert (await original.contents(session))["knowledge"]
    async with database.engine.begin() as connection:
        await connection.execute(
            sa.update(original.original.Knowledge.__table__)
            .where(original.original.Knowledge.id == 9700)
            .values(**changes)
        )
    async with AsyncSession(database.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.alock_space_for_upload(session, space_id=9700)


async def test_upload_root_lock_rejects_pending_without_flush_or_new_query(database):
    repo = original.api().UploadRegistrationRepository()
    async with AsyncSession(database.engine) as session, session.begin():
        pending = File(knowledge_id=9700, file_name="original caller")
        session.add(pending)
        database.queries.clear()
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.alock_space_for_upload(session, space_id=9700)
        assert not database.queries and pending.id is None and pending.tenant_id is None
        await session.rollback()
