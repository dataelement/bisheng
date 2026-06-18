"""Unit tests for LinsightModelResilienceMiddleware (灵思LLM容错).

Exercises the three control-flow branches (retry / degrade / fail-fast) and the
per-instance degrade budget, with delays forced to zero so no real sleeping
happens. ``asyncio_mode = auto`` — async tests need no decorator.
"""

import openai
import pytest
from langchain_core.messages import AIMessage

from bisheng.linsight.domain.services.resilience_middleware import (
    _DEGRADE_MESSAGE,
    LinsightModelResilienceMiddleware,
)


def make_exc(cls, *, message="", code=None, body=None, status_code=None):
    exc = cls.__new__(cls)
    exc.message = message
    exc.code = code
    exc.body = body
    if status_code is not None:
        exc.status_code = status_code
    return exc


def timeout_exc():
    return make_exc(openai.APITimeoutError, message="timeout")


def content_filter_exc():
    return make_exc(
        openai.BadRequestError,
        message="Output data may contain inappropriate content",
        code="data_inspection_failed",
        status_code=400,
    )


def quota_exc():
    return make_exc(openai.RateLimitError, message="insufficient_quota", code="insufficient_quota", status_code=429)


def make_mw(*, is_subagent=False, max_retries=2, max_degrade=3):
    # initial_delay=0 → calculate_delay returns 0 → no asyncio.sleep
    return LinsightModelResilienceMiddleware(
        max_retries=max_retries,
        initial_delay=0.0,
        max_degrade=max_degrade,
        is_subagent=is_subagent,
    )


def handler_factory(exceptions):
    """Async handler that raises each queued exception then returns success.

    ``exceptions`` is a list; each call pops one. When empty, returns a success
    AIMessage. Records the number of invocations on ``.calls``.
    """
    state = {"calls": 0, "queue": list(exceptions)}

    async def handler(_request):
        state["calls"] += 1
        if state["queue"]:
            raise state["queue"].pop(0)
        return AIMessage(content="ok")

    handler.state = state
    return handler


async def test_retry_then_success():
    mw = make_mw(max_retries=2)
    handler = handler_factory([timeout_exc(), timeout_exc()])  # 2 transient failures then ok
    result = await mw.awrap_model_call(None, handler)
    assert isinstance(result, AIMessage)
    assert result.content == "ok"
    assert handler.state["calls"] == 3  # initial + 2 retries


async def test_retry_exhausted_subagent_degrades():
    mw = make_mw(is_subagent=True, max_retries=1)
    handler = handler_factory([timeout_exc(), timeout_exc(), timeout_exc()])  # always fails
    result = await mw.awrap_model_call(None, handler)
    assert isinstance(result, AIMessage)
    assert result.content == _DEGRADE_MESSAGE
    assert handler.state["calls"] == 2  # initial + 1 retry, then degrade


async def test_retry_exhausted_main_raises():
    mw = make_mw(is_subagent=False, max_retries=1)
    handler = handler_factory([timeout_exc(), timeout_exc()])
    with pytest.raises(openai.APITimeoutError):
        await mw.awrap_model_call(None, handler)
    assert handler.state["calls"] == 2


async def test_content_filter_subagent_degrades_without_retry():
    mw = make_mw(is_subagent=True, max_retries=3)
    handler = handler_factory([content_filter_exc()])
    result = await mw.awrap_model_call(None, handler)
    assert isinstance(result, AIMessage)
    assert result.content == _DEGRADE_MESSAGE
    assert handler.state["calls"] == 1  # DEGRADABLE is not retried


async def test_content_filter_main_raises_without_retry():
    mw = make_mw(is_subagent=False, max_retries=3)
    handler = handler_factory([content_filter_exc()])
    with pytest.raises(openai.BadRequestError):
        await mw.awrap_model_call(None, handler)
    assert handler.state["calls"] == 1


async def test_quota_fails_fast_both_roles():
    for is_subagent in (True, False):
        mw = make_mw(is_subagent=is_subagent, max_retries=3)
        handler = handler_factory([quota_exc()])
        with pytest.raises(openai.RateLimitError):
            await mw.awrap_model_call(None, handler)
        assert handler.state["calls"] == 1  # FAIL_FAST never retries


async def test_degrade_budget_exhaustion_raises():
    mw = make_mw(is_subagent=True, max_retries=0, max_degrade=2)
    # Each call is a separate model step that hits the content filter.
    r1 = await mw.awrap_model_call(None, handler_factory([content_filter_exc()]))
    r2 = await mw.awrap_model_call(None, handler_factory([content_filter_exc()]))
    assert r1.content == _DEGRADE_MESSAGE
    assert r2.content == _DEGRADE_MESSAGE
    # 3rd degrade exceeds the budget of 2 → re-raise instead of degrading.
    with pytest.raises(openai.BadRequestError):
        await mw.awrap_model_call(None, handler_factory([content_filter_exc()]))


async def test_success_passthrough():
    mw = make_mw()
    handler = handler_factory([])  # succeeds immediately
    result = await mw.awrap_model_call(None, handler)
    assert result.content == "ok"
    assert handler.state["calls"] == 1
