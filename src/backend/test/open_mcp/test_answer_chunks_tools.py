import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from bisheng.open_mcp import answer as answer_service
from bisheng.open_mcp import chunks as chunks_service
from bisheng.open_mcp.contracts import KnowledgeAnswerInput, KnowledgeChunksTextInput, KnowledgeChunksUploadInput
from bisheng.open_mcp.registry import TOOL_REGISTRY
from bisheng.open_mcp.tools import answer as answer_tools
from bisheng.open_mcp.tools import chunks as chunks_tools
from bisheng.open_mcp.upload import McpUploadError


def test_answer_model_id_falls_back_to_server_default(monkeypatch):
    monkeypatch.setattr(answer_service.settings.open_mcp, "answer_default_model_id", 42)

    assert answer_service.resolve_model_id(None) == 42
    assert answer_service.resolve_model_id(7) == 7


def test_answer_without_any_model_is_a_clear_argument_error(monkeypatch):
    monkeypatch.setattr(answer_service.settings.open_mcp, "answer_default_model_id", None)

    with pytest.raises(HTTPException) as exc:
        answer_service.resolve_model_id(None)

    assert exc.value.status_code == 400
    assert "answer_default_model_id" in exc.value.detail


def test_answer_input_limits_and_visibility():
    with pytest.raises(ValidationError):
        KnowledgeAnswerInput(query="q", knowledge_base_ids=[])
    with pytest.raises(ValidationError):
        KnowledgeAnswerInput(query="q", knowledge_base_ids=[1], top_k=51)
    tool = TOOL_REGISTRY["bisheng_knowledge_answer"]
    assert tool.scope == "knowledge:read"
    assert tool.allow_pat is True


@pytest.mark.asyncio
async def test_answer_handler_maps_declared_fields_only(monkeypatch):
    async def fake_answer(*, command):
        assert command.query == "报销期限"
        return {
            "answer": "30 天内",
            "has_context": True,
            "model_id": 42,
            "references": [{"knowledge_id": 1, "document_id": 2, "document_name": "制度.docx", "internal": "x"}],
            "debug": "x",
        }

    monkeypatch.setattr(answer_service, "answer_knowledge", fake_answer)

    result = await answer_tools.knowledge_answer(KnowledgeAnswerInput(query="报销期限", knowledge_base_ids=[1]))

    dumped = result.model_dump()
    assert dumped["answer"] == "30 天内"
    assert "debug" not in dumped
    assert "internal" not in dumped["references"][0]


def test_chunk_text_requires_a_source_and_allows_extra_metadata():
    with pytest.raises(ValidationError):
        KnowledgeChunksTextInput(knowledge_id=1, documents=[{"page_content": "x", "metadata": {}}])
    parsed = KnowledgeChunksTextInput(
        knowledge_id=1, documents=[{"page_content": "x", "metadata": {"source": "a.txt", "tag": "t"}}]
    )
    assert parsed.documents[0].metadata.model_dump() == {"source": "a.txt", "tag": "t"}


def test_chunk_upload_needs_exactly_one_file_source():
    with pytest.raises(ValidationError):
        KnowledgeChunksUploadInput(knowledge_id=1)
    with pytest.raises(ValidationError):
        KnowledgeChunksUploadInput(knowledge_id=1, content_base64="QQ==")


@pytest.fixture
def chunk_env(monkeypatch):
    monkeypatch.setattr(chunks_service, "get_open_api_operator_async", AsyncMock(return_value=SimpleNamespace(user_id=3)))
    monkeypatch.setattr(
        chunks_service.QuotaService, "get_knowledge_space_upload_limit_bytes", AsyncMock(return_value=1024)
    )


