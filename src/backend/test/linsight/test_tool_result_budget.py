"""F087 P1: one tool result may take at most 10% of the usable input (spec AC-19, AC-20)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.graph import DeepAgentState
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from bisheng.linsight.domain.services.context_budget import ToolResultBudgetMiddleware, estimate_text_tokens

USABLE_INPUT = 20_000  # → 2000-token budget per result


class _Scripted(BaseChatModel):
    replies: Any = None

    @property
    def _llm_type(self) -> str:
        return "result-budget-scripted"

    def bind_tools(self, *args, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        assert any(isinstance(m, SystemMessage) for m in messages)
        return ChatResult(generations=[ChatGeneration(message=next(self.replies))])


@tool
def big_search(query: str) -> str:
    """Return a long Chinese result: 3000 CJK characters (~3000 tokens)."""
    return "检索结果" * 750


@tool
def small_search(query: str) -> str:
    """Return a short result."""
    return "命中 3 条"


def _run_agent(tool_name: str):
    backend = StateBackend()
    model = _Scripted(
        replies=iter(
            [AIMessage("", tool_calls=[{"name": tool_name, "args": {"query": "q"}, "id": "c1"}]), AIMessage("done")]
        )
    )
    agent = create_deep_agent(
        model=model,
        tools=[big_search, small_search],
        middleware=[ToolResultBudgetMiddleware(backend, USABLE_INPUT)],
        state_schema=DeepAgentState,
        backend=backend,
        checkpointer=InMemorySaver(),
    )
    return agent.invoke({"messages": [{"role": "user", "content": "go"}]}, {"configurable": {"thread_id": "t"}})


def _tool_message(result) -> ToolMessage:
    return next(m for m in result["messages"] if isinstance(m, ToolMessage) and m.tool_call_id == "c1")


def test_result_over_budget_is_offloaded():
    # 3000 CJK chars is only 3000 characters: under the framework's own
    # 80000-character threshold, so only the CJK-aware budget catches it.
    result = _run_agent("big_search")

    message = _tool_message(result)
    assert "/large_tool_results/c1" in message.content
    assert estimate_text_tokens(message.content) < 2000
    assert "/large_tool_results/c1" in result["files"]


def test_result_within_budget_is_untouched():
    result = _run_agent("small_search")

    assert _tool_message(result).content == "命中 3 条"
    assert not any(path.startswith("/large_tool_results/") for path in result.get("files", {}))


def _read_request(path="/uploads/report.md"):
    return SimpleNamespace(tool_call={"name": "read_file", "args": {"file_path": path}, "id": "r1"}, runtime=None)


def test_read_file_page_is_clipped_not_offloaded():
    middleware = ToolResultBudgetMiddleware(StateBackend(), USABLE_INPUT)
    page = ToolMessage(content="正文" * 2000, tool_call_id="r1", name="read_file")  # 4000 CJK chars

    clipped = middleware.wrap_tool_call(_read_request(), lambda request: page)

    assert estimate_text_tokens(clipped.content) <= 2000
    assert "offset" in clipped.content and "/uploads/report.md" in clipped.content
    assert clipped.content.startswith("正文正文")


def test_small_read_file_page_is_untouched():
    middleware = ToolResultBudgetMiddleware(StateBackend(), USABLE_INPUT)
    page = ToolMessage(content="短内容", tool_call_id="r1", name="read_file")

    assert middleware.wrap_tool_call(_read_request(), lambda request: page) is page


def test_write_file_result_is_never_touched():
    middleware = ToolResultBudgetMiddleware(StateBackend(), USABLE_INPUT)
    message = ToolMessage(content="已写入" * 2000, tool_call_id="w1", name="write_file")
    request = SimpleNamespace(tool_call={"name": "write_file", "args": {}, "id": "w1"}, runtime=None)

    assert middleware.wrap_tool_call(request, lambda r: message) is message


def test_factory_mounts_the_budget_only_for_a_known_window():
    from bisheng.linsight.domain.services.agent_factory import _result_budget

    assert _result_budget(StateBackend(), {"usable_input": None}) == []
    (mounted,) = _result_budget(StateBackend(), {"usable_input": 50_000})
    assert isinstance(mounted, ToolResultBudgetMiddleware)
