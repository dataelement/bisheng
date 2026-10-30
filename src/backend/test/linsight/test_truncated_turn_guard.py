"""Unit tests for the truncated-turn guard in LinsightModelResilienceMiddleware.

A model call cut off by ``finish_reason=length`` with NO tool call is read by
deepagents as "the agent is done". On a community beta6 run (2026-10-30) one call
reasoned for 32000 tokens with ``content_len=0``, and the task closed COMPLETED
with an earlier turn's narration as its answer. The guard re-sends once with a
nudge, then fails the main graph / degrades the subagent.

``asyncio_mode = auto`` — async tests need no decorator.
"""

import pytest
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage

from bisheng.common.services.llm_error_classifier import (
    Behavior,
    ErrorType,
    classify_behavior,
    classify_for_event,
    label_error,
)
from bisheng.linsight.domain.services.resilience_middleware import (
    _DEGRADE_MESSAGE,
    _TRUNCATED_TURN_NUDGE,
    _TRUNCATED_TURN_RETRY_LIMIT,
    LinsightModelResilienceMiddleware,
    ModelOutputTruncatedError,
    _is_truncated_tool_call,
    _is_truncated_turn,
)
from bisheng.linsight.domain.task_exec import TaskExecutionError

# The measured shape: reasoning only, nothing in content, no tool call.
_USAGE = {"input_tokens": 79225, "output_tokens": 32000, "total_tokens": 111225}


def _truncated_ai(content="", finish="length"):
    return AIMessage(content=content, response_metadata={"finish_reason": finish}, usage_metadata=dict(_USAGE))


def _ok_ai():
    return AIMessage(
        content="",
        tool_calls=[{"name": "read_file", "args": {"file_path": "/a.py"}, "id": "t", "type": "tool_call"}],
        response_metadata={"finish_reason": "tool_calls"},
    )


def _resp(msg):
    return ModelResponse(result=[msg])


def _req():
    return ModelRequest(model=None, messages=[HumanMessage(content="把 PDF 转成 Word")])


def _mw(*, is_subagent=False):
    return LinsightModelResilienceMiddleware(max_retries=3, initial_delay=0.0, is_subagent=is_subagent)


# --------------------------------------------------------------------------- detection


def test_detects_the_measured_shape():
    assert _is_truncated_turn(_resp(_truncated_ai())) is True


def test_partial_text_answer_counts_too():
    assert _is_truncated_turn(_resp(_truncated_ai(content="The document has ten"))) is True


def test_anthropic_max_tokens_counts_too():
    assert _is_truncated_turn(AIMessage(content="", response_metadata={"stop_reason": "max_tokens"})) is True


def test_finished_turn_is_not_truncated():
    assert _is_truncated_turn(_resp(AIMessage(content="done", response_metadata={"finish_reason": "stop"}))) is False


def test_disjoint_from_the_truncated_tool_call_guard():
    cut_tool_call = AIMessage(
        content="",
        tool_calls=[{"name": "write_file", "args": {"file_path": "/o/r.md"}, "id": "t", "type": "tool_call"}],
        response_metadata={"finish_reason": "length"},
    )
    assert _is_truncated_turn(cut_tool_call) is False
    assert _is_truncated_tool_call(cut_tool_call) is True


# --------------------------------------------------------------------------- behaviour


async def test_retries_once_with_nudge_then_returns_recovered():
    mw = _mw()
    captured = []

    async def handler(request):
        captured.append(list(request.messages))
        return _resp(_truncated_ai()) if len(captured) == 1 else _resp(_ok_ai())

    out = await mw.awrap_model_call(_req(), handler)
    assert len(captured) == 2
    assert captured[1][-1].content == _TRUNCATED_TURN_NUDGE
    assert len(captured[1]) == len(captured[0]) + 1
    assert out.result[0].tool_calls


async def test_main_graph_fails_instead_of_completing():
    mw = _mw()
    calls = []

    async def handler(_request):
        calls.append(1)
        return _resp(_truncated_ai())

    with pytest.raises(ModelOutputTruncatedError):
        await mw.awrap_model_call(_req(), handler)
    assert len(calls) == _TRUNCATED_TURN_RETRY_LIMIT + 1


async def test_subagent_degrades_so_the_parent_task_continues():
    mw = _mw(is_subagent=True)

    async def handler(_request):
        return _resp(_truncated_ai())

    out = await mw.awrap_model_call(_req(), handler)
    assert isinstance(out, AIMessage)
    assert out.content == _DEGRADE_MESSAGE


def test_sync_wrapper_guards_the_same_way():
    mw = _mw()
    calls = []

    def handler(_request):
        calls.append(1)
        return _resp(_truncated_ai())

    with pytest.raises(ModelOutputTruncatedError):
        mw.wrap_model_call(_req(), handler)
    assert len(calls) == _TRUNCATED_TURN_RETRY_LIMIT + 1


# --------------------------------------------------------------------------- classification


def test_error_is_classified_as_output_truncated():
    exc = ModelOutputTruncatedError("cut off")
    assert classify_behavior(exc) is Behavior.FAIL_FAST
    assert label_error(exc) is ErrorType.OUTPUT_TRUNCATED


def test_wrapped_error_still_reaches_the_truncated_card():
    try:
        try:
            raise ModelOutputTruncatedError("cut off")
        except ModelOutputTruncatedError as e:
            raise TaskExecutionError("Agent task execution failed") from e
    except TaskExecutionError as wrapper:
        assert classify_for_event(wrapper).error_type == ErrorType.OUTPUT_TRUNCATED.value