@pytest.mark.asyncio
async def test_chunk_text_joins_segments_and_hands_documents_to_importer(monkeypatch, chunk_env):
    saved = {}

    def fake_save(content, folder, name):
        saved.update(content=content, name=name)
        return "/tmp/x/" + name

    monkeypatch.setattr(chunks_service, "save_download_file", fake_save)
    knowledge, db_file = object(), SimpleNamespace(id=5)
    monkeypatch.setattr(
        chunks_service.KnowledgeService,
        "asave_knowledge_file",
        AsyncMock(return_value=(knowledge, [], [db_file], {})),
    )
    imported = MagicMock(return_value={"id": 5, "knowledge_id": 1, "file_name": "a.txt", "file_type": 1})
    monkeypatch.setattr(chunks_service, "text_knowledge", imported)

    result = await chunks_tools.chunks_text(
        KnowledgeChunksTextInput(
            knowledge_id=1,
            documents=[
                {"page_content": "第一段", "metadata": {"source": "a.txt"}},
                {"page_content": "第二段", "metadata": {"source": "a.txt"}},
            ],
        )
    )

    assert result.id == 5
    assert saved["name"] == "a.txt"
    assert saved["content"] == "第一段\n\n第二段".encode()
    called_knowledge, called_file, documents = imported.call_args.args
    assert called_knowledge is knowledge and called_file is db_file
    assert [doc.page_content for doc in documents] == ["第一段", "第二段"]
    assert documents[0].metadata["source"] == "a.txt"


@pytest.mark.asyncio
async def test_chunk_text_returns_the_failed_file_without_importing(monkeypatch, chunk_env):
    monkeypatch.setattr(chunks_service, "save_download_file", lambda *a: "/tmp/x/a.txt")
    failed = {"id": 6, "knowledge_id": 1, "file_name": "a.txt", "file_type": 1, "status": 3}
    monkeypatch.setattr(
        chunks_service.KnowledgeService, "asave_knowledge_file", AsyncMock(return_value=(object(), [failed], [], {}))
    )
    imported = MagicMock()
    monkeypatch.setattr(chunks_service, "text_knowledge", imported)

    result = await chunks_tools.chunks_text(
        KnowledgeChunksTextInput(knowledge_id=1, documents=[{"page_content": "x", "metadata": {"source": "a.txt"}}])
    )

    assert result.status == 3
    imported.assert_not_called()


@pytest.mark.asyncio
async def test_chunk_text_rejects_path_like_source_names(monkeypatch, chunk_env):
    save = MagicMock()
    monkeypatch.setattr(chunks_service, "save_download_file", save)

    with pytest.raises(McpUploadError):
        await chunks_tools.chunks_text(
            KnowledgeChunksTextInput(
                knowledge_id=1, documents=[{"page_content": "x", "metadata": {"source": "../../etc/passwd"}}]
            )
        )

    save.assert_not_called()


@pytest.mark.asyncio
async def test_chunk_upload_waits_for_parsing_through_the_sync_path(monkeypatch, chunk_env):
    @asynccontextmanager
    async def fake_prepared(source):
        yield "/tmp/staged/a.txt", "a.txt"

    monkeypatch.setattr(chunks_tools, "prepared_upload", fake_prepared)
    monkeypatch.setattr(chunks_tools.application, "current_request", lambda: object())
    sync = MagicMock(return_value=[{"id": 9, "knowledge_id": 1, "file_name": "a.txt", "file_type": 1, "status": 2}])
    monkeypatch.setattr(chunks_service.KnowledgeService, "sync_process_knowledge_file", sync)

    result = await chunks_tools.chunks_upload(
        KnowledgeChunksUploadInput(knowledge_id=1, file_name="a.txt", content_base64="QQ==", chunk_size=500)
    )

    assert result.status == 2
    req = sync.call_args.args[2]
    assert req.knowledge_id == 1
    assert req.file_list[0].file_path == "/tmp/staged/a.txt"
    assert req.chunk_size == 500
    assert sync.call_args.kwargs["upload_limit_bytes"] == 1024
    assert json.loads(result.model_dump_json())["id"] == 9
