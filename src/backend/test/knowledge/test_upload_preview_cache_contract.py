"""Preview edits must be consumed by the worker after trusted upload."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.documents import Document

from bisheng.api.v1.schemas import KnowledgeFileProcess, UpdatePreviewFileChunk
from bisheng.knowledge.domain.services import knowledge_service as service
from bisheng.knowledge.domain.services.preview_source_service import PreviewSource, PreviewSourceService
from bisheng.knowledge.rag.pipeline.transformer.preview_cache import PreviewCacheTransformer


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.hashes = {}

    async def aset(self, key, value, **kwargs):
        self.values[key] = value

    async def aget(self, key):
        return self.values.get(key)

    async def ahset(self, name, mapping=None, key=None, value=None):
        bucket = self.hashes.setdefault(name, {})
        bucket.update({str(k): v for k, v in mapping.items()} if mapping else {str(key): value})

    async def ahget(self, name, key):
        return self.hashes.get(name, {}).get(str(key))

    async def ahgetall(self, name):
        return self.hgetall(name)

    def hgetall(self, name):
        return self.hashes.get(name, {}).copy()


@pytest.mark.parametrize(
    "excel_rule",
    [None, {"slice_length": 3, "header_start_row": 2, "header_end_row": 3, "append_header": 0}],
    ids=["default-excel", "custom-excel"],
)
async def test_preview_edit_survives_trusted_upload_for_worker(monkeypatch, tmp_path, excel_rule):
    from bisheng.core.cache import utils as cache_utils
    from bisheng.knowledge.rag import preview_file_pipeline

    # Shared conftest replaces KnowledgeUtils at import time; load the real class
    # privately and combine it with the real service without changing global modules.
    spec = importlib.util.spec_from_file_location(
        "contract_knowledge_utils", Path(service.__file__).with_name("knowledge_utils.py")
    )
    utils = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(utils)

    class ContractService(utils.KnowledgeUtils, service.KnowledgeService):
        pass

    monkeypatch.setattr(service, "KnowledgeUtils", utils.KnowledgeUtils)
    from bisheng.knowledge.rag.pipeline.transformer import preview_cache

    monkeypatch.setattr(preview_cache, "KnowledgeUtils", utils.KnowledgeUtils)
    redis = FakeRedis()
    monkeypatch.setattr(utils, "get_redis_client", AsyncMock(return_value=redis))
    monkeypatch.setattr(utils, "get_redis_client_sync", lambda: redis)
    monkeypatch.setattr(service, "get_redis_client", AsyncMock(return_value=redis))
    user = SimpleNamespace(user_id=7, tenant_id=2)
    knowledge = SimpleNamespace(id=3, user_id=7, tenant_id=2)
    monkeypatch.setattr(service.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=knowledge))
    monkeypatch.setattr(service.KnowledgeService.permission_service, "ensure_knowledge_write_async", AsyncMock())
    monkeypatch.setattr(service.KnowledgeService, "ensure_knowledge_upload_tenant_consistency", Mock())
    monkeypatch.setattr(service.KnowledgeFileDao, "aget_user_upload_total_file_size", AsyncMock(return_value=0))
    source = PreviewSource("temporary", "server.xlsx", "data.xlsx", "issued-url", "issued-url")
    monkeypatch.setattr(PreviewSourceService, "resolve", AsyncMock(return_value=source))
    stream = SimpleNamespace(close=Mock(), release_conn=Mock())
    monkeypatch.setattr(
        service, "get_minio_storage_sync", lambda: SimpleNamespace(download_object_sync=Mock(return_value=stream))
    )
    monkeypatch.setattr(cache_utils, "save_download_file", lambda *args: str(tmp_path / "server.xlsx"))
    minio = SimpleNamespace(
        clear_minio_share_host=lambda url: url, tmp_bucket="temporary", object_exists=AsyncMock(return_value=False)
    )
    monkeypatch.setattr(service, "get_minio_storage", AsyncMock(return_value=minio))

    class FakePipeline:
        def __init__(self, **kwargs):
            self.loader = None

        async def arun(self):
            return SimpleNamespace(documents=[Document(page_content="original", metadata={})])

    monkeypatch.setattr(preview_file_pipeline, "PreviewFilePipeline", FakePipeline)
    db_file = SimpleNamespace(id=5, status=2, file_size=1)
    process = Mock(return_value=db_file)
    monkeypatch.setattr(service.KnowledgeService, "process_one_file", process)
    req = KnowledgeFileProcess(
        knowledge_id=3, file_list=[{"file_path": "issued-url", "preview_upload_ref": "ref", "excel_rule": excel_rule}]
    )

    _, _, chunks, _ = await ContractService.get_preview_file_chunk(None, user, req)
    assert chunks[0].text == "original"
    preview_key = await ContractService.async_resolve_preview_cache_key(3, "issued-url")
    await ContractService.update_preview_file_chunk(
        None,
        user,
        UpdatePreviewFileChunk(knowledge_id=3, file_path="issued-url", chunk_index=0, text="edited", bbox=""),
    )
    _, failed, processed, worker_keys = await ContractService.asave_knowledge_file(user, req, trusted_uploads_only=True)
    assert failed == [] and processed == [db_file]
    assert process.call_args.kwargs["trusted_source"] is source
    assert worker_keys == [preview_key]
    docs = PreviewCacheTransformer(worker_keys[0], {}).transform_documents([Document(page_content="fallback")])
    assert len(docs) == 1
    assert utils.KnowledgeUtils.split_chunk_metadata(docs[0].page_content) == "edited"
