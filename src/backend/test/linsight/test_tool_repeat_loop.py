"""Unit tests for the identical-repeat tier of LinsightToolLoopBreakerMiddleware.

The failure tier (``test_tool_loop_middleware.py``) only counts tool ERRORS. This
file covers the other loop shape: the model re-submitting a byte-identical tool call
that keeps SUCCEEDING. Measured on 114, 2026-08-14 — a kimi-k3 run re-sent the same
``bisheng_code_interpreter`` call 79 times over 78 minutes (13.8M input tokens) with
zero todos advanced, and every existing guard stayed silent.

Three fixture details are deliberately faithful to that incident; getting them wrong
means testing something that cannot fail:
1. ``tool_call_id`` is CONSTANT across turns (``bisheng_code_interpreter:0`` — what
   kimi-k3 returns via tokenrouter), not the unique ``call_<uuid>`` other vendors send.
2. The offloaded tool result carries ``status="success"`` — that is precisely why the
   failure counter never fired.
3. The oversized result is ONE line (``json.dumps`` output), which is what degrades the
   upstream preview to its first 1000 characters.

``asyncio_mode = auto`` — async tests need no decorator.
"""

import json

import pytest
from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from bisheng.linsight.domain.services.tool_loop_middleware import (
    LinsightToolLoopBreakerMiddleware,
    LinsightToolLoopError,
    build_tool_loop_breaker_middleware,
)

CI_TOOL = "bisheng_code_interpreter"
# Constant across turns — the whole point. See module docstring.
CI_CALL_ID = "bisheng_code_interpreter:0"
CI_ARGS = {"python_code": "import fitz\nprint('x')"}


# --------------------------------------------------------------------------- helpers


def _ai_call(tool=CI_TOOL, args=None, call_id=CI_CALL_ID, content=""):
    return AIMessage(
        content=content,
        tool_calls=[{"name": tool, "args": args if args is not None else CI_ARGS, "id": call_id, "type": "tool_call"}],
    )


def _offloaded_tm(tool=CI_TOOL, call_id=CI_CALL_ID):
    """The upstream 'result too large' replacement: SUCCESS status, one long line."""
    return ToolMessage(
        content=(
            f"Tool result too large, the result of this tool call {call_id} was saved in the "
            f"filesystem at this path: /large_tool_results/{call_id}\n\n"
            + json.dumps({"exitcode": 0, "log": "x" * 200}, ensure_ascii=False)
        ),
        tool_call_id=call_id,
        name=tool,
        status="success",
    )


def _repeat_turns(n, tool=CI_TOOL, args=None, call_id=CI_CALL_ID):
    """n interleaved (identical AIMessage tool_call -> success ToolMessage) turns."""
    msgs = []
    for _ in range(n):
        msgs.append(_ai_call(tool, args, call_id))
        msgs.append(_offloaded_tm(tool, call_id))
    return msgs


def _mw(*, repeat_soft=3, repeat_hard=8):
    return LinsightToolLoopBreakerMiddleware(repeat_soft_limit=repeat_soft, repeat_hard_limit=repeat_hard)


def _request(messages, *, state_messages=None):
    """A real ModelRequest so a langchain signature drift surfaces here, not in prod."""
    return ModelRequest(
        model=GenericFakeChatModel(messages=iter([])),
        messages=list(messages),
        tools=[],
        state={"messages": list(messages if state_messages is None else state_messages)},
    )


async def _run_nudge(mw, request):
    """Invoke the soft tier, returning the request the handler actually received."""
    seen = {}

    async def handler(req):
        seen["request"] = req
        return AIMessage(content="ok")

    await mw.awrap_model_call(request, handler)
    return seen["request"]


# --------------------------------------------------------------------------- soft tier


async def test_below_soft_limit_leaves_request_untouched():
    mw = _mw(repeat_soft=3)
    request = _request(_repeat_turns(2))
    received = await _run_nudge(mw, request)
    assert len(received.messages) == len(request.messages)


async def test_soft_limit_injects_counted_nudge():
    mw = _mw(repeat_soft=3)
    original = _repeat_turns(3)
    request = _request(original)
    received = await _run_nudge(mw, request)

    assert len(received.messages) == len(original) + 1
    tail = received.messages[-1]
    assert isinstance(tail, HumanMessage)
    # The COUNT is what breaks the temperature=0 fixed point: without a monotonically
    # changing tail the next context is a byte-identical function of the previous one.
    assert "3" in tail.content
    assert "完全相同" in tail.content
    assert "read_file" in tail.content
    # The original request object must not be mutated — the nudge is ephemeral.
    assert len(request.messages) == len(original)


