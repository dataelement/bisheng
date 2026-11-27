"""F002 coverage AC: AC-11, AC-12, AC-14; new replies use registered citations only."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.documents import Document

from bisheng.citation.domain.schemas.citation_schema import (
    CitationRegistryItemSchema,
    CitationType,
    RagCitationPayloadSchema,
)
from bisheng.worker.workflow import redis_callback as module


@pytest.fixture
def output(monkeypatch):
    callback = module.RedisCallback.__new__(module.RedisCallback)
    callback.chat_id, callback.workflow_id, callback.user_id = "new-chat", "workflow", 7
    callback.source, callback.create_session = "api", True
    items = [
        CitationRegistryItemSchema(
            citationId="knowledgesearch_test",
            type=CitationType.RAG,
            sourcePayload=RagCitationPayloadSchema(knowledgeId=40, documentId=41),
        )
    ]
    callback._finalize_citation_items = Mock(return_value=items)
    callback._remember_pending_input = Mock()
    callback.send_chat_response = Mock()
    written = []

    def save(row):
        row.id = 123
        written.append(row)
        return row

    monkeypatch.setattr(module.ChatMessageDao, "insert_one", save)
    citations = Mock()
    monkeypatch.setattr(module, "save_message_citations_sync", citations)
    tasks = Mock(side_effect=AssertionError("new replies must not schedule keyword extraction"))
    monkeypatch.setattr(module.thread_pool, "submit", tasks)
    monkeypatch.setattr(
        module, "settings", SimpleNamespace(get_minio_conf=lambda: SimpleNamespace(sharepoint="files.example"))
    )
    data = SimpleNamespace(
        source_documents=[
            Document(page_content="source", metadata={"knowledge_id": 40, "document_id": 41, "bbox": "{}"})
        ],
        citation_registry_items=items,
        files=[],
        msg="Answer with registered citation",
    )
    data.dict = lambda **kwargs: {"msg": data.msg}
    return SimpleNamespace(callback=callback, data=data, items=items, citations=citations, written=written, tasks=tasks)


@pytest.mark.parametrize("method", ["on_output_msg", "on_stream_over", "on_output_choose", "on_output_input"])
def test_all_new_output_paths_preserve_citations_without_old_file_button_or_tasks(output, method):
    getattr(output.callback, method)(output.data)
    assert len(output.written) == 1
    assert output.written[0].source == 0
    response = output.callback.send_chat_response.call_args.args[0]
    assert response.source == 0 and response.message_id == 123
    output.callback._finalize_citation_items.assert_called_once()
    output.citations.assert_called_once_with(message_id=123, items=output.items, chat_id="new-chat", flow_id="workflow")
    output.tasks.assert_not_called()


@pytest.mark.parametrize("source", [2, 3, 4])
def test_non_file_source_display_semantics_are_preserved_without_extraction(output, monkeypatch, source):
    monkeypatch.setattr(module, "sync_judge_source", lambda *args: (source, {}))
    output.callback.on_output_msg(output.data)
    assert output.written[0].source == source
    output.tasks.assert_not_called()
