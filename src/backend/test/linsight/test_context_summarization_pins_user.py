"""Compression keeps the user's own messages verbatim across chained summaries.

On 106 (2026-11-16) one run compressed four times. The task instruction lived
only in the summary model's paraphrase, and the third summary restated it as
"review this prospectus for investment value"; the run then wrote a report
instead of the requested JSON. These tests let every summary drop the task and
check that each later agent turn still sees the instruction word for word.

``asyncio_mode = auto``.
"""

from __future__ import annotations

from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.graph import DeepAgentState
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from bisheng.linsight.domain.services.context_budget import BishengSummarizationMiddleware, bisheng_summarization

INSTRUCTION = (
    '只返回一个合法 JSON 对象：{"llm_patches_list": [], "llm_reviews_list": [], "llm_status_list": []}；禁止写文件。'
)
FOLLOW_UP = "补充：受限资产只用 2025 年末数据。"


class _RecordingModel(BaseChatModel):
    """Agent turns from ``replies`` (inputs recorded); summary calls (no system message) drop the task."""

    replies: Any = None
    agent_inputs: list = []
    summary_inputs: list = []

    @property
    def _llm_type(self) -> str:
        return "pin-probe"

    def _get_ls_params(self, stop=None, **kwargs):
        return {"ls_provider": "pin-probe", "ls_model_name": "probe"}

    def bind_tools(self, *args, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if not any(isinstance(m, SystemMessage) for m in messages):
            self.summary_inputs.append(list(messages))
            return ChatResult(generations=[ChatGeneration(message=AIMessage("用户在审查一份募集说明书。"))])
        self.agent_inputs.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=next(self.replies))])


@tool
def fetch(page: int) -> str:
    """Fetch one page."""
    return f"第{page}页 " + "内容" * 3000


def _agent(model, usable_input: int):
    backend = StateBackend()
    with bisheng_summarization(model):
        return create_deep_agent(
            model=model,
            tools=[fetch],
            middleware=[BishengSummarizationMiddleware(model, backend, usable_input)],
            state_schema=DeepAgentState,
            backend=backend,
            checkpointer=InMemorySaver(),
        )


def _summary_messages(inputs: list) -> list[HumanMessage]:
    return [
        m for m in inputs if isinstance(m, HumanMessage) and m.additional_kwargs.get("lc_source") == "summarization"
    ]


def _fetches(n: int) -> list[AIMessage]:
    return [AIMessage("", tool_calls=[{"name": "fetch", "args": {"page": i}, "id": f"f{i}"}]) for i in range(n)]


async def test_instruction_survives_chained_compressions():
    model = _RecordingModel(
        replies=iter([*_fetches(12), AIMessage("done")]),
        agent_inputs=[],
        summary_inputs=[],
        profile={"max_input_tokens": 12_000},
    )
    agent = _agent(model, 12_000)

    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": INSTRUCTION}]}, {"configurable": {"thread_id": "t"}}
    )

    assert result["messages"][-1].content == "done"
    assert len(model.summary_inputs) >= 2  # chained: a later summary summarises an earlier one
    compressed_turns = [inp for inp in model.agent_inputs if _summary_messages(inp)]
    assert compressed_turns
    for inp in compressed_turns:
        # The raw instruction is cut off; only the summary message can carry it.
        assert not any(isinstance(m, HumanMessage) and m.content == INSTRUCTION for m in inp)
        (summary,) = _summary_messages(inp)
        assert INSTRUCTION in summary.content
        assert summary.content.count(INSTRUCTION) == 1
        assert "用户在审查一份募集说明书。" in summary.content


async def test_every_user_message_is_pinned_once(tmp_path):
    model = _RecordingModel(
        replies=iter([*_fetches(2), AIMessage("ok"), *_fetches(8), AIMessage("done")]),
        agent_inputs=[],
        summary_inputs=[],
        profile={"max_input_tokens": 12_000},
    )
    agent = _agent(model, 12_000)
    config = {"configurable": {"thread_id": "t"}}

    await agent.ainvoke({"messages": [{"role": "user", "content": INSTRUCTION}]}, config)
    result = await agent.ainvoke({"messages": [{"role": "user", "content": FOLLOW_UP}]}, config)

    assert result["messages"][-1].content == "done"
    (summary,) = _summary_messages(model.agent_inputs[-1])
    assert summary.content.count(INSTRUCTION) == 1
    assert summary.content.count(FOLLOW_UP) == 1
    assert summary.content.index(INSTRUCTION) < summary.content.index(FOLLOW_UP)


async def test_no_user_message_cut_off_leaves_summary_unchanged():
    middleware = BishengSummarizationMiddleware(
        _RecordingModel(replies=iter(()), agent_inputs=[], summary_inputs=[], profile={"max_input_tokens": 12_000}),
        StateBackend(),
        12_000,
    )
    to_summarize, _ = middleware._partition_messages([AIMessage("a"), AIMessage("b")], 1)
    assert to_summarize == [AIMessage("a")]
    (message,) = middleware._build_new_messages_with_path("摘要", "/conversation_history/t.md")
    assert "<user_messages>" not in message.content
    assert "摘要" in message.content