async def test_nudge_reads_state_not_request_messages():
    """A wrap-up HumanMessage appended by the OUTER resilience middleware lives on
    ``request.messages`` but not in graph state. Since a human turn ends a repeat run,
    scanning the request list would silently disable this detector during soft landing.
    """
    mw = _mw(repeat_soft=3)
    state_messages = _repeat_turns(3)
    request = _request([*state_messages, HumanMessage(content="⚠️ 预算即将耗尽")], state_messages=state_messages)
    received = await _run_nudge(mw, request)
    assert isinstance(received.messages[-1], HumanMessage)
    assert "完全相同" in received.messages[-1].content


async def test_soft_tier_disabled_by_zero():
    mw = _mw(repeat_soft=0, repeat_hard=0)
    request = _request(_repeat_turns(20))
    received = await _run_nudge(mw, request)
    assert len(received.messages) == len(request.messages)


# --------------------------------------------------------------------------- hard tier


async def test_hard_limit_raises_with_repeat_reason():
    mw = _mw(repeat_soft=3, repeat_hard=8)
    messages = [AIMessage(content="我已经读完了 checklist 模板，共 109 项参数。"), *_repeat_turns(8)]
    with pytest.raises(LinsightToolLoopError) as exc:
        await mw.aafter_model({"messages": messages}, None)
    assert exc.value.reason == "repeat"
    assert exc.value.count == 8
    assert exc.value.tool_name == CI_TOOL
    # Salvage must carry the model's earlier analysis so the user still gets output.
    assert "109 项参数" in exc.value.partial_result


async def test_hard_tier_disabled_by_zero():
    mw = _mw(repeat_soft=3, repeat_hard=0)
    await mw.aafter_model({"messages": _repeat_turns(50)}, None)  # must not raise


async def test_tool_call_id_is_not_part_of_the_fingerprint():
    """Vendors that emit unique ids must be caught too — the loop is in the ARGUMENTS."""
    mw = _mw(repeat_soft=3, repeat_hard=8)
    messages = []
    for i in range(8):
        messages.append(_ai_call(call_id=f"call_{i:024d}"))
        messages.append(_offloaded_tm(call_id=f"call_{i:024d}"))
    with pytest.raises(LinsightToolLoopError):
        await mw.aafter_model({"messages": messages}, None)


async def test_parallel_identical_calls_count_as_one_turn():
    """Two identical calls in ONE AIMessage are one unit of model intent, not two."""
    mw = _mw(repeat_soft=3, repeat_hard=8)
    turn = AIMessage(
        content="",
        tool_calls=[
            {"name": CI_TOOL, "args": CI_ARGS, "id": "bisheng_code_interpreter:0", "type": "tool_call"},
            {"name": CI_TOOL, "args": CI_ARGS, "id": "bisheng_code_interpreter:1", "type": "tool_call"},
        ],
    )
    messages = []
    for _ in range(5):
        messages.append(turn)
        messages.append(_offloaded_tm(call_id="bisheng_code_interpreter:0"))
        messages.append(_offloaded_tm(call_id="bisheng_code_interpreter:1"))
    # 5 turns < hard 8: counting per-call would have reached 10 and aborted here.
    await mw.aafter_model({"messages": messages}, None)


# --------------------------------------------------------------------------- false positives


async def test_paginated_reads_are_not_a_repeat():
    """The most important guard: paging through a big file is legitimate repetition.

    ``read_file`` with a moving ``offset`` differs in ARGUMENTS, so it must never count
    — otherwise the fix would break the very recovery path it exists to enable.
    """
    mw = _mw(repeat_soft=3, repeat_hard=8)
    messages = []
    for page in range(10):
        messages.append(
            _ai_call(tool="read_file", args={"file_path": "/large_tool_results/x", "offset": page * 100, "limit": 100})
        )
        messages.append(ToolMessage(content="chunk", tool_call_id="read_file:0", name="read_file"))
    await mw.aafter_model({"messages": messages}, None)
    received = await _run_nudge(mw, _request(messages))
    assert len(received.messages) == len(messages)


async def test_differing_query_is_not_a_repeat():
    """web_search legitimately runs long streaks — with a different query each time."""
    mw = _mw(repeat_soft=3, repeat_hard=8)
    messages = []
    for i in range(12):
        messages.append(_ai_call(tool="web_search", args={"query": f"变压器 参数 {i}"}))
        messages.append(ToolMessage(content="results", tool_call_id="web_search:0", name="web_search"))
    await mw.aafter_model({"messages": messages}, None)


async def test_text_turn_breaks_the_run():
    mw = _mw(repeat_soft=3, repeat_hard=8)
    messages = [*_repeat_turns(7), AIMessage(content="换个思路，我改用 grep 定位。"), *_repeat_turns(1)]
    await mw.aafter_model({"messages": messages}, None)


async def test_new_human_turn_resets_the_run():
    mw = _mw(repeat_soft=3, repeat_hard=8)
    messages = [*_repeat_turns(7), HumanMessage(content="继续"), *_repeat_turns(1)]
    await mw.aafter_model({"messages": messages}, None)


