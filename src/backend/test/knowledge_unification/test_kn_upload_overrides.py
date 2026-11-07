"""Original SPACE HTTP upload uses typed batch rules and the native writer."""

import json
from unittest.mock import call

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from bisheng.knowledge.api.dependencies import get_knowledge_space_service
from bisheng.knowledge.api.endpoints import knowledge_space as api
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.schemas.processing_settings import ProcessingOverrides
from test.knowledge_unification import test_kn_upload as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission
processing = fixtures.processing
application = fixtures.application
files = fixtures.files
legacy = fixtures.legacy
upload = fixtures.upload


async def request(upload, payload):
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    app.dependency_overrides[get_knowledge_space_service] = lambda: upload.service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://offline") as client:
        return await client.post("/api/v1/knowledge/space/40/files", json=payload)


@pytest.mark.parametrize("extra", [{}, {"overrides": None}, {"overrides": {}}])
async def test_http_omitted_null_empty_inherit_saved_defaults(upload, extra):
    response = await request(upload, {"file_path": ["opaque-document"], **extra})
    assert response.status_code == 200
    row = response.json()["data"][0]
    actual = json.loads(row["split_rule"])
    assert actual["chunk_size"] == 800
    assert actual["_effective_processing"]["supplied_fields_by_layer"]["batch"] == []
    assert upload.service._require_action.await_args_list == [call("knowledge_space", 40, "upload_file")] * 2
    upload.publish.assert_called_once()


async def test_http_explicit_partial_rules_reach_native_saved_snapshot_and_v1(upload):
    response = await request(
        upload,
        {"file_path": ["opaque-document"], "overrides": {"document": {"chunk_size": 640, "force_ocr": 0}}},
    )
    assert response.status_code == 200
    row = response.json()["data"][0]
    actual = json.loads(row["split_rule"])
    assert actual["chunk_size"] == 640 and actual["force_ocr"] == 0
    snapshot = actual["_effective_processing"]
    assert set(snapshot["supplied_fields_by_layer"]["batch"]) == {"chunk_size", "force_ocr"}
    assert snapshot["space_config_version"] == 3
    assert upload.preview_rules == [(40, "opaque-document", actual)]
    async with upload.context.sessions() as session:
        saved = await session.get(KnowledgeFile, row["id"])
        assert json.loads(saved.split_rule) == actual
        versions = (
            await session.exec(
                select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.knowledge_file_id == saved.id)
            )
        ).all()
        assert len(versions) == 1 and versions[0].version_no == 1
        root = await session.get(Knowledge, 40)
        assert root.processing_defaults == upload.legacy.defaults and root.processing_config_version == 3


async def test_mixed_batch_preserves_explicit_zero_false_and_type_boundaries(upload, monkeypatch, tmp_path):
    globals_ = upload.legacy.cls.process_one_file.__func__.__globals__
    original_download = globals_["file_download"]
    table_source = tmp_path / "differenthash_sheet.csv"
    table_source.write_text("header\nsecond input\n", encoding="utf-8")
    monkeypatch.setitem(
        globals_,
        "file_download",
        lambda path: (str(table_source), "sheet.csv") if path == "opaque-table" else original_download(path),
    )
    overrides = ProcessingOverrides.model_validate(
        {"document": {"chunk_overlap": 0, "append_title": False}, "table": {"slice_length": 12, "append_header": 0}}
    )
    before = overrides.model_dump(mode="json")
    rows = await upload.service.add_file(40, ["opaque-document", "opaque-table"], processing_overrides=overrides)
    assert len(rows) == 2
    rules = [json.loads(row.split_rule) for row in rows]
    by_kind = {rule["_effective_processing"]["file_kind"]: rule for rule in rules}
    doc, table = by_kind["document"], by_kind["table"]
    assert (doc["chunk_size"], doc["chunk_overlap"], doc["append_title"]) == (800, 0, False)
    assert table["excel_rule"]["slice_length"] == 12 and table["excel_rule"]["append_header"] == 0
    assert set(doc["_effective_processing"]["supplied_fields_by_layer"]["batch"]) == {"chunk_overlap", "append_title"}
    assert set(table["_effective_processing"]["supplied_fields_by_layer"]["batch"]) == {"slice_length", "append_header"}
    assert overrides.model_dump(mode="json") == before
    assert upload.publish.call_count == 2


async def test_null_rule_fields_do_not_reset_defaults(upload):
    overrides = ProcessingOverrides.model_validate({"document": {"chunk_size": None}, "table": None})
    row = (await upload.service.add_file(40, ["opaque-document"], processing_overrides=overrides))[0]
    actual = json.loads(row.split_rule)
    assert actual["chunk_size"] == 800
    assert actual["_effective_processing"]["supplied_fields_by_layer"]["batch"] == []


async def test_folder_upload_keeps_only_original_container_action_with_explicit_rules(upload):
    async with upload.context.sessions() as session:
        root = await session.get(Knowledge, 40)
        session.add(
            KnowledgeFile(
                id=95,
                knowledge_id=40,
                tenant_id=root.tenant_id,
                user_id=7,
                file_name="destination",
                file_type=0,
                level=0,
                file_level_path="",
            )
        )
        await session.commit()
    response = await request(
        upload,
        {"file_path": ["opaque-document"], "parent_id": 95, "overrides": {"document": {"chunk_size": 600}}},
    )
    assert response.status_code == 200
    row = response.json()["data"][0]
    assert row["file_level_path"] == "/95"
    assert json.loads(row["split_rule"])["chunk_size"] == 600
    assert upload.service._require_action.await_args_list == [call("folder", 95, "upload_file")] * 2


@pytest.mark.parametrize(
    "overrides",
    [
        {"unknown": 1},
        {"document": {"chunk_size": True}},
        {"document": {"chunk_size": 0}},
        {"document": {"force_ocr": True}},
        {"document": {"force_ocr": 0.0}},
        {"table": {"append_header": True}},
        {"document": {"private_effective_processing": {}}},
        {"table": {"slice_length": 0}},
        {"table": {"header_start_row": -1}},
        {"model_id": 999},
    ],
)
async def test_invalid_public_override_refused_before_actual_business_or_queue(upload, overrides):
    response = await request(upload, {"file_path": ["opaque-document"], "overrides": overrides})
    assert response.status_code == 422
    upload.service._require_action.assert_not_awaited()
    upload.publish.assert_not_called()
    upload.legacy.storage.put_object_sync.assert_not_called()


async def test_explicit_rules_keep_original_compensation_after_version_registration(upload):
    async with upload.context.sessions() as session:
        before_files = set((await session.exec(select(KnowledgeFile.id))).all())
        before_versions = set((await session.exec(select(KnowledgeDocumentVersion.id))).all())
    permission = upload.projection._permission
    permission.authorize_created.side_effect = RuntimeError("permission failed")
    with pytest.raises(RuntimeError, match="permission failed"):
        await upload.service.add_file(
            40, ["opaque-document"], processing_overrides=ProcessingOverrides(document={"chunk_size": 600})
        )
    permission.rollback_created.assert_awaited_once()
    upload.publish.assert_not_called()
    async with upload.context.sessions() as session:
        assert set((await session.exec(select(KnowledgeFile.id))).all()) == before_files
        assert set((await session.exec(select(KnowledgeDocumentVersion.id))).all()) == before_versions
