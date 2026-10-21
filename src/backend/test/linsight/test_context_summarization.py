"""F087 P1: BishengSummarizationMiddleware replaces deepagents' summarization per task.

Covers the budgets (spec AC-21, AC-24), the summary retry/failure contract
(AC-17, AC-18), the unknown-window equivalence with the framework (AC-08) and
the harness-profile swap itself (design decision 7).
"""

from __future__ import annotations

from typing import Any

import pytest
from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.graph import DeepAgentState
from deepagents.middleware.summarization import SummarizationMiddleware, create_summarization_middleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from bisheng.common.errcode.linsight import LinsightContextCompressFailedError
from bisheng.common.services.llm_error_classifier import classify_for_event
from bisheng.linsight.domain.services.context_budget import (
    BishengSummarizationMiddleware,
    bisheng_summarization,
    estimate_tokens,
)


class _SummaryProbeModel(BaseChatModel):
    """Agent turns from ``replies``; summary calls (no system message) follow ``summaries``."""

    replies: Any = None
    summaries: Any = None
    summary_calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "summary-probe"

    def _get_ls_params(self, stop=None, **kwargs):
        return {"ls_provider": "f087-summary-probe", "ls_model_name": "probe"}

    def bind_tools(self, *args, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if not any(isinstance(m, SystemMessage) for m in messages):
            self.summary_calls += 1
            outcome = next(self.summaries)
            if isinstance(outcome, Exception):
                raise outcome
            return ChatResult(generations=[ChatGeneration(message=AIMessage(outcome))])
        return ChatResult(generations=[ChatGeneration(message=next(self.replies))])


def _model(replies=(), summaries=(), profile=None) -> _SummaryProbeModel:
    return _SummaryProbeModel(replies=iter(replies), summaries=iter(summaries), profile=profile)


# --------------------------------------------------------------------------- #
# Construction: unknown window == framework defaults; known window == budgets
# --------------------------------------------------------------------------- #


def test_unknown_window_matches_the_framework_defaults():
    model = _model()
    ours = BishengSummarizationMiddleware(model, StateBackend(), usable_input=None)
    framework = create_summarization_middleware(model, StateBackend())

    assert ours._lc_helper.trigger == framework._lc_helper.trigger
    assert ours._lc_helper.keep == framework._lc_helper.keep
    assert ours._lc_helper.trim_tokens_to_summarize == framework._lc_helper.trim_tokens_to_summarize is None
    assert ours._truncate_args_trigger == framework._truncate_args_trigger
    assert ours._truncate_args_keep == framework._truncate_args_keep


def test_known_window_budgets():
    model = _model(profile={"max_input_tokens": 100_000})
    ours = BishengSummarizationMiddleware(model, StateBackend(), usable_input=100_000)

    assert ours._lc_helper.trigger == ("fraction", 0.85)
    assert ours._lc_helper.keep == ("fraction", 0.10)
    assert ours._lc_helper.trim_tokens_to_summarize == 50_000  # summary input <= half the usable input
    assert ours.token_counter is estimate_tokens  # partial counts stay a pure estimate


def test_known_window_counts_from_the_usage_base():
    model = _model(profile={"max_input_tokens": 100_000})
    ours = BishengSummarizationMiddleware(model, StateBackend(), usable_input=100_000)
    messages = [
        HumanMessage(content="q"),
        AIMessage(
            content="",
            tool_calls=[{"name": "fetch", "args": {}, "id": "f"}],
            usage_metadata={"input_tokens": 79_990, "output_tokens": 10, "total_tokens": 80_000},
        ),
        ToolMessage(content="中文结果" * 2500, tool_call_id="f"),  # 10000 CJK chars
    ]

    total = ours._count_tokens(messages, SystemMessage(content="system"), [])

    # 80000 reported + ~10000 for the newer tool result: over 85% of 100000.
    assert total >= 90_000


def test_name_survives_the_framework_exclusion():
    ours = BishengSummarizationMiddleware(_model(), StateBackend(), usable_input=None)
    assert ours.name == "BishengSummarizationMiddleware"
    assert create_summarization_middleware(_model(), StateBackend()).name == "SummarizationMiddleware"


# --------------------------------------------------------------------------- #
# Summary failure: retry once, then fail the task (never continue on the error text)
# --------------------------------------------------------------------------- #


async def test_summary_failure_is_retried_once():
    model = _model(summaries=[RuntimeError("timeout"), "recovered summary"])
    ours = BishengSummarizationMiddleware(model, StateBackend(), usable_input=None)

    summary = await ours._acreate_summary([HumanMessage(content="old step")])

    assert summary == "recovered summary"
    assert model.summary_calls == 2


async def test_summary_failing_twice_raises():
    model = _model(summaries=[RuntimeError("timeout"), RuntimeError("timeout")])
    ours = BishengSummarizationMiddleware(model, StateBackend(), usable_input=None)

    with pytest.raises(LinsightContextCompressFailedError):
        await ours._acreate_summary([HumanMessage(content="old step")])


def test_sync_summary_failing_twice_raises():
    model = _model(summaries=[RuntimeError("x"), RuntimeError("x")])
    ours = BishengSummarizationMiddleware(model, StateBackend(), usable_input=None)

    with pytest.raises(LinsightContextCompressFailedError):
        ours._create_summary([HumanMessage(content="old step")])


# --------------------------------------------------------------------------- #
# The harness-profile swap, end to end on a real deep agent
# --------------------------------------------------------------------------- #


@tool
def fetch(page: int) -> str:
    """Fetch one page."""
    return f"第{page}页 " + "内容" * 3000


def _build(model, usable_input):
    backend = StateBackend()
    with bisheng_summarization(model, backend, usable_input):
        return create_deep_agent(
            model=model,
            tools=[fetch],
            subagents=[{"name": "general-purpose", "description": "r", "system_prompt": "r", "tools": [fetch]}],
            state_schema=DeepAgentState,
            checkpointer=InMemorySaver(),
        )


@pytest.fixture
def instances(monkeypatch):
    created: list = []
    framework_calls = {"n": 0}
    original_init = BishengSummarizationMiddleware.__init__

    def recording_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        created.append(self)

    original_awrap = SummarizationMiddleware.awrap_model_call

    async def counting_awrap(self, request, handler):
        if not isinstance(self, BishengSummarizationMiddleware):
            framework_calls["n"] += 1
        return await original_awrap(self, request, handler)

    monkeypatch.setattr(BishengSummarizationMiddleware, "__init__", recording_init)
    monkeypatch.setattr(SummarizationMiddleware, "awrap_model_call", counting_awrap)
    return created, framework_calls


async def test_main_and_subagent_get_bisheng_summarization(instances):
    created, framework_calls = instances
    delegate = AIMessage(
        "", tool_calls=[{"name": "task", "args": {"description": "d", "subagent_type": "general-purpose"}, "id": "t"}]
    )
    model = _model(
        replies=[delegate, AIMessage("sub done"), AIMessage("main done")], profile={"max_input_tokens": 50_000}
    )

    agent = _build(model, 50_000)
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "go"}]}, {"configurable": {"thread_id": "t"}}
    )

    assert result["messages"][-1].content == "main done"
    assert len(created) == 2  # one per graph
    assert all(mw._lc_helper.trim_tokens_to_summarize == 25_000 for mw in created)
    assert framework_calls["n"] == 0


