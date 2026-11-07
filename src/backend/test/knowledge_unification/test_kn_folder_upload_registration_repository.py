"""Native folder ownership, committed ACK and unchanged empty-tree cleanup."""

import importlib
from dataclasses import replace

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from test.knowledge_unification import test_kn_upload_registration_repository as original

native = original.native
database = original.database
File, Document, Version = original.File, original.Document, original.Version


def api():
    return importlib.import_module("bisheng.knowledge.domain.repositories.folder_upload_registration_repository")


def folder(name="original_%folder"):
    return api().NewUploadFolder(name=name, user_id=7, user_name="creator", updater_id=7, updater_name="updater")


async def stage(repo, session, *, parent=11):
    return await repo.aregister_folder(session, space_id=9700, parent_id=parent, folder=folder())


async def create(repo, database):
    async with AsyncSession(database.engine) as session:
        await session.begin()
        staged = await stage(repo, session)
        await session.commit()
        owned = repo._acknowledge_committed_folder(registration=staged)
    return owned


async def test_native_folder_only_registration_and_outer_rollback_preserve_file_doc_v1_tables(database):
    before, repo = await original.snapshot(database), api().FolderUploadRegistrationRepository()
    async with AsyncSession(database.engine) as session, session.begin():
        staged = await stage(repo, session)
        assert (staged.file.file_type, staged.file.status, staged.file.tenant_id) == (0, 2, 101)
        assert (staged.file.file_level_path, staged.file.level) == ("/10/11", 2)
        assert staged.file.file_name == "original_%folder" and staged.file.user_id == 7
        current = await original.contents(session)
        assert current["knowledge_document"] == before["knowledge_document"]
        assert current["knowledge_document_version"] == before["knowledge_document_version"]
        await session.rollback()
    assert await original.snapshot(database) == before


async def test_owned_folder_can_be_rechecked_twice_and_deleted_only_in_new_native_tx(database):
    before, repo = await original.snapshot(database), api().FolderUploadRegistrationRepository()
    owned = await create(repo, database)
    async with AsyncSession(database.engine) as first, first.begin():
        local = await repo._arebind_owned_empty_folder(first, registration=owned)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            repo._acknowledge_committed_folder(registration=local)
    async with AsyncSession(database.engine) as second, second.begin():
        local = await repo._arebind_owned_empty_folder(second, registration=owned)
        await repo.arollback_created_empty(second, receipt=local)
    assert await original.snapshot(database) == before


@pytest.mark.parametrize(
    "case", ["active", "rollback", "savepoint_only", "no_ack", "other_repo", "copy", "foreign", "mutated"]
)
async def test_only_actual_original_root_ack_can_issue_owned_folders(database, case):
    repo = api().FolderUploadRegistrationRepository()
    async with AsyncSession(database.engine) as session:
        await session.begin()
        staged = await stage(repo, session)
        if case == "rollback":
            await session.rollback()
        elif case == "savepoint_only":
            async with session.begin_nested():
                pass
        elif case not in {"active"}:
            await session.commit()
        if case == "no_ack":
            async with AsyncSession(database.engine) as fresh, fresh.begin():
                with pytest.raises(KnowledgeOperationPlanConflictError):
                    await repo._arebind_owned_empty_folder(fresh, registration=staged)
            return
        if case == "other_repo":
            repo = api().FolderUploadRegistrationRepository()
        elif case == "copy":
            staged = replace(staged)
        elif case == "mutated":
            staged.file.file_name = "new caller name"
        token = set_current_tenant_id(202 if case == "foreign" else 101)
        try:
            with pytest.raises(KnowledgeOperationPlanConflictError):
                repo._acknowledge_committed_folder(registration=staged)
        finally:
            current_tenant_id.reset(token)


