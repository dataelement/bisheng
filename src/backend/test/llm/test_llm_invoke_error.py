"""A failed provider call inside a plain request must surface as LlmInvokeError
(business code 10028), not as a bare HTTP 500 the user can only read as
"server error"."""

from types import SimpleNamespace

import httpx
import openai

from bisheng.common.errcode.server import LlmInvokeError, LlmModelOfflineError
from bisheng.llm.domain.utils import to_llm_invoke_error


def _model():
    return SimpleNamespace(
        model_info=SimpleNamespace(model_name="qwen-max"),
        server_info=SimpleNamespace(name="bailian"),
    )


def _status_error(status: int, body: dict) -> openai.APIStatusError:
    request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
    response = httpx.Response(status, request=request)
    return openai.AuthenticationError(f"Error code: {status} - {body}", response=response, body=body)


def test_provider_status_error_becomes_10028_with_short_reason():
    exc = _status_error(401, {"error": {"message": "Incorrect API key provided", "code": "invalid_api_key"}})

    err = to_llm_invoke_error(_model(), exc)

    assert isinstance(err, LlmInvokeError)
    assert err.code == 10028
    assert err.kwargs == {
        "model_name": "qwen-max",
        "server_name": "bailian",
        "reason": "HTTP 401: Incorrect API key provided",
    }
    assert "qwen-max" in err.message and "bailian" in err.message
    # The full provider exception stays attached for logs and the response data.
    assert err.exception is exc


def test_connection_error_falls_back_to_str():
    exc = openai.APIConnectionError(request=httpx.Request("POST", "https://example.invalid"))

    err = to_llm_invoke_error(_model(), exc)

    assert err.kwargs["reason"] == "Connection error."


def test_long_reason_is_truncated():
    err = to_llm_invoke_error(_model(), RuntimeError("x" * 1000))

    assert len(err.kwargs["reason"]) == 203
    assert err.kwargs["reason"].endswith("...")


def test_business_error_passes_through_unchanged():
    offline = LlmModelOfflineError(server_name="bailian", model_name="qwen-max")

    assert to_llm_invoke_error(_model(), offline) is offline


def test_model_without_info_still_builds_error():
    err = to_llm_invoke_error(None, ValueError("boom"))

    assert isinstance(err, LlmInvokeError)
    assert err.kwargs["model_name"] == "" and err.kwargs["reason"] == "boom"


class _FailingLLM:
    """Stands in for BishengLLM: carries model/server info, every call fails."""

    model_info = SimpleNamespace(model_name="qwen-max")
    server_info = SimpleNamespace(name="bailian")

    def __call__(self, *_args, **_kwargs):
        raise openai.APIConnectionError(request=httpx.Request("POST", "https://example.invalid"))


def _runnable_failing_llm():
    from langchain_core.runnables import RunnableLambda

    failing = _FailingLLM()
    runnable = RunnableLambda(failing)
    # AssistantAgent hands self.llm to the chain and to to_llm_invoke_error, so
    # the runnable must carry the model/server info too.
    object.__setattr__(runnable, "model_info", failing.model_info)
    object.__setattr__(runnable, "server_info", failing.server_info)
    return runnable


def test_opening_dialog_propagates_provider_error_instead_of_unbound_local():
    import pytest

    from bisheng_langchain.gpts.auto_optimization import generate_opening_dialog

    with pytest.raises(openai.APIConnectionError):
        generate_opening_dialog(_runnable_failing_llm(), "desc")


def test_assistant_agent_auto_calls_raise_llm_invoke_error():
    import pytest

    from bisheng.api.services.assistant_agent import AssistantAgent

    agent = AssistantAgent.__new__(AssistantAgent)
    agent.llm = _runnable_failing_llm()
    agent.assistant = SimpleNamespace(name="a", prompt="p")

    for call in (
        lambda: agent.generate_description("p"),
        lambda: agent.generate_guide("p"),
        lambda: agent.choose_tools([{"name": "t", "description": ""}], "p"),
    ):
        with pytest.raises(LlmInvokeError) as info:
            call()
        assert info.value.kwargs["model_name"] == "qwen-max"
        assert info.value.kwargs["reason"] == "Connection error."


async def test_assistant_prompt_optimization_stream_raises_llm_invoke_error():
    import pytest

    from bisheng.api.services.assistant_agent import AssistantAgent

    agent = AssistantAgent.__new__(AssistantAgent)
    agent.llm = _runnable_failing_llm()
    agent.assistant = SimpleNamespace(name="a", prompt="p")

    with pytest.raises(LlmInvokeError):
        async for _ in agent.optimize_assistant_prompt():
            pass
