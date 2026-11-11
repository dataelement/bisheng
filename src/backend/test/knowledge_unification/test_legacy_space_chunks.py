"""Actual legacy chunks endpoints register native SPACE anchors before indexing."""

from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.documents import Document

from bisheng.api.services import knowledge_imp
from bisheng.api.v1.schemas import ChunkInput
from bisheng.knowledge.application import legacy_files
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.open_endpoints.api.endpoints import filelib
from test.knowledge_unification import test_legacy_space_files as native
from test.open_api.test_chunks_string_ingest import stores as stores

store = native.store
tenant = native.tenant
business = native.business
admission = native.admission
processing = native.processing
application = native.application
files = native.files
legacy = native.legacy
upload = native.upload


@pytest.mark.parametrize("fail", [False, True])
async def test_actual_chunks_string_pipeline_complete_or_compensate_native_chain(upload, stores, monkeypatch, fail):
    monkeypatch.setattr(legacy_files, "make_legacy_space_service", lambda _request, _user: upload.service)
    monkeypatch.setattr(KnowledgeService, "upload_knowledge_file_hook", Mock())
    monkeypatch.setattr(filelib, "get_open_api_operator_async", AsyncMock(return_value=upload.context.user))
    monkeypatch.setattr(filelib, "save_download_file", lambda *_args: "opaque-document")
    monkeypatch.setattr(knowledge_imp, "delete_vector_files", Mock())
    before = await native.rows(upload)
    command = ChunkInput(
        knowledge_id=40,
        documents=[
            Document(page_content="actual caller text", metadata={"source": "document.txt"}),
        ],
    )
    if fail:
        stores.es.fail = OSError("secondary index refused")
        from bisheng.common.errcode.knowledge import KnowledgeFileFailedError

        with pytest.raises(KnowledgeFileFailedError):
            await filelib.post_string_chunks(request=None, document=command)
        assert await native.rows(upload) == before
        assert stores.milvus.texts == ["actual caller text"]
        knowledge_imp.delete_vector_files.assert_called_once()
    else:
        result = await filelib.post_string_chunks(request=None, document=command)
        assert result.data.status == 2
        assert stores.es.metadatas == stores.milvus.metadatas
        assert stores.es.metadatas[0]["document_id"] == result.data.id
        after = await native.rows(upload)
        assert [len(rows) for rows in after] == [len(rows) + 1 for rows in before]
    upload.publish.assert_not_called()


async def test_original_sync_chunks_endpoint_awaits_native_completion(upload, monkeypatch):
    from io import BytesIO

    from fastapi import UploadFile
    from sqlmodel import Session

    monkeypatch.setattr(legacy_files, "make_legacy_space_service", lambda _request, _user: upload.service)
    monkeypatch.setattr(KnowledgeService, "upload_knowledge_file_hook", Mock())
    monkeypatch.setattr(filelib, "get_open_api_operator_async", AsyncMock(return_value=upload.context.user))
    monkeypatch.setattr(filelib, "save_download_file", lambda *_args: "opaque-document")

    def parse(**kwargs):
        with Session(upload.context.sync) as session:
            row = kwargs["db_files"][0]
            assert not __import__("sqlalchemy").inspect(row).transient
            row.status = 2
            session.add(row)
            session.commit()

    monkeypatch.setattr(knowledge_imp, "process_file_task", parse)
    response = await filelib.post_chunks(
        request=None,
        knowledge_id=40,
        metadata="{}",
        file=UploadFile(BytesIO(b"source"), filename="a.txt"),
        split_mode="auto",
        separator=None,
        separator_rule=None,
        chunk_size=None,
        chunk_overlap=None,
        hierarchy_level=3,
        append_title=False,
        max_chunk_size=1000,
    )
    assert response.data.status == 2
    upload.publish.assert_not_called()
