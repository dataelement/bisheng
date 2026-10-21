"""F087: a context overflow is compressed and retried, and fails cleanly when it persists.

Drives a real deepagents graph with a scripted model. The model raises the error
BishengLLM raises for a vLLM context-window rejection; the framework's
summarization middleware (outer) must see it, which only works because the
resilience middleware (inner) re-raises it instead of degrading (design decision 9).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import openai
import pytest
from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.graph import DeepAgentState
from langchain_core.exceptions import ContextOverflowError
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from bisheng.common.services.llm_error_classifier import classify_for_event
from bisheng.core.config.settings import LinsightConf
from bisheng.linsight.domain.services.context_budget import bisheng_summarization
from bisheng.linsight.domain.services.resilience_middleware import (
    _SUBAGENT_OVERFLOW_MESSAGE,
    SubagentContextOverflowMiddleware,
    build_resilience_middleware,
)
from bisheng.llm.domain.llm.context_overflow import as_context_overflow

_VLLM_TEXT = (
    "This model's maximum context length is 32768 tokens. However, you requested 0 output tokens and "
    "your prompt contains at least 32769 input tokens"
)
OVERFLOW = object()  # marker in a reply script


def _overflow() -> ContextOverflowError:
    request = httpx.Request("POST", "http://vllm.local/v1/chat/completions")
    original = openai.BadRequestError(
        _VLLM_TEXT, response=httpx.Response(400, request=request), body={"error": {"message": _VLLM_TEXT}}
    )
    overflow = as_context_overflow(original)
    overflow.__cause__ = original
    return overflow


class _ScriptedModel(BaseChatModel):
    """Agent turns come from ``replies``; summary requests (no system message) get a fixed text."""

    replies: Any = None
    summary_calls: int = 0
    agent_calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _get_ls_params(self, stop=None, **kwargs):
        # A provider of its own: bisheng_summarization() registers a harness profile
        # per provider for the whole process (design §5 gotcha 18), and other test
        # modules build deep agents from a same-named "_ScriptedModel" class.
        return {"ls_provider": "f087-overflow-flow", "ls_model_name": "scripted"}

    def bind_tools(self, *args, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if not any(isinstance(m, SystemMessage) for m in messages):
            self.summary_calls += 1
            return ChatResult(generations=[ChatGeneration(message=AIMessage("summary of earlier steps"))])
        self.agent_calls += 1
        reply = next(self.replies)
        if reply is OVERFLOW:
            raise _overflow()
        return ChatResult(generations=[ChatGeneration(message=reply)])


@tool
def fetch(page: int) -> str:
    """Fetch one page of a long document."""
    return f"第{page}页 " + "长文档内容" * 400


def _fetch_calls(n: int) -> Iterator[AIMessage]:
    for i in range(n):
        yield AIMessage("", tool_calls=[{"name": "fetch", "args": {"page": i}, "id": f"f{i}"}])


def _build(model: _ScriptedModel, conf: LinsightConf, context_window: dict):
    """The production assembly: BishengSummarizationMiddleware swapped in (P1), which
    sits INSIDE the resilience middleware (design decision 7)."""
    researcher_resilience = build_resilience_middleware(conf, is_subagent=True)
    with bisheng_summarization(model, StateBackend(), model.profile["max_input_tokens"]):
        return _create(model, conf, context_window, researcher_resilience)


def _create(model, conf, context_window, researcher_resilience):
    return create_deep_agent(
        model=model,
        tools=[fetch],
        middleware=[
            build_resilience_middleware(conf, is_subagent=False),
            SubagentContextOverflowMiddleware(researcher_resilience, context_window),
        ],
        subagents=[
            {
                "name": "general-purpose",
                "description": "researcher",
                "system_prompt": "research",
                "tools": [fetch],
                "middleware": [researcher_resilience],
            }
        ],
        state_schema=DeepAgentState,
        checkpointer=InMemorySaver(),
    )


async def _run(agent):
    return await agent.ainvoke(
        {"messages": [{"role": "user", "content": "读完这份长文档并写报告"}]},
        {"configurable": {"thread_id": "t"}, "recursion_limit": 200},
    )


def _model(script) -> _ScriptedModel:
    # A known window: the framework runs in fraction mode. Small enough that 10%
    # cannot hold the history (so compression has something to cut), large enough that
    # the chars/4 estimate never triggers proactively — the overflow path is under test.
    return _ScriptedModel(replies=iter(script), profile={"max_input_tokens": 20000})


async def test_main_overflow_is_compressed_and_retried():
    model = _model([*_fetch_calls(3), OVERFLOW, AIMessage("报告完成")])

    result = await _run(_build(model, LinsightConf(), {}))

    assert result["messages"][-1].content == "报告完成"
    assert model.summary_calls == 1  # compressed exactly once
    # The evicted history was offloaded before the summary replaced it.
    assert "/conversation_history/t.md" in result["files"]


async def test_main_overflow_after_compression_fails_as_context_overflow():
    model = _model([*_fetch_calls(3), OVERFLOW, OVERFLOW])

    with pytest.raises(ContextOverflowError) as info:
        await _run(_build(model, LinsightConf(), {}))

    # Same shape task_exec hands the classifier: TaskExecutionError(...) from e.
    try:
        raise RuntimeError("Task execution failed") from info.value
    except RuntimeError as wrapped:
        classified = classify_for_event(wrapped)
    assert (classified.error_type, classified.error_code) == ("context_overflow", 11075)
    assert model.summary_calls <= 1  # one compression per request, no loop


async def test_subagent_overflow_comes_back_as_a_tool_result():
    task_call = AIMessage(
        "",
        tool_calls=[
            {"name": "task", "args": {"description": "读第 1-50 页", "subagent_type": "general-purpose"}, "id": "t0"}
        ],
    )
    # main: delegate → (subagent: overflow, overflow) → main reads the note and finishes.
    model = _model([task_call, OVERFLOW, OVERFLOW, AIMessage("改为分段处理，报告完成")])

    result = await _run(_build(model, LinsightConf(), {"window": 32768, "source": "deployed"}))

    notes = [m for m in result["messages"] if isinstance(m, ToolMessage) and m.tool_call_id == "t0"]
    assert notes and notes[0].content == _SUBAGENT_OVERFLOW_MESSAGE
    assert notes[0].status == "success"
    assert result["messages"][-1].content == "改为分段处理，报告完成"


async def test_subagent_overflow_budget_exhausted_fails_the_task():
    def delegate(i):
        return AIMessage(
            "",
            tool_calls=[
                {
                    "name": "task",
                    "args": {"description": f"step {i}", "subagent_type": "general-purpose"},
                    "id": f"t{i}",
                }
            ],
        )

    conf = LinsightConf(max_degrade=1)
    # Two delegations, each overflowing twice: the first is absorbed, the second
    # exceeds max_degrade=1 and the task fails.
    model = _model([delegate(0), OVERFLOW, OVERFLOW, delegate(1), OVERFLOW, OVERFLOW])

    with pytest.raises(ContextOverflowError):
        await _run(_build(model, conf, {}))


async def test_resilience_reraises_overflow_on_both_graphs():
    from langchain.agents.middleware.types import ModelRequest

    async def handler(request):
        raise _overflow()

    for is_subagent in (False, True):
        middleware = build_resilience_middleware(LinsightConf(), is_subagent=is_subagent)
        request = ModelRequest(model=_model([]), messages=[], system_message=None, tools=[], state={}, runtime=None)
        with pytest.raises(ContextOverflowError):
            await middleware.awrap_model_call(request, handler)


async def test_task_failure_records_type_code_and_window(monkeypatch):
    """task_exec._handle_task_failure: output_result + the AC-15 log line."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from loguru import logger

    from bisheng.linsight.domain import task_exec as task_exec_module
    from bisheng.linsight.domain.task_exec import LinsightWorkflowTask

    task = LinsightWorkflowTask()
    task._state_manager = SimpleNamespace(set_session_version_info=AsyncMock(), push_message=AsyncMock())
    task._terminate_unfinished_tasks = AsyncMock()
    task._context_window = {"window": 32768, "source": "deployed", "usable_input": 32768}
    monkeypatch.setattr(task_exec_module.linsight_execute_utils, "persist_task_turn_message", AsyncMock())
    monkeypatch.setattr(task_exec_module, "settings", SimpleNamespace(aget_all_config=AsyncMock(return_value={})))
    session = SimpleNamespace(id="sv-1", user_id=1, status=None, output_result=None)

    try:
        raise RuntimeError("Task execution failed") from _overflow()
    except RuntimeError as wrapped:
        error = wrapped

    records: list[str] = []
    handler_id = logger.add(lambda message: records.append(str(message)), level="WARNING")
    try:
        await task._handle_task_failure(session, str(error), exc=error)
    finally:
        logger.remove(handler_id)

    assert session.output_result["error_type"] == "context_overflow"
    assert session.output_result["error_code"] == 11075
    pushed = task._state_manager.push_message.await_args.args[0].data
    assert (pushed["error_type"], pushed["error_code"]) == ("context_overflow", 11075)
    line = next(r for r in records if "task failed on context overflow" in r)
    assert "window=32768" in line and "source=deployed" in line and "reported_input_tokens=32769" in line
