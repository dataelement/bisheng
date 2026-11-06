"""Daily attachments must reach the model with retained, readable image URLs."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.documents import Document

from bisheng.chat_session.domain.services.workflow_file_service import WorkflowFileService
from bisheng.common.errcode.workstation import ChatFileParseError
from bisheng.workstation.domain.services import chat_service


async def test_daily_parser_receives_the_owned_image_storage_context(monkeypatch):
    storage = object()
    factory = MagicMock(return_value=storage)
    parse = AsyncMock(return_value="![image](/api/v1/chat/daily/files/image/content)")
    monkeypatch.setattr(WorkflowFileService, "image_storage", factory)
    monkeypatch.setattr(chat_service, "get_file_content", parse)
    result = await chat_service._extract_doc_text(
        "/tmp/source.pdf",
        "source.pdf",
        7,
        chat_id="daily",
        source_url="/bisheng/chat/7/source.pdf",
        tenant_id=3,
    )
    assert result.startswith("![image](/api/v1/chat/daily/")
    assert factory.call_args.kwargs | {"run_id": "ignored"} == {
        "chat_id": "daily",
        "user_id": 7,
        "tenant_id": 3,
        "workflow_id": "",
        "run_id": "ignored",
        "node_id": "daily-attachment",
        "source_url": "/bisheng/chat/7/source.pdf",
        "file_name": "source.pdf",
    }
    assert parse.await_args.kwargs["image_storage"] is storage


async def test_temp_pipeline_keeps_images_and_uses_the_retained_storage(monkeypatch):
    storage = object()
    pipeline = MagicMock()
    pipeline.return_value.arun = AsyncMock(
        return_value=SimpleNamespace(
            documents=[Document(page_content="![image](/api/v1/chat/daily/files/image/content)")]
        )
    )
    monkeypatch.setattr("bisheng.knowledge.rag.temp_file_pipeline.TempFilePipeline", pipeline)
    monkeypatch.setattr(
        chat_service.knowledge_imp.KnowledgeUtils, "chunk2promt", staticmethod(lambda body, _: body), raising=False
    )
    result = await chat_service.get_file_content("/tmp/source.pdf", "source.pdf", 7, image_storage=storage)
    assert pipeline.call_args.kwargs["image_storage"] is storage
    assert pipeline.call_args.kwargs["file_rule"].retain_images == 1
    assert "/tmp/" not in result


async def test_storage_failure_is_reported_instead_of_returning_a_local_image_path(monkeypatch):
    monkeypatch.setattr(WorkflowFileService, "image_storage", MagicMock(side_effect=OSError("storage unavailable")))
    parse = AsyncMock()
    monkeypatch.setattr(chat_service, "get_file_content", parse)
    with pytest.raises(ChatFileParseError) as caught:
        await chat_service._extract_doc_text("/tmp/source.pdf", "source.pdf", 7, chat_id="daily")
    assert caught.value.kwargs["filename"] == "source.pdf"
    parse.assert_not_awaited()


async def test_live_daily_file_processing_binds_each_document_to_the_new_conversation(monkeypatch):
    extract = AsyncMock(return_value="retained document")
    monkeypatch.setattr(chat_service, "_extract_doc_text", extract)
    monkeypatch.setattr(chat_service, "async_file_download", AsyncMock(return_value=("/tmp/source.pdf", "source.pdf")))
    monkeypatch.setattr(
        chat_service, "_annotate_agent_files_with_video_covers", AsyncMock(side_effect=lambda files, _: files)
    )
    files = [{"filepath": "/bisheng/chat/7/source.pdf"}]
    await chat_service._process_agent_files(
        SimpleNamespace(files=files),
        SimpleNamespace(visual=False),
        SimpleNamespace(user_id=7, tenant_id=3),
        SimpleNamespace(maxTokens=1000),
        conversation_id="new-daily",
    )
    assert extract.call_args.kwargs == {"chat_id": "new-daily", "source_url": files[0]["filepath"], "tenant_id": 3}
