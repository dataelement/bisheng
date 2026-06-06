import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


def _load_knowledge_utils(monkeypatch):
    base_module = ModuleType("bisheng.common.services.base")

    class BaseService:
        pass

    base_module.BaseService = BaseService
    monkeypatch.setitem(sys.modules, "bisheng.common.services.base", base_module)

    module_path = (
        Path(__file__).resolve().parents[2]
        / "bisheng/knowledge/domain/services/knowledge_utils.py"
    )
    spec = importlib.util.spec_from_file_location(
        "knowledge_utils_retry_file_category_under_test",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.KnowledgeUtils


@pytest.mark.asyncio
async def test_process_retry_files_clears_encoding_when_file_category_selected(monkeypatch):
    KnowledgeUtils = _load_knowledge_utils(monkeypatch)
    db_file = SimpleNamespace(
        id=11,
        knowledge_id=7,
        object_name="files/11.pdf",
        file_name="旧报告.pdf",
        file_encoding="SGGF-STD-PP-20260500000001",
        file_level_path="",
    )
    input_file = {
        "id": 11,
        "object_name": "files/11.pdf",
        "file_path": "/tmp/new.pdf",
        "split_rule": json.dumps({"file_category_code": "RPT"}),
        "file_level_path": "",
        "remark": "",
    }
    login_user = SimpleNamespace(user_id=3, user_name="tester")

    monkeypatch.setattr(
        "bisheng.core.storage.minio.minio_manager.get_minio_storage",
        AsyncMock(return_value=SimpleNamespace()),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.async_update",
        AsyncMock(side_effect=lambda file: file),
    )

    fake_file_worker = SimpleNamespace(
        retry_knowledge_file_celery=SimpleNamespace(delay=Mock()),
    )
    fake_worker_module = ModuleType("bisheng.worker")
    fake_worker_knowledge_module = ModuleType("bisheng.worker.knowledge")
    fake_worker_knowledge_module.file_worker = fake_file_worker
    monkeypatch.setitem(sys.modules, "bisheng.worker", fake_worker_module)
    monkeypatch.setitem(sys.modules, "bisheng.worker.knowledge", fake_worker_knowledge_module)

    await KnowledgeUtils.process_retry_files([db_file], {11: input_file}, login_user)

    assert db_file.file_encoding is None


@pytest.mark.asyncio
async def test_process_retry_files_clears_encoding_when_business_domain_selected(monkeypatch):
    KnowledgeUtils = _load_knowledge_utils(monkeypatch)
    db_file = SimpleNamespace(
        id=11,
        knowledge_id=7,
        object_name="files/11.pdf",
        file_name="旧报告.pdf",
        file_encoding="SGGF-STD-PP-20260500000001",
        file_level_path="",
    )
    input_file = {
        "id": 11,
        "object_name": "files/11.pdf",
        "file_path": "/tmp/new.pdf",
        "split_rule": json.dumps({"business_domain_code": "IT"}),
        "file_level_path": "",
        "remark": "",
    }
    login_user = SimpleNamespace(user_id=3, user_name="tester")

    monkeypatch.setattr(
        "bisheng.core.storage.minio.minio_manager.get_minio_storage",
        AsyncMock(return_value=SimpleNamespace()),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.async_update",
        AsyncMock(side_effect=lambda file: file),
    )

    fake_file_worker = SimpleNamespace(
        retry_knowledge_file_celery=SimpleNamespace(delay=Mock()),
    )
    fake_worker_module = ModuleType("bisheng.worker")
    fake_worker_knowledge_module = ModuleType("bisheng.worker.knowledge")
    fake_worker_knowledge_module.file_worker = fake_file_worker
    monkeypatch.setitem(sys.modules, "bisheng.worker", fake_worker_module)
    monkeypatch.setitem(sys.modules, "bisheng.worker.knowledge", fake_worker_knowledge_module)

    await KnowledgeUtils.process_retry_files([db_file], {11: input_file}, login_user)

    assert db_file.file_encoding is None
