"""A tool card in the chat closes only when its end frame arrives.

Two ways it never did. The knowledge tool ran its retriever through `invoke`,
which opened a *nested* tool run: a second card per search, named after the
retriever rather than the knowledge base ("知识库已被删除"), whose result is a
list of ``Document`` objects that plain ``json.dumps`` refuses — so the end frame
raised inside the callback and the card spun forever, past the end of the
session, with nothing persisted to recover it from.
"""

from __future__ import annotations

import inspect
import json

from langchain_core.documents import Document

from bisheng.api.v1.callback import AsyncGptsDebugCallbackHandler, _dump_run_log
from bisheng.tool.domain.langchain.knowledge import KnowledgeRagTool


def test_a_document_answer_still_serializes() -> None:
    """The retriever's own answer shape must not be able to suppress a frame."""

    payload = {"tool_key": "4138", "output": [Document(page_content="hello")]}

    decoded = json.loads(_dump_run_log(payload))

    assert decoded["tool_key"] == "4138"
    assert "hello" in decoded["output"][0]


def test_chinese_survives_the_frame() -> None:
    # ensure_ascii stays off: the card shows this text verbatim.
    assert "知识库" in _dump_run_log({"output": "知识库内容"})


def test_a_nameless_end_callback_is_not_fatal() -> None:
    """`on_tool_end` reads the name from kwargs, which is not always populated."""

    assert AsyncGptsDebugCallbackHandler.parse_tool_category(None) == ("", "tool")
    assert AsyncGptsDebugCallbackHandler.parse_tool_category("") == ("", "tool")


def test_a_knowledge_tool_is_still_recognised_by_its_id() -> None:
    name, category = AsyncGptsDebugCallbackHandler.parse_tool_category("knowledge_4138")
    assert (name, category) == ("4138", "knowledge")


def test_the_retriever_is_an_internal_step_not_a_tool_call() -> None:
    """Going through `invoke` re-opens the callback machinery for the inner tool.

    That is what produced the duplicate, wrongly-named card; the direct call
    keeps the retrieval invisible to whoever is watching the outer tool.
    """

    for source in (inspect.getsource(KnowledgeRagTool._run), inspect.getsource(KnowledgeRagTool._arun)):
        assert "knowledge_retriever_tool.invoke" not in source
        assert "knowledge_retriever_tool.ainvoke" not in source
    assert "knowledge_retriever_tool._run(query)" in inspect.getsource(KnowledgeRagTool._run)
    assert "knowledge_retriever_tool._arun(query)" in inspect.getsource(KnowledgeRagTool._arun)