async def test_ask_user_repeat_is_exempt():
    """ask_user parks on an interrupt; resuming replays a same-shaped call."""
    mw = _mw(repeat_soft=3, repeat_hard=8)
    messages = []
    for _ in range(15):
        messages.append(_ai_call(tool="ask_user", args={"reason": "需要澄清", "questions": []}))
        messages.append(ToolMessage(content="parked", tool_call_id="ask_user:0", name="ask_user"))
    await mw.aafter_model({"messages": messages}, None)
    received = await _run_nudge(mw, _request(messages))
    assert len(received.messages) == len(messages)


async def test_write_todos_nudges_but_tolerates_more_before_abort():
    mw = _mw(repeat_soft=3, repeat_hard=8)
    lenient = []
    for _ in range(10):
        lenient.append(_ai_call(tool="write_todos", args={"todos": [{"content": "a", "status": "pending"}]}))
        lenient.append(ToolMessage(content="updated", tool_call_id="write_todos:0", name="write_todos"))
    # Past the hard limit for a normal tool, still tolerated for a state-only one...
    await mw.aafter_model({"messages": lenient}, None)
    # ...but it is nudged, and it is NOT unbounded.
    received = await _run_nudge(mw, _request(lenient))
    assert isinstance(received.messages[-1], HumanMessage)
    for _ in range(15):
        lenient.append(_ai_call(tool="write_todos", args={"todos": [{"content": "a", "status": "pending"}]}))
        lenient.append(ToolMessage(content="updated", tool_call_id="write_todos:0", name="write_todos"))
    with pytest.raises(LinsightToolLoopError):
        await mw.aafter_model({"messages": lenient}, None)


# --------------------------------------------------------------------------- tier separation


async def test_pure_failure_run_is_left_to_the_failure_tier():
    """Identical calls that ALL error out are a failure loop, not a repeat loop.

    Claiming them here would abort earlier than ``tool_failure_hard_limit`` intends
    and would label the abort "重复提交" when the honest cause is "调用一直失败".
    """
    mw = LinsightToolLoopBreakerMiddleware(soft_limit=3, hard_limit=99, repeat_soft_limit=3, repeat_hard_limit=8)
    messages = []
    for _ in range(20):
        messages.append(_ai_call())
        messages.append(ToolMessage(content="boom", tool_call_id=CI_CALL_ID, name=CI_TOOL, status="error"))
    await mw.aafter_model({"messages": messages}, None)  # failure tier owns this run
    received = await _run_nudge(mw, _request(messages))
    assert len(received.messages) == len(messages)


async def test_mixed_results_still_count_as_a_repeat():
    """A run that succeeded at first and only recently started erroring is still a
    repeat loop — the model is re-sending identical arguments regardless."""
    mw = _mw(repeat_soft=3, repeat_hard=8)
    messages = _repeat_turns(6)
    for _ in range(2):
        messages.append(_ai_call())
        messages.append(ToolMessage(content="boom", tool_call_id=CI_CALL_ID, name=CI_TOOL, status="error"))
    with pytest.raises(LinsightToolLoopError) as exc:
        await mw.aafter_model({"messages": messages}, None)
    assert exc.value.reason == "repeat"


async def test_evicted_success_results_do_not_feed_the_failure_counter():
    """Pins WHY this tier had to exist: the failure counter breaks on the first
    non-error result, and an evicted tool message keeps ``status="success"``.
    """
    mw = _mw(repeat_soft=99, repeat_hard=0)  # repeat tier fully disabled
    await mw.aafter_model({"messages": _repeat_turns(30)}, None)  # failure tier stays silent

    mw_enabled = _mw(repeat_soft=3, repeat_hard=8)
    with pytest.raises(LinsightToolLoopError) as exc:
        await mw_enabled.aafter_model({"messages": _repeat_turns(30)}, None)
    assert exc.value.reason == "repeat"


def test_build_reads_repeat_limits_from_conf():
    class _Conf:
        tool_failure_soft_limit = 3
        tool_failure_hard_limit = 8
        tool_repeat_soft_limit = 4
        tool_repeat_hard_limit = 9

    mw = build_tool_loop_breaker_middleware(_Conf(), is_subagent=False)
    assert mw.repeat_soft_limit == 4
    assert mw.repeat_hard_limit == 9


def test_build_tolerates_conf_without_repeat_limits():
    """Existing deployments have no such keys in initdb_config; defaults must hold."""

    class _OldConf:
        tool_failure_soft_limit = 3
        tool_failure_hard_limit = 8

    mw = build_tool_loop_breaker_middleware(_OldConf(), is_subagent=True)
    assert mw.repeat_soft_limit == 3
    assert mw.repeat_hard_limit == 8
