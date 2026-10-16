"""POST /api/v2/filelib/chunks_string on a document knowledge base.

Before the fix, ``text_knowledge`` wrote chunks with the QA metadata layout
(``file_id``, ``knowledge_id`` as a string, ``source``, ``extra``, ``title``).
The Milvus collection of a document knowledge base uses
KNOWLEDGE_RAG_METADATA_SCHEMA, so the insert failed, and the endpoint still
answered HTTP 200 / SUCCESS with ``data.status=3``. Retrieval also filters on
``metadata.document_id``, which those chunks did not have.

These tests pin the fixed contract:
- chunk metadata has the same keys and value types as chunks of an uploaded
  text file, and file-level values come from the same function;
- Milvus and ES are initialized with KNOWLEDGE_RAG_METADATA_SCHEMA;
- a failed write returns a business error and removes the unfinished file.
"""

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.documents import Document

from bisheng.api.services import knowledge_imp
from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA
from bisheng.common.errcode.knowledge import KnowledgeFileEmptyError, KnowledgeFileFailedError
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.rag import knowledge_file_pipeline
from bisheng.knowledge.rag.knowledge_file_pipeline import KnowledgeFilePipeline
from bisheng.knowledge.rag.pipeline.loader.txt import BishengTextLoader
from bisheng.knowledge.rag.pipeline.transformer import abstract as abstract_module
from bisheng.knowledge.rag.pipeline.transformer.splitter import SplitterTransformer
from bisheng.open_endpoints.api.endpoints import filelib
from test.open_api.test_filelib_param_errors import AUTH
from test.open_api.test_filelib_param_errors import api as api

SCHEMA_KEYS = {schema.field_name for schema in KNOWLEDGE_RAG_METADATA_SCHEMA}


class FakeVectorStore:
    """Record what a Milvus / ES store receives."""

    def __init__(self, fail: Exception | None = None):
        self.fail = fail
        self.texts: list[str] = []
        self.metadatas: list[dict] = []

    def add_texts(self, texts, metadatas=None, **kwargs):
        if self.fail:
            raise self.fail
        self.texts.extend(texts)
        self.metadatas.extend(metadatas or [])
        return [str(i) for i in range(len(texts))]

    def add_documents(self, documents, **kwargs):
        return self.add_texts([d.page_content for d in documents], [d.metadata for d in documents])


def _db_file() -> KnowledgeFile:
    return KnowledgeFile(
        id=31,
        knowledge_id=128,
        file_name="faq.txt",
        user_id=12,
        updater_id=12,
        status=KnowledgeFileStatus.PROCESSING.value,
        create_time=datetime(2026, 10, 1, 8, 0, 0),
        update_time=datetime(2026, 10, 1, 9, 0, 0),
        user_metadata={},
    )


@pytest.fixture
def no_db(monkeypatch):
    """Isolate the pipeline from MySQL, the abstract LLM and the user table."""
    monkeypatch.setattr(knowledge_file_pipeline.UserDao, "get_user", lambda _uid: SimpleNamespace(user_name="svc"))
    monkeypatch.setattr(abstract_module.KnowledgeUtils, "get_knowledge_abstract_llm", lambda *_a, **_k: (None, None))
    monkeypatch.setattr(knowledge_imp.KnowledgeFileDao, "update", lambda f: f)


@pytest.fixture
def stores(monkeypatch):
    milvus, es = FakeVectorStore(), FakeVectorStore()
    init_milvus = Mock(return_value=milvus)
    init_es = Mock(return_value=es)
    monkeypatch.setattr(knowledge_imp.KnowledgeRag, "init_knowledge_milvus_vectorstore_sync", init_milvus)
    monkeypatch.setattr(knowledge_imp.KnowledgeRag, "init_knowledge_es_vectorstore_sync", init_es)
    monkeypatch.setattr(knowledge_imp.KnowledgeUtils, "ensure_milvus_schema_ready", lambda **kw: kw["vector_client"])
    return SimpleNamespace(milvus=milvus, es=es, init_milvus=init_milvus, init_es=init_es)


def _upload_reference_metadata(db_file: KnowledgeFile, tmp_path) -> dict:
    """Chunk metadata that the upload pipeline produces for the same file as a .txt upload."""
    upload = KnowledgeFilePipeline(invoke_user_id=12, db_file=db_file)
    path = tmp_path / "faq.txt"
    path.write_text("first\n\nsecond", encoding="utf-8")
    loader = BishengTextLoader(
        file_path=str(path), file_metadata=upload.file_metadata, file_extension="txt", tmp_dir=str(tmp_path)
    )
    chunks = SplitterTransformer(**upload.get_splitter_kwargs()).transform_documents(loader.load())
    return {k: v for k, v in chunks[0].metadata.items() if k in SCHEMA_KEYS}