async def test_compression_with_failing_summary_fails_as_compress_failed(instances):
    fetches = [AIMessage("", tool_calls=[{"name": "fetch", "args": {"page": i}, "id": f"f{i}"}]) for i in range(4)]
    # Each fetch result is ~3000 CJK tokens: the 4th request crosses 85% of 12000
    # under the CJK counter (it would not under chars/4) and compression starts.
    model = _model(
        replies=[*fetches, AIMessage("done")],
        summaries=[RuntimeError("summary model down"), RuntimeError("summary model down")],
        profile={"max_input_tokens": 12_000},
    )

    agent = _build(model, 12_000)
    with pytest.raises(LinsightContextCompressFailedError) as info:
        await agent.ainvoke({"messages": [{"role": "user", "content": "读完"}]}, {"configurable": {"thread_id": "t"}})

    try:
        raise RuntimeError("Task execution failed") from info.value
    except RuntimeError as wrapped:
        classified = classify_for_event(wrapped)
    assert (classified.error_type, classified.error_code) == ("context_compress_failed", 11076)
    assert model.summary_calls == 2


def test_assembling_outside_the_block_fails_loudly():
    model = _model()
    with bisheng_summarization(model, StateBackend(), None):
        pass  # registers the provider

    with pytest.raises(RuntimeError, match="outside bisheng_summarization"):
        create_deep_agent(model=model, tools=[], checkpointer=InMemorySaver())
