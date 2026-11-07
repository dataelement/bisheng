"""One actual App owns parent-first folders and files; no SQL session spans IO."""

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, KnowledgeProcessingConflictError
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState
from test.knowledge_unification import test_kn_space_upload_application as original

native = original.native
database = original.database
case = original.case


async def folder(application, case, *, parent=None, name="original folder"):
    return await application.acreate_folder(knowledge=case.knowledge, parent_id=parent, folder_name=name)


@pytest.mark.parametrize("parent", [None, 11])
async def test_folder_uses_only_parent_upload_and_original_creation_record_without_blob_io(case, monkeypatch, parent):
    application = original.app(case, monkeypatch)
    before = await original.original.snapshot(case.database)
    row = await folder(application, case, parent=parent)
    assert row.file_type == 0 and row.status == 2 and row.tenant_id == 101
    assert (row.file_level_path, row.level) == (("/10/11", 2) if parent else ("", 0))
    assert case.events == [("folder" if parent else "knowledge_space", parent or 9700, "upload_file"), "project"]
    call = case.adapter._permission.authorize_created.await_args.kwargs
    assert call["target"].resource_type == "folder" and call["actor"] is case.actor
    assert call["target"].parent_id == str(parent or 9700)
    after = await original.original.snapshot(case.database)
    assert after["knowledge_document"] == before["knowledge_document"]
    assert after["knowledge_document_version"] == before["knowledge_document_version"]
    assert not case.blobs and not case.active and all(not session.in_transaction() for session in case.sessions)


async def test_same_instance_projects_parents_first_then_unwinds_files_before_deepest_folders(case, monkeypatch):
    application = original.app(case, monkeypatch)
    before = await original.original.snapshot(case.database)
    parent = await folder(application, case)
    child = await folder(application, case, parent=parent.id, name="child")
    file = await original.create(application, case, parent_id=child.id)
    targets = [call.kwargs["target"] for call in case.adapter._permission.authorize_created.await_args_list]
    assert [(target.resource_type, int(target.resource_id)) for target in targets] == [
        ("folder", parent.id),
        ("folder", child.id),
        ("knowledge_file", file.id),
    ]
    assert targets[1].parent_id == str(parent.id) and targets[2].parent_id == str(child.id)
    await application.arollback_created()
    inverses = [call.kwargs["target"] for call in case.adapter._permission.rollback_created.await_args_list]
    assert [(target.resource_type, int(target.resource_id)) for target in inverses] == [
        ("knowledge_file", file.id),
        ("folder", child.id),
        ("folder", parent.id),
    ]
    assert await original.original.snapshot(case.database) == before
    assert not case.blobs and not case.projection
    assert all(event[2] == "upload_file" for event in case.events if type(event) is tuple)


async def test_failed_child_projection_uses_created_inverse_and_then_owned_empty_sql(case, monkeypatch):
    application = original.app(case, monkeypatch)
    before = await original.original.snapshot(case.database)
    parent = await folder(application, case)
    case.fail = "project"
    with pytest.raises(OSError, match="project"):
        await folder(application, case, parent=parent.id)
    case.fail = None
    await application.arollback_created()
    assert await original.original.snapshot(case.database) == before
    assert len(case.adapter._permission.rollback_created.await_args_list) == 2


async def test_file_blob_failure_rolls_back_file_receipt_before_empty_parent(case, monkeypatch):
    application = original.app(case, monkeypatch)
    before = await original.original.snapshot(case.database)
    parent = await folder(application, case)
    case.fail = "put"
    with pytest.raises(OSError, match="put"):
        await original.create(application, case, parent_id=parent.id)
    case.fail = None
    await application.arollback_created()
    assert await original.original.snapshot(case.database) == before and not case.blobs


@pytest.mark.parametrize("kind", ["folder", "file"])
async def test_unknown_native_initial_commit_never_authorizes_tree_cleanup(case, monkeypatch, kind):
    application = original.app(case, monkeypatch)
    parent = None if kind == "folder" else await folder(application, case)
    case.fail_commit = (1 if kind == "folder" else 2, "after")
    with pytest.raises(OSError, match="commit ACK unknown") as caught:
        if kind == "folder":
            await folder(application, case)
        else:
            await original.create(application, case, parent_id=parent.id)
    before = await original.original.snapshot(case.database)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await application.arollback_created()
    assert await original.original.snapshot(case.database) == before
    case.adapter._permission.rollback_created.assert_not_awaited()
    assert all(
        not {"path", "object_name", "config", "credential"} & progress.keys()
        for progress in caught.value.space_upload_progress
    )


@pytest.mark.parametrize("kind", ["rename", "extra_child"])
async def test_changed_or_nonempty_folder_survives_before_any_permission_inverse(case, monkeypatch, kind):
    application = original.app(case, monkeypatch)
    row = await folder(application, case)
    async with case.database.engine.begin() as connection:
        if kind == "rename":
            await connection.execute(
                sa.update(original.original.File.__table__)
                .where(original.original.File.id == row.id)
                .values(file_name="changed name")
            )
        else:
            await connection.execute(
                original.original.File.__table__.insert(),
                original.original.original.file(1000, knowledge_id=9700, file_level_path=f"/{row.id}", status=7),
            )
    before = await original.original.snapshot(case.database)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await application.arollback_created()
    case.adapter._permission.rollback_created.assert_not_awaited()
    assert await original.original.snapshot(case.database) == before


async def test_child_arriving_during_inverse_is_seen_in_fresh_sql_recheck(case, monkeypatch):
    application = original.app(case, monkeypatch)
    row = await folder(application, case)

    async def add_child():
        await case.database.insert(
            original.original.File,
            [original.original.original.file(1000, knowledge_id=9700, file_level_path=f"/{row.id}")],
        )

    case.inverse_hook = add_child
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await application.arollback_created()
    after = await original.original.snapshot(case.database)
    assert any(file["id"] == row.id for file in after["knowledgefile"])
    assert any(file["id"] == 1000 for file in after["knowledgefile"])
    assert not case.active


async def test_failed_file_inverse_keeps_all_owned_parent_folders(case, monkeypatch):
    application = original.app(case, monkeypatch)
    parent = await folder(application, case)
    await original.create(application, case, parent_id=parent.id)
    before = await original.original.snapshot(case.database)
    case.fail = "inverse"
    with pytest.raises(OSError, match="inverse"):
        await application.arollback_created()
    assert await original.original.snapshot(case.database) == before
    calls = case.adapter._permission.rollback_created.await_args_list
    assert len(calls) == 1 and calls[0].kwargs["target"].resource_type == "knowledge_file"


async def test_visible_only_does_not_create_folder_or_open_business_session(case, monkeypatch):
    application = original.app(case, monkeypatch)
    case.allowed = {"visible"}
    with pytest.raises(SpacePermissionDeniedError):
        await folder(application, case)
    assert not case.sessions and not case.blobs


async def test_actual_locked_root_busy_prevents_new_folder_before_projection(case, monkeypatch):
    application = original.app(case, monkeypatch)
    async with case.database.engine.begin() as connection:
        await connection.execute(
            sa.update(Knowledge.__table__).where(Knowledge.id == 9700).values(state=KnowledgeState.REBUILDING.value)
        )
    before = await original.original.snapshot(case.database)
    with pytest.raises(KnowledgeProcessingConflictError):
        await folder(application, case)
    assert await original.original.snapshot(case.database) == before
    case.adapter._permission.authorize_created.assert_not_awaited()