def test_text_knowledge_writes_upload_pipeline_metadata(no_db, stores, tmp_path):
    db_file = _db_file()
    reference = _upload_reference_metadata(_db_file(), tmp_path)
    documents = [
        Document(page_content="Q: warranty?\nA: 3 years.", metadata={"source": "faq.txt", "category": "after-sales"}),
        Document(page_content="Q: repair?\nA: call 400.", metadata={"source": "faq.txt", "page": 2, "bbox": "[1]"}),
    ]

    result = knowledge_imp.text_knowledge(
        SimpleNamespace(id=128, collection_name="c", index_name="i"), db_file, documents
    )

    # Both stores are initialized with the document knowledge base schema.
    assert stores.init_milvus.call_args.kwargs["metadata_schemas"] is KNOWLEDGE_RAG_METADATA_SCHEMA
    assert stores.init_es.call_args.kwargs["metadata_schemas"] is KNOWLEDGE_RAG_METADATA_SCHEMA

    assert stores.milvus.texts == [d.page_content for d in documents]
    assert stores.es.metadatas == stores.milvus.metadatas
    for index, metadata in enumerate(stores.milvus.metadatas):
        # Same key set and value types as an uploaded file; nothing outside the schema.
        assert set(metadata) == set(reference) == SCHEMA_KEYS
        assert {k: type(v) for k, v in metadata.items()} == {k: type(v) for k, v in reference.items()}
        # File-level values come from the same function as the upload pipeline.
        for key in ("document_id", "document_name", "knowledge_id", "upload_time", "update_time"):
            assert metadata[key] == reference[key]
        for key in ("uploader", "updater", "user_metadata", "abstract"):
            assert metadata[key] == reference[key]
        assert metadata["document_id"] == 31
        assert metadata["knowledge_id"] == 128
        assert metadata["chunk_index"] == index

    first, second = stores.milvus.metadatas
    assert (first["page"], first["bbox"]) == (0, json.dumps({"chunk_bboxes": ""}))
    assert (second["page"], second["bbox"]) == (2, "[1]")
    # The caller documents are not mutated.
    assert documents[0].metadata == {"source": "faq.txt", "category": "after-sales"}

    assert result["status"] == KnowledgeFileStatus.SUCCESS.value
    assert db_file.status == KnowledgeFileStatus.SUCCESS.value


def test_text_knowledge_splits_long_documents_with_consistent_metadata(no_db, stores):
    long_text = "\n\n".join(["a" * 600, "b" * 600, "c" * 600])
    documents = [Document(page_content=long_text, metadata={"source": "long.txt", "page": 5})]

    knowledge_imp.text_knowledge(SimpleNamespace(id=128, collection_name="c", index_name="i"), _db_file(), documents)

    # One metadata row per written chunk (the old code built one row per input document).
    assert len(stores.milvus.texts) == len(stores.milvus.metadatas) == 3
    assert [m["chunk_index"] for m in stores.milvus.metadatas] == [0, 1, 2]
    assert {m["page"] for m in stores.milvus.metadatas} == {5}


def test_text_knowledge_raises_when_the_store_rejects_the_write(no_db, stores):
    stores.milvus.fail = RuntimeError("DataNotMatchException")
    db_file = _db_file()

    with pytest.raises(RuntimeError):
        knowledge_imp.text_knowledge(
            SimpleNamespace(id=128, collection_name="c", index_name="i"),
            db_file,
            [Document(page_content="x", metadata={"source": "faq.txt"})],
        )
    assert db_file.status != KnowledgeFileStatus.SUCCESS.value


def test_text_knowledge_rejects_documents_without_text(no_db, stores):
    with pytest.raises(KnowledgeFileEmptyError):
        knowledge_imp.text_knowledge(
            SimpleNamespace(id=128, collection_name="c", index_name="i"),
            _db_file(),
            [Document(page_content="", metadata={"source": "faq.txt"})],
        )
    assert stores.milvus.texts == []


# --------------------------------------------------------------------------- #
# Service: failure cleanup
# --------------------------------------------------------------------------- #
@pytest.fixture
def cleanup(monkeypatch):
    calls = SimpleNamespace(
        vectors=Mock(),
        minio=Mock(),
        projection=AsyncMock(),
        db=AsyncMock(),
    )
    from bisheng.knowledge.domain.services import knowledge_service

    monkeypatch.setattr(knowledge_service, "delete_vector_files", calls.vectors)
    monkeypatch.setattr(knowledge_service, "delete_minio_files", calls.minio)
    monkeypatch.setattr(KnowledgeService, "_project_file_ids_deletion", calls.projection)
    monkeypatch.setattr(knowledge_service.KnowledgeFileDao, "adelete_batch", calls.db)
    return calls


