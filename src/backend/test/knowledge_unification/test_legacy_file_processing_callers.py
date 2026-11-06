"""T679: real old save/asave/process_one_file and rebuild consume adapter.

SQL records and actual caller bodies run; downloads/storage, permissions,
telemetry and Celery publication are isolated transport boundaries.
"""

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlmodel import Session

from bisheng.api.services import knowledge_imp
from bisheng.api.v1.schemas import FileProcessBase, KnowledgeFileProcess, KnowledgeFileReProcess
from bisheng.knowledge.application.file_processing_adapter import system_processing_defaults
from bisheng.knowledge.domain.models import knowledge as knowledge_model
from bisheng.knowledge.domain.models import knowledge_file as file_model
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.rag import knowledge_file_pipeline
from bisheng.worker.knowledge import file_worker
from test.knowledge_unification import test_file_worker as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission
processing = fixtures.processing
application = fixtures.application
files = fixtures.files


@pytest.fixture
async def legacy(files, monkeypatch, tmp_path):
    # Root conftest installs a placeholder parent before importing the old
    # service. Reload only this Service class with the actual Utils parent.
    monkeypatch.setattr(knowledge_imp, "KnowledgeUtils", knowledge_file_pipeline.KnowledgeUtils)
    module = fixtures.source_module(
        "_legacy_rules_service",
        Path(__file__).resolve().parents[2] / "bisheng/knowledge/domain/services/knowledge_service.py",
    )
    cls = module.KnowledgeService
    assert isinstance(cls, type) and cls.process_one_file.__module__ == "_legacy_rules_service"
    auth = SimpleNamespace(ensure_knowledge_write_sync=Mock(), ensure_knowledge_write_async=AsyncMock())
    monkeypatch.setattr(cls, "permission_service", auth)
    monkeypatch.setattr(cls, "audit_telemetry_service", SimpleNamespace(telemetry_new_knowledge_file=Mock()))

    @contextmanager
    def sessions():
        with Session(files.context.sync, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(knowledge_model, "get_sync_db_session", sessions)
    monkeypatch.setattr(knowledge_model, "get_async_db_session", files.context.sessions)
    monkeypatch.setattr(file_model, "get_sync_db_session", sessions)
    monkeypatch.setattr(file_model, "get_async_db_session", files.context.sessions)
    storage = Mock(bucket="tests")
    storage.get_minio_share_host.return_value = "http://private-storage.invalid"
    monkeypatch.setattr(module, "get_minio_storage_sync", lambda: storage)
    monkeypatch.setattr(module, "get_redis_client_sync", lambda: SimpleNamespace(get=lambda key: None))
    source = tmp_path / "digest_source.txt"
    source.write_text("name\nalpha\nbeta\n", encoding="utf-8")
    downloads = {"opaque-document": (str(source), "document.txt"), "opaque-table": (str(source), "sheet.csv")}
    monkeypatch.setattr(module, "file_download", lambda path: downloads[path])
    publish = Mock()
    monkeypatch.setattr(file_worker.retry_knowledge_file_celery, "delay", publish)
    defaults = system_processing_defaults(40).model_dump(mode="json")
    defaults["document"].update(chunk_size=800, force_ocr=0)
    defaults["table"]["slice_length"] = 44
    async with files.context.sessions() as session:
        root = await session.get(Knowledge, 40)
        root.processing_defaults, root.processing_config_version = defaults, 3
        original = await session.get(KnowledgeFile, 81)
        original.split_rule = FileProcessBase(knowledge_id=40, chunk_size=333, force_ocr=0).model_dump_json()
        await session.commit()
    return SimpleNamespace(cls=cls, files=files, auth=auth, storage=storage, publish=publish, defaults=defaults)


async def save(legacy, request, asynchronous):
    if asynchronous:
        return await legacy.cls.asave_knowledge_file(legacy.files.context.user, request)
    return legacy.cls.save_knowledge_file(legacy.files.context.user, request)


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_real_save_inherits_space_only_when_old_client_did_not_supply_value(legacy, asynchronous):
    request = KnowledgeFileProcess.model_validate(
        {"knowledge_id": 40, "chunk_size": None, "force_ocr": None, "file_list": [{"file_path": "opaque-document"}]}
    )
    _, failed, accepted, _ = await save(legacy, request, asynchronous)
    assert not failed and len(accepted) == 1 and accepted[0].status == 5
    actual = json.loads(accepted[0].split_rule)
    assert actual["chunk_size"] == 800 and actual["force_ocr"] == 0
    assert request.chunk_size == 1000 and request.force_ocr == 1
    async with legacy.files.context.sessions() as session:
        root = await session.get(Knowledge, 40)
        assert root.processing_defaults == legacy.defaults and root.model_config_revision == 0
        assert (await session.get(KnowledgeFile, accepted[0].id)).object_name.endswith(".txt")
    legacy.publish.assert_not_called()


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_real_download_name_selects_table_and_per_file_fields_do_not_erase_batch(legacy, asynchronous):
    request = KnowledgeFileProcess.model_validate(
        {
            "knowledge_id": 40,
            "chunk_size": 7,
            "excel_rule": {"slice_length": 20},
            "file_list": [{"file_path": "opaque-table", "excel_rule": {"header_start_row": 2, "header_end_row": 3}}],
        }
    )
    _, failed, accepted, _ = await save(legacy, request, asynchronous)
    assert not failed and len(accepted) == 1 and accepted[0].file_name == "sheet.csv"
    table = json.loads(accepted[0].split_rule)["excel_rule"]
    assert table == {"slice_length": 20, "header_start_row": 2, "header_end_row": 3, "append_header": 1}
    assert request.file_list[0].excel_rule.slice_length == 10


@pytest.mark.parametrize("length", [0, -3])
async def test_old_explicit_unbounded_table_request_reaches_real_saved_rule(legacy, length):
    request = KnowledgeFileProcess(
        knowledge_id=40, file_list=[{"file_path": "opaque-table", "excel_rule": {"slice_length": length}}]
    )
    _, _, accepted, _ = await save(legacy, request, True)
    assert json.loads(accepted[0].split_rule)["excel_rule"]["slice_length"] == 0


@pytest.mark.parametrize("size", [None, 222])
async def test_old_rebuild_keeps_actual_prior_rules_and_applies_only_new_explicit_fields(legacy, size):
    async with legacy.files.context.sessions() as session:
        original = await session.get(KnowledgeFile, 81)
    request = KnowledgeFileReProcess(knowledge_id=40, kb_file_id=81, chunk_size=size, force_ocr=None)
    updated = await legacy.cls.process_rebuild_file(original, request, 7, "operator")
    actual = json.loads(updated.split_rule)
    assert actual["chunk_size"] == (333 if size is None else size)
    assert actual["force_ocr"] == 0 and updated.id == 81 and updated.status == 5
    assert legacy.publish.call_args.args[0] == 81
    async with legacy.files.context.sessions() as session:
        assert (await session.get(Knowledge, 40)).processing_defaults == legacy.defaults
