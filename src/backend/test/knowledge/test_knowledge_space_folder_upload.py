"""Original F034 folder contract against real registration and native SQL.

Only permission/object/queue transports are isolated. The actual directory and
File/Doc/V1 writers execute; no FakeDAO or second folder algorithm is involved.
"""

from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

from bisheng.common.errcode.knowledge_space import (
    SpaceFileSizeLimitError,
    SpaceFolderDepthError,
    SpaceFolderDuplicateError,
    SpaceFolderUploadCountExceededError,
)
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.schemas.knowledge_space_schema import FolderUploadItem
from bisheng.knowledge.domain.services import knowledge_space_service as module
from test.knowledge_unification import test_kn_folder_upload_wiring as fixtures
from test.knowledge_unification.test_kn_space_upload_wiring import chain_snapshot

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission
processing = fixtures.processing
application = fixtures.application
files = fixtures.files
legacy = fixtures.legacy
upload = fixtures.upload
folder_upload = fixtures.folder_upload


def _items(*paths, size=10):
    return [
        FolderUploadItem(file_path="opaque-document" if i == 0 else "opaque-table", relative_path=path, size=size)
        for i, path in enumerate(paths)
    ]


async def _folder_rows(upload):
    async with upload.context.sessions() as session:
        return (
            await session.exec(
                select(KnowledgeFile).where(KnowledgeFile.knowledge_id == 40, KnowledgeFile.file_type == 0)
            )
        ).all()


async def _existing_parent(upload, level):
    async with upload.context.sessions() as session:
        space = await session.get(Knowledge, 40)
    app = upload.service.upload_application_factory()
    parent_id = None
    for index in range(level + 1):
        parent = await app.acreate_folder(knowledge=space, parent_id=parent_id, folder_name=f"ancestor-{index}")
        parent_id = parent.id
    return parent


async def test_builds_nested_tree_and_groups_files(folder_upload):
    upload = folder_upload.upload
    svc = upload.service
    svc.add_file = AsyncMock(wraps=svc.add_file)
    await svc.upload_folder_items(40, _items("Root/a.pdf", "Root/Sub/b.pdf", "Root/Sub/Deep/c.pdf"))
    by_name = {row.file_name: row for row in await _folder_rows(upload)}
    assert set(by_name) == {"Root", "Sub", "Deep"}
    root, sub, deep = (by_name[name] for name in ("Root", "Sub", "Deep"))
    assert (root.level, root.file_level_path) == (0, "")
    assert (sub.level, sub.file_level_path) == (1, f"/{root.id}")
    assert (deep.level, deep.file_level_path) == (2, f"/{root.id}/{sub.id}")
    calls = {call.kwargs["parent_id"]: call.args[1] for call in svc.add_file.await_args_list}
    assert calls == {root.id: ["opaque-document"], sub.id: ["opaque-table"], deep.id: ["opaque-table"]}
    targets = [
        call.kwargs["target"]
        for call in upload.projection._permission.authorize_created.await_args_list
        if call.kwargs["target"].resource_type == "folder"
    ]
    assert [(target.resource_id, target.parent_type, target.parent_id) for target in targets] == [
        (str(root.id), "knowledge_space", "40"),
        (str(sub.id), "folder", str(root.id)),
        (str(deep.id), "folder", str(sub.id)),
    ]
    svc._initialize_child_resource_permissions.assert_not_awaited()


async def test_nested_folder_grouping_preserves_trusted_sources(folder_upload):
    """Legacy-wire folder uploads keep each server-resolved source with its own file."""
    svc = folder_upload.upload.service
    svc.add_file = AsyncMock(return_value=[])
    items = [
        FolderUploadItem(file_path=f"opaque-{i}", relative_path=path, size=10)
        for i, path in enumerate(("Root/a.pdf", "Root/Sub/b.pdf", "Root/c.pdf"))
    ]
    sources = [object(), object(), object()]

    await svc.upload_folder_items(40, items, trusted_sources=sources)

    calls = {tuple(call.args[1]): call.kwargs["trusted_sources"] for call in svc.add_file.await_args_list}
    assert calls == {
        ("opaque-0", "opaque-2"): [sources[0], sources[2]],
        ("opaque-1",): [sources[1]],
    }


async def test_upload_under_existing_parent_folder(folder_upload):
    upload = folder_upload.upload
    parent = await _existing_parent(upload, 2)
    await upload.service.upload_folder_items(40, _items("Top/x.pdf"), parent_id=parent.id)
    top = next(row for row in await _folder_rows(upload) if row.file_name == "Top")
    assert (top.level, top.file_level_path) == (3, f"{parent.file_level_path}/{parent.id}")
    target = next(
        call.kwargs["target"]
        for call in upload.projection._permission.authorize_created.await_args_list
        if call.kwargs["target"].resource_type == "folder" and call.kwargs["target"].resource_id == str(top.id)
    )
    assert (target.parent_type, target.parent_id) == ("folder", str(parent.id))


