"""A folder request stages the real tree/files before the existing dispatch tail."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from bisheng.common.errcode.knowledge_space import SpaceFileSizeLimitError
from bisheng.core.context import tenant as context
from bisheng.knowledge.api.dependencies import get_knowledge_space_service
from bisheng.knowledge.api.endpoints import knowledge_space as api
from bisheng.knowledge.domain.models import knowledge_space_file
from bisheng.knowledge.domain.schemas.knowledge_space_schema import FolderUploadItem
from bisheng.knowledge.domain.services import knowledge_space_service as module
from bisheng.permission.application.identity import (
    PermissionActor,
    reset_current_permission_actor,
    set_current_permission_actor,
)
from test.knowledge_unification import test_kn_upload as fixtures
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


@pytest.fixture
async def folder_upload(upload, monkeypatch, tmp_path):
    monkeypatch.setattr(knowledge_space_file, "get_async_db_session", upload.context.sessions)
    globals_ = upload.legacy.cls.prepare_one_file.__func__.__globals__
    download = globals_["file_download"]
    second = tmp_path / "differenthash_second.csv"
    second.write_text("header\nsecond source\n", encoding="utf-8")
    monkeypatch.setitem(
        globals_,
        "file_download",
        lambda path: (str(second), "sheet.csv") if path == "opaque-table" else download(path),
    )
    factory = upload.service.upload_application_factory
    apps = []

    def build():
        result = factory()
        apps.append(result)
        return result

    upload.service.upload_application_factory = build
    return SimpleNamespace(upload=upload, apps=apps, second=second)


def items(second="opaque-table"):
    return [
        FolderUploadItem(file_path="opaque-document", relative_path="Root/a.txt", size=0),
        FolderUploadItem(file_path=second, relative_path="Root/Sub/b.csv", size=0),
    ]


async def test_later_directory_failure_has_zero_dispatch_and_unwinds_the_whole_owned_tree(folder_upload):
    upload = folder_upload.upload
    before = await chain_snapshot(upload)
    with pytest.raises(KeyError):
        await upload.service.upload_folder_items(40, items("missing-input"))
    upload.publish.assert_not_called()
    assert await chain_snapshot(upload) == before
    assert len(folder_upload.apps) == 1
    kinds = [
        call.kwargs["target"].resource_type for call in upload.projection._permission.rollback_created.await_args_list
    ]
    assert kinds == ["knowledge_file", "folder", "folder"]


async def test_real_folder_http_uses_one_app_and_projects_all_resources_before_first_dispatch(folder_upload):
    upload = folder_upload.upload

    def dispatch(**kwargs):
        assert upload.projection._permission.authorize_created.await_count == 4

    upload.publish.side_effect = dispatch
    server = FastAPI()
    server.include_router(api.router, prefix="/api/v1")
    server.dependency_overrides[get_knowledge_space_service] = lambda: upload.service
    # Legacy wire resolves issued upload references first; that contract is tested separately.
    with patch.object(api.PreviewSourceService, "resolve", AsyncMock(return_value=None)):
        async with AsyncClient(transport=ASGITransport(app=server), base_url="http://offline") as client:
            response = await client.post(
                "/api/v1/knowledge/space/40/folders/upload",
                json={"items": [item.model_dump() for item in items()]},
            )
    assert response.status_code == 200 and len(response.json()["data"]) == 2
    assert len(folder_upload.apps) == 1 and upload.publish.call_count == 2
    upload.service._initialize_child_resource_permissions.assert_not_awaited()
    assert all(call.args[2] == "upload_file" for call in upload.service._require_action.await_args_list)


async def test_second_projection_failure_unwinds_files_then_all_folders_without_dispatch(folder_upload):
    upload = folder_upload.upload
    before = await chain_snapshot(upload)
    failure = OSError("second file projection failed")

    async def project(**kwargs):
        if upload.projection._permission.authorize_created.await_count == 4:
            raise failure

    upload.projection._permission.authorize_created.side_effect = project
    with pytest.raises(OSError) as caught:
        await upload.service.upload_folder_items(40, items())
    assert caught.value is failure and await chain_snapshot(upload) == before
    upload.publish.assert_not_called()
    kinds = [
        call.kwargs["target"].resource_type for call in upload.projection._permission.rollback_created.await_args_list
    ]
    assert kinds == ["knowledge_file", "knowledge_file", "folder", "folder"]


async def test_late_authoritative_quota_unwinds_reported_zero_size_batch(folder_upload, monkeypatch):
    upload = folder_upload.upload
    before = await chain_snapshot(upload)
    # The reported zero-byte precheck passes. Only the real second input is over quota.
    folder_upload.second.write_bytes(b"x" * 10000)
    monkeypatch.setattr(module.QuotaService, "get_knowledge_space_upload_limit_bytes", AsyncMock(return_value=9999))
    with pytest.raises(SpaceFileSizeLimitError):
        await upload.service.upload_folder_items(40, items())
    upload.publish.assert_not_called()
    assert await chain_snapshot(upload) == before
    assert upload.legacy.storage.put_object_sync.call_count == 1
    assert upload.legacy.storage.remove_object_sync.call_count == 1


async def test_same_batch_content_duplicate_keeps_one_chain_and_one_dispatch(folder_upload):
    upload = folder_upload.upload
    before = await chain_snapshot(upload)
    result = await upload.service.upload_folder_items(
        40,
        [
            FolderUploadItem(file_path="opaque-document", relative_path="Root/a.txt"),
            FolderUploadItem(file_path="opaque-document", relative_path="Root/Sub/b.txt"),
        ],
    )
    assert len(result) == 2 and result[0].id == result[1].id
    assert result[1].status == 3
    upload.publish.assert_called_once()
    after = await chain_snapshot(upload)
    assert len(after["knowledgefile"]) == len(before["knowledgefile"]) + 3
    assert len(after["knowledge_document"]) == len(before["knowledge_document"]) + 1
    assert len(after["knowledge_document_version"]) == len(before["knowledge_document_version"]) + 1


async def test_dispatch_unknown_preserves_all_registered_resources_and_original_error(folder_upload):
    upload = folder_upload.upload
    before = await chain_snapshot(upload)
    failure = OSError("dispatch acknowledgement unknown")
    upload.publish.side_effect = failure
    with pytest.raises(OSError) as caught:
        await upload.service.upload_folder_items(40, items())
    assert caught.value is failure and len(folder_upload.apps) == 1
    after = await chain_snapshot(upload)
    assert len(after["knowledgefile"]) == len(before["knowledgefile"]) + 4
    assert len(after["knowledge_document"]) == len(before["knowledge_document"]) + 2
    assert len(after["knowledge_document_version"]) == len(before["knowledge_document_version"]) + 2
    upload.publish.assert_called_once()
    upload.projection._permission.rollback_created.assert_not_awaited()
    upload.legacy.storage.remove_object_sync.assert_not_called()
    upload.service.update_folder_update_time.assert_not_awaited()


async def test_saved_rules_and_full_paths_are_registered_before_timestamp_tail(folder_upload):
    upload = folder_upload.upload

    async def folder_time(path):
        assert upload.publish.call_count == 2
        assert upload.projection._permission.authorize_created.await_count == 4

    upload.service.update_folder_update_time.side_effect = folder_time
    result = await upload.service.upload_folder_items(40, items())
    assert len(result) == 2
    paths = [row.file_level_path for row in result]
    assert paths[1].startswith(paths[0] + "/") and paths[0].startswith("/")
    actual = [json.loads(row.split_rule) for row in result]
    assert actual[0]["chunk_size"] == 800 and actual[1]["excel_rule"]["slice_length"] == 44
    assert all(rule["_effective_processing"]["space_config_version"] == 3 for rule in actual)
    snapshot = await chain_snapshot(upload)
    versions = {row["knowledge_file_id"]: row for row in snapshot["knowledge_document_version"]}
    documents = {row["id"]: row for row in snapshot["knowledge_document"]}
    for row in result:
        version = versions[row.id]
        assert version["version_no"] == 1 and version["is_primary"]
        assert documents[version["document_id"]]["file_level_path"] == row.file_level_path
        assert documents[version["document_id"]]["primary_version_id"] == version["id"]
    assert [call.args[0] for call in upload.service.update_folder_update_time.await_args_list] == paths


@pytest.mark.parametrize("fail", [False, True])
async def test_selected_super_covers_entire_folder_batch_and_restores_original_identity(folder_upload, fail):
    upload = folder_upload.upload
    user = upload.context.user
    user.tenant_id, user.is_global_super = 1, True
    user._runtime_credential_reference = {**user._runtime_credential_reference, "tenant_id": 1}
    actor = PermissionActor(user_id=7, tenant_id=1, super_admin=True)
    actor_token = set_current_permission_actor(actor)
    raw = context.set_current_tenant_id(1)
    original_visible = context.get_visible_tenant_ids()

    def dispatch(**kwargs):
        assert user.tenant_id == actor.current_tenant_id == 1
        assert context.current_tenant_id.get() == context.get_current_tenant_id() == 101
        assert context.get_admin_scope_tenant_id() == 101 and context.get_is_management_api()

    upload.publish.side_effect = dispatch
    try:
        with context.management_tenant_scope(101):
            if fail:
                with pytest.raises(KeyError):
                    await upload.service.upload_folder_items(40, items("missing-input"))
                upload.publish.assert_not_called()
            else:
                await upload.service.upload_folder_items(40, items())
                assert upload.publish.call_count == 2
            assert context.current_tenant_id.get() == 1 and context.get_current_tenant_id() == 101
            assert context.get_admin_scope_tenant_id() == 101 and context.get_is_management_api()
        assert context.current_tenant_id.get() == 1 and context.get_visible_tenant_ids() == original_visible
        assert user.tenant_id == actor.current_tenant_id == 1
    finally:
        context.current_tenant_id.reset(raw)
        reset_current_permission_actor(actor_token)
