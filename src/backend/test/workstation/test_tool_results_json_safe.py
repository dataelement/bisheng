"""Tool results persisted into the agent_answer row must be JSON-serialisable.

A knowledge / retriever tool can hand back a list that still contains raw
LangChain ``Document`` objects (``on_tool_end`` ``data["output"]`` is the bare
return value when ``response_format`` is the default ``"content"``).
``_parse_tool_results`` used to pass lists straight through, so those Documents
landed in ``events`` and the final ``json.dumps({"msg", "events"})`` at persist
time raised ``TypeError: Object of type Document is not JSON serializable`` —
which aborted the SSE stream *after* the answer was streamed (the client saw an
``IncompleteRead`` and the assistant turn was never saved).

These tests lock that anything ``_parse_tool_results`` returns is safe to
``json.dumps`` and that the Document's payload survives in a readable form.
"""

from __future__ import annotations

import json

from langchain_core.documents import Document

from bisheng.workstation.domain.services.chat_service import _parse_tool_results


def test_list_of_documents_is_json_serialisable():
    docs = [
        Document(page_content="hello", metadata={"document_id": 1, "kb_id": 7}),
        Document(page_content="world", metadata={"source": "f.pdf"}),
    ]

    results = _parse_tool_results(docs, "search_knowledge_bases")

    # The whole point: persisting must not raise.
    dumped = json.dumps({"msg": "answer", "events": [{"results": results}]}, ensure_ascii=False)
    assert "hello" in dumped and "world" in dumped


def test_document_content_and_metadata_survive():
    doc = Document(page_content="content-A", metadata={"kb_id": 42})
    [parsed] = _parse_tool_results([doc], "any_tool")

    # Must round-trip through json untouched and keep the useful fields.
    parsed = json.loads(json.dumps(parsed, ensure_ascii=False))
    flat = json.dumps(parsed, ensure_ascii=False)
    assert "content-A" in flat
    assert "42" in flat


def test_nested_document_inside_dict_is_sanitised():
    payload = {"chunks": [Document(page_content="nested")], "ok": True}
    result = _parse_tool_results(payload, "tool")
    # Nested non-serialisable objects must also be handled.
    assert "nested" in json.dumps(result, ensure_ascii=False)


def test_plain_serialisable_values_pass_through_unchanged():
    assert _parse_tool_results(["a", {"x": 1}], "t") == ["a", {"x": 1}]
    assert _parse_tool_results('[{"x": 1}]', "t") == [{"x": 1}]
    assert _parse_tool_results(None, "t") == []
    assert _parse_tool_results("", "t") == []
