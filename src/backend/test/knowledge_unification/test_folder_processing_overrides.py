"""Actual folder registration carries temporary rules and preserves dedicated media."""

import json
from unittest.mock import Mock

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from bisheng.api.v1.schemas import FileProcessBase, KnowledgeFileOne
from bisheng.knowledge.api.dependencies import get_knowledge_space_service
from bisheng.knowledge.api.endpoints.knowledge_space import router
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.schemas.processing_settings import ProcessingOverrides
from test.knowledge_unification import test_kn_folder_upload_wiring as native

store, tenant, business, admission = native.store, native.tenant, native.business, native.admission
processing, application, files, legacy = native.processing, native.application, native.files, native.legacy
upload, folder_upload = native.upload, native.folder_upload


async def test_actual_folder_http_registers_document_table_overrides_without_saving_defaults(folder_upload):
    context = folder_upload.upload
    async with context.context.sessions() as session:
        before = await session.get(Knowledge, 40)
        defaults = before.processing_defaults
        version = before.processing_config_version
    server = FastAPI()
    server.include_router(router, prefix="/api/v1")
    server.dependency_overrides[get_knowledge_space_service] = lambda: context.service
    async with AsyncClient(transport=ASGITransport(app=server), base_url="http://native") as client:
        response = await client.post(
            "/api/v1/knowledge/space/40/folders/upload",
            json={
                "items": [item.model_dump() for item in native.items()],
                "overrides": {"document": {"chunk_size": 123}, "table": {"slice_length": 17}},
            },
        )
    assert response.status_code == 200
    actual = [json.loads(row["split_rule"]) for row in response.json()["data"]]
    assert actual[0]["chunk_size"] == 123 and actual[1]["excel_rule"]["slice_length"] == 17
    assert actual[0]["_effective_processing"]["file_kind"] == "document"
    assert actual[1]["_effective_processing"]["file_kind"] == "table"
    assert context.publish.call_count == 2
    async with context.context.sessions() as session:
        after = await session.get(Knowledge, 40)
        assert after.processing_defaults == defaults and after.processing_config_version == version


async def test_space_media_ignores_ordinary_overrides_using_actual_download_name(folder_upload, monkeypatch):
    context = folder_upload.upload
    globals_ = context.legacy.cls.prepare_one_file.__func__.__globals__
    # The opaque input and caller-facing relative path do not identify its kind.
    # The existing download returns the actual media name before rule resolution.
    download = Mock(return_value=(str(folder_upload.second), "original.mp3"))
    monkeypatch.setitem(globals_, "file_download", download)
    result = await context.service.add_file(
        40,
        ["opaque-original-body"],
        processing_overrides=ProcessingOverrides(document={"chunk_size": 123}),
    )
    actual = json.loads(result[0].split_rule)["_effective_processing"]
    assert actual["file_kind"] == "audio" and actual["effective_rule"]["chunk_size"] == 800
    assert not actual["supplied_fields_by_layer"].get("batch")
    assert download.call_count == 1


async def test_existing_prepare_default_keeps_the_original_media_override_semantics(folder_upload, monkeypatch):
    context = folder_upload.upload
    globals_ = context.legacy.cls.prepare_one_file.__func__.__globals__
    download = Mock(return_value=(str(folder_upload.second), "original.mp3"))
    monkeypatch.setitem(globals_, "file_download", download)
    async with context.context.sessions() as session:
        root = await session.get(Knowledge, 40)
    request = FileProcessBase(knowledge_id=40, chunk_size=123)
    prepared = context.legacy.cls.prepare_one_file(
        context.context.user,
        root,
        KnowledgeFileOne(file_path="opaque-original-body", excel_rule={"slice_length": 0}),
        request.model_dump(),
        processing_rule_request=request,
    )
    actual = json.loads(prepared.split_rule)["_effective_processing"]
    assert actual["file_kind"] == "audio" and actual["effective_rule"]["chunk_size"] == 123
    assert download.call_count == 1


async def test_server_owned_legacy_table_zero_keeps_unbounded_snapshot(folder_upload):
    from bisheng.knowledge.domain.schemas.processing_settings import LegacyProcessingOverrides

    context = folder_upload.upload
    result = await context.service.add_file(
        40, ["opaque-table"], processing_overrides=LegacyProcessingOverrides(table={"slice_length": 0})
    )
    actual = json.loads(result[0].split_rule)["_effective_processing"]
    assert actual["file_kind"] == "table"
    assert actual["effective_rule"]["slice_length"] == 0 and actual["effective_rule"]["legacy_unbounded"] is True


async def test_server_owned_legacy_media_keeps_its_explicit_rule(folder_upload, monkeypatch):
    from bisheng.knowledge.domain.schemas.processing_settings import LegacyProcessingOverrides

    context = folder_upload.upload
    globals_ = context.legacy.cls.prepare_one_file.__func__.__globals__
    monkeypatch.setitem(globals_, "file_download", Mock(return_value=(str(folder_upload.second), "original.mp3")))
    result = await context.service.add_file(
        40, ["opaque-media"], processing_overrides=LegacyProcessingOverrides(document={"chunk_size": 123})
    )
    actual = json.loads(result[0].split_rule)["_effective_processing"]
    assert actual["file_kind"] == "audio" and actual["effective_rule"]["chunk_size"] == 123
