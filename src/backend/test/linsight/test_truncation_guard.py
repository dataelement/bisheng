"""Unit tests for the Layer 2 truncation guard in LinsightModelResilienceMiddleware.

A model call cut off by ``finish_reason=length`` WHILE emitting a tool call is the
root cause of the write_file "content: Field required" loop. The guard detects it,
injects a "write in smaller parts" nudge, and retries a bounded number of times;
if still truncating it hands the response off to the L3/L4 backstops.

``asyncio_mode = auto`` — async tests need no decorator.
"""

from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage

from bisheng.linsight.domain.services.resilience_middleware import (
    _TRUNCATION_NUDGE,
    LinsightModelResilienceMiddleware,
    _is_truncated_tool_call,
    _log_call_diagnostics,
    _summarize_tool_calls,
)


def _truncated_ai(finish="length"):
    return AIMessage(
        content="",
        tool_calls=[{"name": "write_file", "args": {"file_path": "/output/r.md"}, "id": "t", "type": "tool_call"}],
        response_metadata={"finish_reason": finish},
    )


def _ok_ai():
    return AIMessage(content="done", response_metadata={"finish_reason": "stop"})


def _resp(msg):
    return ModelResponse(result=[msg])


def _req():
    return ModelRequest(model=None, messages=[HumanMessage(content="写一份报告")])


def _mw(limit=2):
    return LinsightModelResilienceMiddleware(max_retries=3, initial_delay=0.0, truncation_retry_limit=limit)


# --------------------------------------------------------------------------- detection


def test_detect_truncated_tool_call_length():
    assert _is_truncated_tool_call(_resp(_truncated_ai("length"))) is True


def test_detect_truncated_tool_call_anthropic_max_tokens():
    assert _is_truncated_tool_call(_resp(_truncated_ai("max_tokens"))) is True


def test_not_truncated_when_finish_stop():
    assert _is_truncated_tool_call(_resp(_ok_ai())) is False


def test_not_truncated_when_length_but_no_tool_call():
    ai = AIMessage(content="a long truncated essay", response_metadata={"finish_reason": "length"})
    assert _is_truncated_tool_call(_resp(ai)) is False


def test_detect_accepts_bare_aimessage():
    assert _is_truncated_tool_call(_truncated_ai()) is True


# --------------------------------------------------------------------------- behaviour


async def test_retries_with_nudge_then_returns_recovered():
    mw = _mw(limit=2)
    seen_lengths = []

    async def handler(request):
        seen_lengths.append(len(request.messages))
        # First call truncates; the nudged retry succeeds.
        return _resp(_truncated_ai()) if len(seen_lengths) == 1 else _resp(_ok_ai())

    out = await mw.awrap_model_call(_req(), handler)
    assert len(seen_lengths) == 2  # exactly one retry
    assert seen_lengths[1] == seen_lengths[0] + 1  # nudge appended to the retry request
    assert out.result[0].content == "done"  # recovered response returned


async def test_gives_up_after_limit_and_hands_off_truncated():
    mw = _mw(limit=2)
    calls = {"n": 0}

    async def handler(_request):
        calls["n"] += 1
        return _resp(_truncated_ai())  # always truncated

    out = await mw.awrap_model_call(_req(), handler)
    assert calls["n"] == 3  # initial + 2 bounded retries
    assert _is_truncated_tool_call(out) is True  # truncated response handed to L3/L4


async def test_nudge_message_is_appended():
    mw = _mw(limit=1)
    captured = []

    async def handler(request):
        captured.append(list(request.messages))
        return _resp(_truncated_ai()) if len(captured) == 1 else _resp(_ok_ai())

    await mw.awrap_model_call(_req(), handler)
    last = captured[1][-1]
    assert isinstance(last, HumanMessage)
    assert last.content == _TRUNCATION_NUDGE


async def test_truncation_retry_disabled_when_limit_zero():
    mw = _mw(limit=0)
    calls = {"n": 0}

    async def handler(_request):
        calls["n"] += 1
        return _resp(_truncated_ai())

    out = await mw.awrap_model_call(_req(), handler)
    assert calls["n"] == 1  # no retry when disabled
    assert _is_truncated_tool_call(out) is True


# --------------------------------------------------------------------------- #1 diagnostics


def test_summarize_tool_calls_flags_missing_content():
    # A truncated write_file call has file_path but NO content — that absent key is
    # the whole diagnostic signal for the loop.
    truncated = AIMessage(
        content="",
        tool_calls=[{"name": "write_file", "args": {"file_path": "/o/r.md"}, "id": "t", "type": "tool_call"}],
    )
    assert _summarize_tool_calls(truncated) == ["write_file(file_path)"]
    full = AIMessage(
        content="",
        tool_calls=[
            {"name": "write_file", "args": {"file_path": "/o/r.md", "content": "x"}, "id": "t", "type": "tool_call"}
        ],
    )
    assert _summarize_tool_calls(full) == ["write_file(content,file_path)"]


def test_summarize_tool_calls_never_dumps_values():
    # Safety: a huge content value must never reach the log — only KEY names.
    huge = "A" * 100_000
    ai = AIMessage(
        content="",
        tool_calls=[
            {"name": "write_file", "args": {"file_path": "/o/r.md", "content": huge}, "id": "t", "type": "tool_call"}
        ],
    )
    summary = _summarize_tool_calls(ai)
    assert summary == ["write_file(content,file_path)"]
    assert huge not in "".join(summary)


def test_log_call_diagnostics_never_raises():
    # Observability must never break the model call, whatever the response shape.
    _log_call_diagnostics(None, is_subagent=False)
    _log_call_diagnostics(_resp(_truncated_ai()), is_subagent=True)
    _log_call_diagnostics(object(), is_subagent=False)
