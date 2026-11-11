"""Provider validation must preserve the task model-call retry policies."""

import json

import openai
import pytest
from langchain.agents.middleware.types import ModelResponse

from bisheng.common.services.failure_context import FailureContextAdapter
from bisheng.linsight.domain.services.resilience_middleware import (
    IncompleteStreamError,
    LinsightModelResilienceMiddleware,
)
from test.llm.test_provider_response_validation import choice, invoke, model_for_body, sse


def response_for_result(result):
    generation = result.generations[0]
    # BaseChatModel's public invocation attaches generation metadata to messages.
    generation.message.response_metadata.update(generation.generation_info or {})
    return ModelResponse(result=[generation.message])


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("max_retries", [0, 5])
async def test_incomplete_exception_keeps_its_independent_two_retry_allowance(asynchronous, max_retries):
    calls = []
    model = model_for_body(sse(choice("Hello fr")), requests=calls)
    mw = LinsightModelResilienceMiddleware(max_retries=max_retries, initial_delay=0.0)

    async def async_handler(_request):
        result = await invoke(model, "_agenerate")
        return response_for_result(result)

    def sync_handler(_request):
        from langchain_core.messages import HumanMessage

        result = type(model)._generate.__wrapped__(model, [HumanMessage(content="hi")])
        return response_for_result(result)

    with pytest.raises(IncompleteStreamError) as caught:
        if asynchronous:
            await mw.awrap_model_call(None, async_handler)
        else:
            mw.wrap_model_call(None, sync_handler)
    assert len(calls) == 3
    assert FailureContextAdapter.from_error(caught.value)["category"] == "model_service"


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_fallback_incomplete_response_still_captures_model_category(asynchronous):
    from langchain_core.messages import AIMessage

    response = ModelResponse(result=[AIMessage(content="partial", response_metadata={"model_provider": "openai"})])
    mw = LinsightModelResilienceMiddleware(max_retries=0, initial_delay=0.0)

    async def async_handler(_request):
        return response

    with pytest.raises(IncompleteStreamError) as caught:
        if asynchronous:
            await mw.awrap_model_call(None, async_handler)
        else:
            mw.wrap_model_call(None, lambda _: response)
    assert FailureContextAdapter.from_error(caught.value)["category"] == "model_service"


@pytest.mark.parametrize("is_subagent", [False, True])
async def test_content_filter_never_retries_and_retains_model_category(is_subagent):
    calls = []
    model = model_for_body(sse(choice(finish_reason="content_filter")), requests=calls)
    mw = LinsightModelResilienceMiddleware(max_retries=5, initial_delay=0.0, is_subagent=is_subagent)

    async def handler(_request):
        result = await invoke(model, "_agenerate")
        return response_for_result(result)

    if is_subagent:
        result = await mw.awrap_model_call(None, handler)
        assert result.additional_kwargs["failure_info"]["category"] == "model_service"
    else:
        with pytest.raises(Exception) as caught:
            await mw.awrap_model_call(None, handler)
        assert getattr(caught.value, "code", None) == "content_filter"
        assert FailureContextAdapter.from_error(caught.value)["category"] == "model_service"
    assert len(calls) == 1


async def test_rate_limit_still_uses_the_configured_exception_retry_allowance():
    calls = []
    model = model_for_body(
        json.dumps({"error": {"code": "rate_limit_exceeded", "message": "Rate limit exceeded"}}).encode(),
        requests=calls,
        status=429,
    )
    mw = LinsightModelResilienceMiddleware(max_retries=1, initial_delay=0.0)

    async def handler(_request):
        return await invoke(model, "_agenerate")

    with pytest.raises(openai.RateLimitError):
        await mw.awrap_model_call(None, handler)
    assert len(calls) == 2


async def test_terminal_response_is_accepted_without_a_retry():
    calls = []
    model = model_for_body(sse(choice("done", finish_reason="stop")), requests=calls)
    mw = LinsightModelResilienceMiddleware(max_retries=5, initial_delay=0.0)

    async def handler(_request):
        result = await invoke(model, "_agenerate")
        return response_for_result(result)

    result = await mw.awrap_model_call(None, handler)
    assert result.result[0].content == "done"
    assert len(calls) == 1


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_exception_retry_does_not_consume_incomplete_stream_allowance(asynchronous):
    calls = []
    model = model_for_body(sse(choice("Hello fr")), requests=calls)
    mw = LinsightModelResilienceMiddleware(max_retries=1, initial_delay=0.0)
    attempts = 0

    def sync_handler(_request):
        from langchain_core.messages import HumanMessage

        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("transport timeout")
        return type(model)._generate.__wrapped__(model, [HumanMessage(content="hi")])

    async def async_handler(_request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("transport timeout")
        return await invoke(model, "_agenerate")

    with pytest.raises(IncompleteStreamError):
        if asynchronous:
            await mw.awrap_model_call(None, async_handler)
        else:
            mw.wrap_model_call(None, sync_handler)
    assert attempts == 4
    assert len(calls) == 3
