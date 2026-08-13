"""Unit tests for the incomplete-stream guard in LinsightModelResilienceMiddleware.

A provider that closes the SSE stream mid-turn raises nothing: langchain hands back
whatever it accumulated. When that partial message carries no tool call, deepagents
reads it as "the agent is done" — which is how a 114 run (2026-08-13) with 3 of its
5 steps still pending completed "successfully", its final answer being the one line
of narration the model had emitted before the stream died.

The guard detects that shape, re-sends the call a bounded number of times, and — if
it keeps coming back incomplete — fails the main graph / degrades the subagent
instead of passing the cut-off narration off as an answer.

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
    _INCOMPLETE_STREAM_RETRY_LIMIT,
    IncompleteStreamError,
    LinsightModelResilienceMiddleware,
    _is_incomplete_stream_response,
)
from bisheng.linsight.domain.task_exec import TaskExecutionError

# The exact shape observed on 114: metadata from the first chunk, one line of
# narration, no finish_reason, no usage, no tool call.
_METADATA = {"model_name": "grok4.6", "model_provider": "openai"}


def _incomplete_ai(content="正在撰写完整参数清单与 D2 数据表。"):
    return AIMessage(
        content=content,
        response_metadata=dict(_METADATA),
        usage_metadata={"input_tokens": 0, "output_tokens": 69, "total_tokens": 69},
    )


def _ok_ai(content="done"):
    return AIMessage(
        content=content,
        response_metadata={**_METADATA, "finish_reason": "stop"},
        usage_metadata={"input_tokens": 147642, "output_tokens": 2423, "total_tokens": 150065},
    )


def _resp(msg):
    return ModelResponse(result=[msg])


def _req():
    return ModelRequest(model=None, messages=[HumanMessage(content="写一份报告")])


def _mw(*, is_subagent=False):
    return LinsightModelResilienceMiddleware(max_retries=3, initial_delay=0.0, is_subagent=is_subagent)


# --------------------------------------------------------------------------- detection


def test_detects_the_114_shape():
    assert _is_incomplete_stream_response(_resp(_incomplete_ai())) is True


def test_detect_accepts_bare_aimessage():
    assert _is_incomplete_stream_response(_incomplete_ai()) is True


def test_completed_stream_is_not_incomplete():
    assert _is_incomplete_stream_response(_resp(_ok_ai())) is False


def test_anthropic_stop_reason_counts_as_finished():
    ai = AIMessage(content="done", response_metadata={**_METADATA, "stop_reason": "end_turn"})
    assert _is_incomplete_stream_response(_resp(ai)) is False


def test_usage_alone_proves_the_stream_completed():
    """A provider that omits finish_reason but reported real input usage is done."""
    ai = AIMessage(
        content="done",
        response_metadata=dict(_METADATA),
        usage_metadata={"input_tokens": 1234, "output_tokens": 56, "total_tokens": 1290},
    )
    assert _is_incomplete_stream_response(_resp(ai)) is False


def test_stream_cut_mid_tool_call_is_out_of_scope():
    """Deliberately excluded: the graph keeps running, so it is never silent."""
    ai = AIMessage(
        content="",
        tool_calls=[{"name": "write_file", "args": {"file_path": "/output/r.md"}, "id": "t", "type": "tool_call"}],
        response_metadata=dict(_METADATA),
    )
    assert _is_incomplete_stream_response(_resp(ai)) is False


def test_synthetic_message_without_provider_metadata_is_ignored():
    """A degraded/synthetic AIMessage is not a provider stream — never retried."""
    assert _is_incomplete_stream_response(AIMessage(content=_DEGRADE_MESSAGE)) is False


# --------------------------------------------------------------------------- behaviour


async def test_retries_then_returns_the_recovered_response():
    mw = _mw()
    calls = []

    async def handler(_request):
        calls.append(1)
        return _resp(_incomplete_ai()) if len(calls) == 1 else _resp(_ok_ai())

    out = await mw.awrap_model_call(_req(), handler)
    assert len(calls) == 2  # exactly one retry
    assert out.result[0].content == "done"


async def test_main_graph_fails_instead_of_passing_off_a_cut_off_answer():
    mw = _mw()
    calls = []

    async def handler(_request):
        calls.append(1)
        return _resp(_incomplete_ai())

    with pytest.raises(IncompleteStreamError):
        await mw.awrap_model_call(_req(), handler)
    assert len(calls) == _INCOMPLETE_STREAM_RETRY_LIMIT + 1  # initial + bounded retries


async def test_subagent_degrades_so_the_parent_task_continues():
    mw = _mw(is_subagent=True)

    async def handler(_request):
        return _resp(_incomplete_ai())

    out = await mw.awrap_model_call(_req(), handler)
    assert isinstance(out, AIMessage)
    assert out.content == _DEGRADE_MESSAGE


async def test_retry_budget_is_separate_from_the_exception_budget():
    """A transient exception first must not eat the incomplete-stream allowance."""
    mw = LinsightModelResilienceMiddleware(max_retries=1, initial_delay=0.0)
    calls = []

    async def handler(_request):
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError("transient")
        return _resp(_incomplete_ai()) if len(calls) <= 2 else _resp(_ok_ai())

    out = await mw.awrap_model_call(_req(), handler)
    assert len(calls) == 3  # exception retry + incomplete retry, both spent
    assert out.result[0].content == "done"


def test_sync_wrapper_guards_the_same_way():
    mw = _mw()
    calls = []

    def handler(_request):
        calls.append(1)
        return _resp(_incomplete_ai()) if len(calls) == 1 else _resp(_ok_ai())

    out = mw.wrap_model_call(_req(), handler)
    assert len(calls) == 2
    assert out.result[0].content == "done"


# --------------------------------------------------------------------------- classification


def test_error_is_classified_as_transient_network():
    """Subclassing ConnectionError is what buys the right bucket + user-facing copy."""
    exc = IncompleteStreamError("stream closed early")
    assert classify_behavior(exc) is Behavior.RETRYABLE
    assert label_error(exc) is ErrorType.NETWORK_TIMEOUT


def test_wrapped_error_still_reaches_the_network_card():
    """task_exec re-raises as ``TaskExecutionError(...) from e`` — the card must survive."""
    cause = IncompleteStreamError("stream closed early")
    try:
        try:
            raise cause
        except IncompleteStreamError as e:
            raise TaskExecutionError("Agent task execution failed") from e
    except TaskExecutionError as wrapper:
        assert classify_for_event(wrapper).error_type == ErrorType.NETWORK_TIMEOUT.value