async def test_ingest_failure_raises_business_error_and_removes_the_file(monkeypatch, cleanup):
    from bisheng.knowledge.domain.services import knowledge_service

    monkeypatch.setattr(knowledge_service, "text_knowledge", Mock(side_effect=RuntimeError("insert failed")))
    knowledge, db_file, login_user = SimpleNamespace(id=128), _db_file(), SimpleNamespace(user_id=12)

    with pytest.raises(KnowledgeFileFailedError) as raised:
        await KnowledgeService.aingest_text_chunks(login_user, knowledge, db_file, [])

    assert "insert failed" in raised.value.message
    cleanup.vectors.assert_called_once_with([31], knowledge)
    cleanup.minio.assert_called_once_with(db_file)
    cleanup.projection.assert_awaited_once_with(login_user, [31])
    cleanup.db.assert_awaited_once_with([31])


async def test_ingest_failure_keeps_business_error_code(monkeypatch, cleanup):
    from bisheng.knowledge.domain.services import knowledge_service

    monkeypatch.setattr(knowledge_service, "text_knowledge", Mock(side_effect=KnowledgeFileEmptyError()))

    with pytest.raises(KnowledgeFileEmptyError):
        await KnowledgeService.aingest_text_chunks(SimpleNamespace(user_id=12), SimpleNamespace(id=1), _db_file(), [])
    cleanup.db.assert_awaited_once_with([31])


async def test_ingest_cleanup_continues_after_a_step_fails(monkeypatch, cleanup):
    from bisheng.knowledge.domain.services import knowledge_service

    monkeypatch.setattr(knowledge_service, "text_knowledge", Mock(side_effect=RuntimeError("boom")))
    cleanup.vectors.side_effect = RuntimeError("milvus down")
    cleanup.projection.side_effect = RuntimeError("fga down")

    with pytest.raises(KnowledgeFileFailedError):
        await KnowledgeService.aingest_text_chunks(SimpleNamespace(user_id=12), SimpleNamespace(id=1), _db_file(), [])
    cleanup.minio.assert_called_once()
    cleanup.db.assert_awaited_once_with([31])


# --------------------------------------------------------------------------- #
# Endpoint
# --------------------------------------------------------------------------- #
_BODY = {"knowledge_id": 7, "documents": [{"page_content": "x", "metadata": {"source": "faq.txt"}}]}


async def test_endpoint_write_failure_is_a_business_error(api, monkeypatch):
    monkeypatch.setattr(
        filelib.KnowledgeService,
        "aingest_text_chunks",
        AsyncMock(side_effect=KnowledgeFileFailedError(exception=RuntimeError("insert failed"))),
    )

    response = await api.client.post("/api/v2/filelib/chunks_string", json=_BODY, headers=AUTH)

    assert response.status_code == 400
    body = response.json()
    assert body["status_code"] == 10953
    assert "insert failed" in body["status_message"]


async def test_endpoint_success_returns_the_ingested_file(api, monkeypatch):
    ingest = AsyncMock(return_value={"id": 3, "status": 2})
    monkeypatch.setattr(filelib.KnowledgeService, "aingest_text_chunks", ingest)

    response = await api.client.post("/api/v2/filelib/chunks_string", json=_BODY, headers=AUTH)

    assert (response.status_code, response.json()["status_code"]) == (200, 200)
    assert response.json()["data"] == {"id": 3, "status": 2}
    documents = ingest.await_args.args[3]
    assert documents[0].metadata == {"source": "faq.txt"}


async def test_endpoint_duplicate_file_keeps_the_200_status_3_contract(api, monkeypatch):
    duplicate = {"id": 9, "status": 3, "remark": json.dumps({"new_name": "faq.txt", "old_name": "faq.txt"})}
    api.save_kf.return_value = (SimpleNamespace(id=7), [duplicate], [], None)
    ingest = AsyncMock()
    monkeypatch.setattr(filelib.KnowledgeService, "aingest_text_chunks", ingest)

    response = await api.client.post("/api/v2/filelib/chunks_string", json=_BODY, headers=AUTH)

    assert (response.status_code, response.json()["status_code"]) == (200, 200)
    assert response.json()["data"] == duplicate
    ingest.assert_not_awaited()


@pytest.mark.parametrize("knowledge_type", [1, 3])
async def test_endpoint_rejects_non_document_knowledge(api, monkeypatch, knowledge_type):
    monkeypatch.setattr(
        filelib.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=SimpleNamespace(type=knowledge_type))
    )

    response = await api.client.post("/api/v2/filelib/chunks_string", json=_BODY, headers=AUTH)

    assert (response.status_code, response.json()["status_code"]) == (400, 10962)
    api.save.assert_not_called()
    api.save_kf.assert_not_awaited()


async def test_endpoint_unknown_knowledge_is_404(api, monkeypatch):
    monkeypatch.setattr(filelib.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=None))

    response = await api.client.post("/api/v2/filelib/chunks_string", json=_BODY, headers=AUTH)

    assert response.status_code == 404
    api.save.assert_not_called()