@pytest.mark.parametrize(
    "field,value",
    [
        ("file_name", "renamed"),
        ("file_level_path", ""),
        ("user_id", 8),
        ("status", 3),
        ("file_type", 1),
        ("user_metadata", {"new": [False, 0, 0.0]}),
        ("object_name", "owned-elsewhere"),
    ],
)
async def test_actual_full_row_drift_cannot_be_erased_by_creation_cleanup(database, field, value):
    repo = api().FolderUploadRegistrationRepository()
    owned = await create(repo, database)
    async with database.engine.begin() as connection:
        await connection.execute(sa.update(File.__table__).where(File.id == owned.file.id).values(**{field: value}))
    before = await original.snapshot(database)
    async with AsyncSession(database.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo._arebind_owned_empty_folder(session, registration=owned)
    assert await original.snapshot(database) == before


@pytest.mark.parametrize("status", range(8))
@pytest.mark.parametrize("kind", [0, 1])
async def test_every_child_status_and_kind_preserves_owned_parent(database, status, kind):
    repo = api().FolderUploadRegistrationRepository()
    owned = await create(repo, database)
    prefix = f"{owned.file.file_level_path}/{owned.file.id}"
    await database.insert(
        File, [original.original.file(1000, knowledge_id=9700, file_level_path=prefix, file_type=kind, status=status)]
    )
    async with AsyncSession(database.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo._arebind_owned_empty_folder(session, registration=owned)
    assert any(row["id"] == owned.file.id for row in (await original.snapshot(database))["knowledgefile"])


@pytest.mark.parametrize("case", ["descendant", "broken_document", "broken_version", "parent_changed", "foreign_child"])
async def test_orphan_relationships_or_broken_parent_are_not_hidden_by_inner_joins(database, case):
    repo = api().FolderUploadRegistrationRepository()
    owned = await create(repo, database)
    prefix = f"{owned.file.file_level_path}/{owned.file.id}"
    async with database.engine.begin() as connection:
        if case == "foreign_child":
            await connection.execute(
                File.__table__.insert(),
                original.original.file(1000, tenant=202, knowledge_id=8000, file_level_path=prefix),
            )
        elif case == "descendant":
            await connection.execute(
                File.__table__.insert(),
                original.original.file(1000, knowledge_id=9700, file_level_path=prefix + "/999999"),
            )
        elif case == "broken_document":
            await connection.execute(
                Document.__table__.insert(),
                {"id": 1000, "knowledge_id": 9700, "file_level_path": prefix, "primary_version_id": 999999},
            )
        elif case == "broken_version":
            await connection.execute(
                Version.__table__.insert(),
                {
                    "id": 1000,
                    "document_id": 999999,
                    "knowledge_file_id": owned.file.id,
                    "version_no": 1,
                    "is_primary": True,
                },
            )
        else:
            await connection.execute(sa.update(File.__table__).where(File.id == 11).values(file_level_path="", level=0))
    async with AsyncSession(database.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo._arebind_owned_empty_folder(session, registration=owned)


async def test_recheck_after_projection_gap_detects_new_child_and_preserves_both(database):
    repo = api().FolderUploadRegistrationRepository()
    owned = await create(repo, database)
    async with AsyncSession(database.engine) as session, session.begin():
        await repo._arebind_owned_empty_folder(session, registration=owned)
    prefix = f"{owned.file.file_level_path}/{owned.file.id}"
    await database.insert(File, [original.original.file(1000, knowledge_id=9700, file_level_path=prefix)])
    before = await original.snapshot(database)
    async with AsyncSession(database.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo._arebind_owned_empty_folder(session, registration=owned)
    assert await original.snapshot(database) == before


async def test_local_receipt_rechecks_again_and_rejects_forgery_or_other_tx(database):
    repo = api().FolderUploadRegistrationRepository()
    owned = await create(repo, database)
    async with AsyncSession(database.engine) as session, session.begin():
        local = await repo._arebind_owned_empty_folder(session, registration=owned)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.arollback_created_empty(session, receipt=replace(local))
        with session.no_autoflush:
            await session.execute(
                sa.update(File.__table__).where(File.id == owned.file.id).values(file_name="same-TX change")
            )
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.arollback_created_empty(session, receipt=local)
        await session.rollback()
    async with AsyncSession(database.engine) as other, other.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.arollback_created_empty(other, receipt=local)


async def test_parent_foreign_pending_and_receipt_scope_fail_without_mutating_caller(database):
    repo = api().FolderUploadRegistrationRepository()
    async with AsyncSession(database.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await stage(repo, session, parent=20)
        pending = File(**original.original.file(1000, knowledge_id=9700))
        session.add(pending)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await stage(repo, session)
        assert pending in session.new
        await session.rollback()
    owned = await create(repo, database)
    token = set_current_tenant_id(202)
    try:
        async with AsyncSession(database.engine) as session, session.begin():
            database.queries.clear()
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await repo._arebind_owned_empty_folder(session, registration=owned)
            assert not database.queries
    finally:
        current_tenant_id.reset(token)


async def test_prefix_is_literal_and_a_sibling_path_does_not_block_deletion(database):
    repo = api().FolderUploadRegistrationRepository()
    owned = await create(repo, database)
    await database.insert(
        File,
        [
            original.original.file(
                1000, knowledge_id=9700, file_level_path=f"{owned.file.file_level_path}/{owned.file.id}0"
            )
        ],
    )
    async with AsyncSession(database.engine) as session, session.begin():
        local = await repo._arebind_owned_empty_folder(session, registration=owned)
        await repo.arollback_created_empty(session, receipt=local)
    assert not any(row["id"] == owned.file.id for row in (await original.snapshot(database))["knowledgefile"])