async def test_count_over_1000_rejected(folder_upload):
    upload = folder_upload.upload
    before = await chain_snapshot(upload)
    with pytest.raises(SpaceFolderUploadCountExceededError):
        await upload.service.upload_folder_items(40, _items(*[f"Root/f{i}.pdf" for i in range(1001)]))
    assert await chain_snapshot(upload) == before and not folder_upload.apps
    upload.publish.assert_not_called()


async def test_depth_over_limit_rejected_whole_batch(folder_upload):
    upload = folder_upload.upload
    parent = await _existing_parent(upload, 8)
    before = await chain_snapshot(upload)
    with pytest.raises(SpaceFolderDepthError):
        await upload.service.upload_folder_items(40, _items("A/B/d.pdf"), parent_id=parent.id)
    assert await chain_snapshot(upload) == before
    upload.publish.assert_not_called()


async def test_depth_into_deepest_folder_rejected(folder_upload):
    upload = folder_upload.upload
    parent = await _existing_parent(upload, 9)
    before = await chain_snapshot(upload)
    with pytest.raises(SpaceFolderDepthError):
        await upload.service.upload_folder_items(40, _items("A/d.pdf"), parent_id=parent.id)
    assert await chain_snapshot(upload) == before


async def test_depth_deepest_folder_at_level_9_allowed(folder_upload):
    upload = folder_upload.upload
    parent = await _existing_parent(upload, 7)
    result = await upload.service.upload_folder_items(40, _items("A/B/d.pdf"), parent_id=parent.id)
    assert {row.level for row in await _folder_rows(upload) if row.file_name in {"A", "B"}} == {8, 9}
    assert result[0].level == 10


async def test_top_level_name_conflict_rejected(folder_upload):
    upload = folder_upload.upload
    await upload.service.upload_folder_items(40, _items("Root/a.pdf"))
    before = await chain_snapshot(upload)
    upload.publish.reset_mock()
    with pytest.raises(SpaceFolderDuplicateError):
        await upload.service.upload_folder_items(40, _items("Root/b.pdf"))
    assert await chain_snapshot(upload) == before
    upload.publish.assert_not_called()


async def test_capacity_precheck_user_limit_rejects_batch(folder_upload, monkeypatch):
    upload = folder_upload.upload
    before = await chain_snapshot(upload)
    monkeypatch.setattr(module.QuotaService, "get_knowledge_space_upload_limit_bytes", AsyncMock(return_value=100))
    monkeypatch.setattr(module.SpaceFileDao, "get_user_total_file_size", AsyncMock(return_value=50))
    with pytest.raises(SpaceFileSizeLimitError):
        await upload.service.upload_folder_items(
            40, _items("R/a.pdf", "R/b.pdf", "R/c.pdf", "R/d.pdf", "R/e.pdf", "R/f.pdf", size=10)
        )
    assert await chain_snapshot(upload) == before and not folder_upload.apps
    upload.publish.assert_not_called()


async def test_capacity_precheck_tenant_limit_rejects_batch(folder_upload, monkeypatch):
    upload = folder_upload.upload
    before = await chain_snapshot(upload)
    monkeypatch.setattr(module.QuotaService, "get_tenant_storage_remaining_bytes", AsyncMock(return_value=10))
    monkeypatch.setattr(module.QuotaService, "get_tenant_storage_used_bytes", AsyncMock(return_value=0))
    with pytest.raises(Exception) as caught:
        await upload.service.upload_folder_items(40, _items("R/a.pdf", "R/b.pdf", size=10))
    assert "quota" in type(caught.value).__name__.lower()
    assert await chain_snapshot(upload) == before and not folder_upload.apps


async def test_folder_create_failure_rolls_back_created_folders(folder_upload):
    upload = folder_upload.upload
    before = await chain_snapshot(upload)
    failure = RuntimeError("fga down")
    upload.projection._permission.authorize_created.side_effect = [None, failure]
    with pytest.raises(RuntimeError) as caught:
        await upload.service.upload_folder_items(40, _items("Root/Sub/a.pdf"))
    assert caught.value is failure and await chain_snapshot(upload) == before
    inverse = [call.kwargs["target"] for call in upload.projection._permission.rollback_created.await_args_list]
    assert len(inverse) == 2 and all(target.resource_type == "folder" for target in inverse)
    upload.publish.assert_not_called()


async def test_file_dup_failed_entries_aggregate_without_raise(folder_upload):
    upload = folder_upload.upload
    result = await upload.service.upload_folder_items(
        40,
        [
            FolderUploadItem(file_path="opaque-document", relative_path="Root/a.pdf"),
            FolderUploadItem(file_path="opaque-document", relative_path="Root/Sub/b.pdf"),
            FolderUploadItem(file_path="opaque-table", relative_path="Root/Sub/c.csv"),
        ],
    )
    assert [row.status for row in result] == [5, 3, 5]
    assert result[0].id == result[1].id and result[2].id != result[0].id
    assert upload.publish.call_count == 2
