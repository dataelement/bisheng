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
import pathlib

from langchain_core.documents import Document

from bisheng.api.v1.callback import AsyncGptsDebugCallbackHandler, _dump_run_log
from bisheng.tool.domain.langchain.knowledge import KnowledgeRagTool

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[2]


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


def test_no_citation_wrapper_reopens_a_run_for_the_retriever() -> None:
    """The citation wrappers bypass the knowledge tool and drive the retriever.

    Four copies of the same few lines — the assistant's, the workflow agent
    node's, daily chat's, and the RAG node's. Fixing only the one that was
    reported would leave the identical stray entry in the other three.
    """

    roots = [
        "bisheng/api/services/assistant_agent.py",
        "bisheng/workflow/nodes/agent/agent.py",
        "bisheng/workstation/domain/services/chat_service.py",
        "bisheng/workflow/common/knowledge.py",
    ]
    for relative in roots:
        source = (BACKEND_ROOT / relative).read_text(encoding="utf-8")
        assert "knowledge_retriever_tool.invoke" not in source, relative
        assert "knowledge_retriever_tool.ainvoke" not in source, relative


class _Socket:
    def __init__(self) -> None:
        self.frames: list[dict] = []

    async def send_json(self, frame: dict) -> None:
        self.frames.append(frame)


async def test_a_tool_called_by_a_wrapping_tool_gets_no_card_of_its_own() -> None:
    """A citation wrapper calls the real tool with its own config, so the inner
    call reports to the same handler with the wrapper as its parent run. Only
    the wrapper's card is shown; it carries the citation key the model reads."""
    from uuid import uuid4

    socket = _Socket()
    handler = AsyncGptsDebugCallbackHandler(socket, flow_id="a1", chat_id="")
    outer, inner, model = uuid4(), uuid4(), uuid4()

    await handler.on_tool_start({"name": "web_fetch"}, "{'url': 'u'}", run_id=outer, parent_run_id=model)
    await handler.on_tool_start({"name": "web_fetch"}, "{'url': 'u'}", run_id=inner, parent_run_id=outer)
    await handler.on_tool_end("page", run_id=inner, parent_run_id=outer, name="web_fetch")
    await handler.on_tool_error(RuntimeError("x"), run_id=inner, parent_run_id=outer, name="web_fetch")
    await handler.on_tool_end("page+citation_key", run_id=outer, parent_run_id=model, name="web_fetch")

    assert [(frame["type"], json.loads(frame["extra"])["run_id"]) for frame in socket.frames] == [
        ("start", outer.hex),
        ("end", outer.hex),
    ]
    assert "citation_key" in socket.frames[-1]["intermediate_steps"]
    assert handler.tool_cache == {}


async def test_sibling_tool_calls_each_get_a_card() -> None:
    from uuid import uuid4

    socket = _Socket()
    handler = AsyncGptsDebugCallbackHandler(socket, flow_id="a1", chat_id="")
    model, first, second = uuid4(), uuid4(), uuid4()

    for run_id in (first, second):
        await handler.on_tool_start({"name": "web_search"}, "q", run_id=run_id, parent_run_id=model)
        await handler.on_tool_end("hits", run_id=run_id, parent_run_id=model, name="web_search")

    assert len(socket.frames) == 4
