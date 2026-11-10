"""Actual web HTTP/service rules and native initial/retained version chains."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from bisheng.common.errcode.knowledge_space import SpaceFileNotFoundError
from bisheng.core.context import tenant as context
from bisheng.knowledge.api.dependencies import get_knowledge_space_service
from bisheng.knowledge.api.endpoints import knowledge_space as api
from bisheng.knowledge.application import web_link_upload
from bisheng.knowledge.domain.models import knowledge_space_file
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.services import knowledge_space_service as module
from bisheng.knowledge.domain.services.web_link_import_service import WebLinkImportResult
from bisheng.knowledge.rag import knowledge_file_pipeline
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
async def web(upload, monkeypatch):
    monkeypatch.setattr(module, "KnowledgeUtils", knowledge_file_pipeline.KnowledgeUtils)
    monkeypatch.setattr(web_link_upload, "KnowledgeUtils", knowledge_file_pipeline.KnowledgeUtils)
    monkeypatch.setattr(
        upload.service,
        "preview_cache_key_for_split_rule",
        knowledge_file_pipeline.KnowledgeUtils.preview_cache_key_for_split_rule,
    )
    monkeypatch.setattr(knowledge_space_file, "get_async_db_session", upload.context.sessions)
    result = WebLinkImportResult(
        title="原网页 / 中文",
        markdown="# original\n\nbody\n",
        final_url="https://example.test/final",
        content_hash="a" * 64,
        content_length=18,
        html_snapshot="<html>original</html>",
    )
    fetch = AsyncMock(return_value=result)
    monkeypatch.setattr(module.KnowledgeWebLinkImportService, "fetch", fetch)
    factory, apps = upload.service.upload_application_factory, []

    def build():
        value = factory()
        apps.append(value)
        return value

    upload.service.upload_application_factory = build
    return SimpleNamespace(upload=upload, result=result, fetch=fetch, apps=apps)


async def test_web_actual_saved_space_rules_and_primary_chain_exist_before_dispatch(web):
    upload = web.upload

    def dispatch(**kwargs):
        with upload.context.sync.connect() as connection:
            import sqlalchemy as sa

            from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
            from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion

            version = (
                connection.execute(
                    sa.select(KnowledgeDocumentVersion.__table__).where(
                        KnowledgeDocumentVersion.knowledge_file_id == kwargs["file_id"]
                    )
                )
                .mappings()
                .one()
            )
            document = (
                connection.execute(
                    sa.select(KnowledgeDocument.__table__).where(KnowledgeDocument.id == version["document_id"])
                )
                .mappings()
                .one()
            )
            assert version["version_no"] == 1 and version["is_primary"]
            assert document["primary_version_id"] == version["id"]

    upload.publish.side_effect = dispatch
    row = await upload.service.import_web_link(40, "https://example.test/start")
    rule = json.loads(row.split_rule)
    assert rule["chunk_size"] == 800
    assert rule["_effective_processing"]["file_kind"] == "web"
    assert rule["_effective_processing"]["space_config_version"] == 3
    assert rule["chunk_overlap"] == 0 and len(rule["separator"]) == 11
    assert rule["separator_rule"] == ["after"] * 11
    assert row.file_name == "原网页   中文.html" and row.md5 == web.result.content_hash
    assert row.file_size == len(web.result.markdown.encode("utf-8"))
    assert row.object_name == f"original/{row.id}.md"
    assert row.user_metadata["html_snapshot_object_name"] == f"preview/{row.id}.html"
    assert len(web.apps) == 1
    upload.service._initialize_child_resource_permissions.assert_not_awaited()
    assert upload.projection._permission.authorize_created.await_count == 1
    expected_key = knowledge_file_pipeline.KnowledgeUtils.preview_cache_key_for_split_rule(
        40, web.result.final_url, rule, md5_value=web.result.content_hash
    )
    assert upload.publish.call_args.kwargs["preview_cache_key"] == expected_key


async def test_new_web_projection_failure_unwinds_owned_chain_and_attempted_objects(web):
    upload = web.upload
    before = await chain_snapshot(upload)
    failure = OSError("web projection failed")
    upload.projection._permission.authorize_created.side_effect = failure
    with pytest.raises(OSError) as caught:
        await upload.service.import_web_link(40, "https://example.test/start")
    assert caught.value is failure and await chain_snapshot(upload) == before
    upload.publish.assert_not_called()
    assert len(web.apps) == 1
    removed = [call.kwargs["object_name"] for call in upload.legacy.storage.remove_object_sync.call_args_list]
    assert len(removed) == 2 and removed[0].startswith("preview/") and removed[1].startswith("original/")


async def test_actual_web_http_returns_existing_shape(web):
    server = FastAPI()
    server.include_router(api.router, prefix="/api/v1")
    server.dependency_overrides[get_knowledge_space_service] = lambda: web.upload.service
    async with AsyncClient(transport=ASGITransport(app=server), base_url="http://offline") as client:
        response = await client.post("/api/v1/knowledge/space/40/web-links", json={"url": "https://example.test/start"})
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["knowledge_id"] == 40 and body["file_source"] == "web_link"
    assert json.loads(body["split_rule"])["_effective_processing"]["space_config_version"] == 3
    assert len(web.apps) == 1


@pytest.mark.parametrize("file_id", [81, 82])
async def test_overwrite_keeps_primary_and_historical_version_relationships(web, monkeypatch, file_id):
    upload = web.upload
    async with upload.context.sessions() as session:
        target = await session.get(KnowledgeFile, file_id)
    monkeypatch.setattr(module.KnowledgeFileDao, "get_file_by_condition", lambda **kwargs: [target])
    before = await chain_snapshot(upload)
    row = await upload.service.import_web_link(40, "https://example.test/start", overwrite=True)
    after = await chain_snapshot(upload)
    assert row.id == file_id and not web.apps
    assert before["knowledge_document"] == after["knowledge_document"]
    assert before["knowledge_document_version"] == after["knowledge_document_version"]
    assert len(before["knowledgefile"]) == len(after["knowledgefile"])
    assert [item for item in before["knowledgefile"] if item["id"] != file_id] == [
        item for item in after["knowledgefile"] if item["id"] != file_id
    ]
    actual = json.loads(row.split_rule)
    assert actual["chunk_size"] == 800 and actual["_effective_processing"]["file_kind"] == "web"
    assert row.object_name == f"original/{file_id}.md"
    upload.projection._permission.rollback_created.assert_not_awaited()
    upload.legacy.storage.remove_object_sync.assert_not_called()
    upload.publish.assert_called_once()


async def test_overwrite_broken_existing_chain_is_rejected_before_replacing_old_objects(web, monkeypatch):
    upload = web.upload
    async with upload.context.sessions() as session:
        target = await session.get(KnowledgeFile, 81)
        document = await session.get(KnowledgeDocument, 80)
        document.primary_version_id = None
        await session.commit()
    monkeypatch.setattr(module.KnowledgeFileDao, "get_file_by_condition", lambda **kwargs: [target])
    before = await chain_snapshot(upload)
    with pytest.raises(SpaceFileNotFoundError):
        await upload.service.import_web_link(40, "https://example.test/start", overwrite=True)
    assert await chain_snapshot(upload) == before
    upload.legacy.storage.put_object_sync.assert_not_called()
    upload.publish.assert_not_called()


async def test_overwrite_put_failure_keeps_existing_chain_and_never_deletes_old_keys(web, monkeypatch):
    upload = web.upload
    async with upload.context.sessions() as session:
        target = await session.get(KnowledgeFile, 81)
    monkeypatch.setattr(module.KnowledgeFileDao, "get_file_by_condition", lambda **kwargs: [target])
    before = await chain_snapshot(upload)
    failure = OSError("existing key PUT result unknown")
    upload.legacy.storage.put_object_sync.side_effect = failure
    with pytest.raises(OSError) as caught:
        await upload.service.import_web_link(40, "https://example.test/start", overwrite=True)
    assert caught.value is failure and await chain_snapshot(upload) == before
    upload.legacy.storage.remove_object_sync.assert_not_called()
    upload.projection._permission.rollback_created.assert_not_awaited()
    upload.publish.assert_not_called()
    assert not web.apps


async def test_saved_rule_change_changes_same_content_preview_cache_without_creating_another_version(web):
    upload = web.upload
    row = await upload.service.import_web_link(40, "https://example.test/start")
    first_key = upload.publish.call_args.kwargs["preview_cache_key"]
    before = await chain_snapshot(upload)
    async with upload.context.sessions() as session:
        root = await session.get(Knowledge, 40)
        defaults = {**root.processing_defaults, "document": {**root.processing_defaults["document"], "chunk_size": 900}}
        root.processing_defaults, root.processing_config_version = defaults, 4
        await session.commit()
    again = await upload.service.import_web_link(40, "https://example.test/start", overwrite=True)
    assert again.id == row.id and json.loads(again.split_rule)["chunk_size"] == 900
    assert json.loads(again.split_rule)["_effective_processing"]["space_config_version"] == 4
    assert upload.publish.call_args.kwargs["preview_cache_key"] != first_key
    after = await chain_snapshot(upload)
    assert after["knowledge_document"] == before["knowledge_document"]
    assert after["knowledge_document_version"] == before["knowledge_document_version"]


async def test_dispatch_unknown_does_not_compensate_registered_web_chain(web):
    upload = web.upload
    before = await chain_snapshot(upload)
    failure = OSError("queue acknowledgement unknown")
    upload.publish.side_effect = failure
    with pytest.raises(OSError) as caught:
        await upload.service.import_web_link(40, "https://example.test/start")
    assert caught.value is failure
    after = await chain_snapshot(upload)
    assert len(after["knowledge_document"]) == len(before["knowledge_document"]) + 1
    upload.legacy.storage.remove_object_sync.assert_not_called()
    upload.projection._permission.rollback_created.assert_not_awaited()
    assert len(web.apps) == 1


async def test_selected_super_web_dispatch_keeps_original_home_and_binds_actual_tenant(web):
    upload = web.upload
    user = upload.context.user
    user.tenant_id, user.is_global_super = 1, True
    user._runtime_credential_reference = {**user._runtime_credential_reference, "tenant_id": 1}
    actor = PermissionActor(user_id=7, tenant_id=1, super_admin=True)
    actor_token = set_current_permission_actor(actor)
    raw = context.set_current_tenant_id(1)

    def dispatch(**kwargs):
        assert context.current_tenant_id.get() == context.get_current_tenant_id() == 101
        assert context.get_admin_scope_tenant_id() == 101 and context.get_is_management_api()
        assert user.tenant_id == actor.current_tenant_id == 1

    upload.publish.side_effect = dispatch
    try:
        with context.management_tenant_scope(101):
            await upload.service.import_web_link(40, "https://example.test/start")
            assert context.current_tenant_id.get() == 1 and context.get_current_tenant_id() == 101
            assert context.get_admin_scope_tenant_id() == 101 and context.get_is_management_api()
        upload.publish.assert_called_once()
        assert user.tenant_id == actor.current_tenant_id == 1 and context.current_tenant_id.get() == 1
    finally:
        context.current_tenant_id.reset(raw)
        reset_current_permission_actor(actor_token)
