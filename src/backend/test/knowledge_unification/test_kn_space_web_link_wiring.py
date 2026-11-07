"""Actual web HTTP/service rules and native initial/retained version chains."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.domain.models import knowledge_space_file
from bisheng.knowledge.domain.services import knowledge_space_service as module
from bisheng.knowledge.domain.services.web_link_import_service import WebLinkImportResult
from bisheng.knowledge.rag import knowledge_file_pipeline
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
