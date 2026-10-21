"""F087: BishengLLM turns a provider's context-window rejection into ContextOverflowError.

deepagents compresses history and retries only on ``ContextOverflowError``. The
converted error must stay an instance of the original SDK error with its body, and
it must not mark the model as broken in model management (design.md decisions 5, 6).
"""

from types import SimpleNamespace

import anthropic
import httpx
import openai
import pytest
from langchain_core.exceptions import ContextOverflowError
from langchain_core.messages import HumanMessage

from bisheng.llm.domain.const import LLMModelStatus
from bisheng.llm.domain.llm.context_overflow import as_context_overflow, extract_input_tokens
from bisheng.llm.domain.llm.exceptions import LLMContextOverflowError
from bisheng.llm.domain.llm.llm import BishengLLM

# Real provider wording, one per recognition rule.
VLLM_LEGACY = (
    "This model's maximum context length is 133120 tokens. However, you requested 0 output tokens and "
    "your prompt contains at least 133121 input tokens, for a total of at least 133121 tokens. Please "
    "reduce the length of the input prompt or the number of requested output tokens. "
    "(parameter=input_tokens, value=133121)"
)
VLLM_NEW = "The decoder prompt (length 40000) is longer than the maximum model length of 32768."
DEEPSEEK = (
    "This model's maximum context length is 131072 tokens. However, you requested 140000 tokens "
    "(135000 in the messages, 5000 in the completion)."
)
SGLANG = "Input length (40000 tokens) exceeds the maximum allowed length (32768 tokens)."
LLAMACPP = "the request (40000 tokens) exceeds the available context size (32768 tokens), try increasing it"
ANTHROPIC = "prompt is too long: 210000 tokens > 200000 maximum"


def _openai_400(message: str) -> openai.BadRequestError:
    request = httpx.Request("POST", "http://vllm.local/v1/chat/completions")
    body = {"error": {"message": message, "type": "BadRequestError", "code": 400}}
    return openai.BadRequestError(message, response=httpx.Response(400, request=request), body=body)


def _anthropic_400(message: str) -> anthropic.BadRequestError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    body = {"type": "error", "error": {"type": "invalid_request_error", "message": message}}
    return anthropic.BadRequestError(message, response=httpx.Response(400, request=request), body=body)


@pytest.mark.parametrize(
    "message,tokens",
    [(VLLM_LEGACY, 133121), (VLLM_NEW, 40000), (DEEPSEEK, 135000), (SGLANG, 40000), (LLAMACPP, 40000)],
)
def test_openai_compatible_rejections_become_overflow(message, tokens):
    original = _openai_400(message)
    overflow = as_context_overflow(original)

    assert isinstance(overflow, ContextOverflowError)
    assert isinstance(overflow, openai.BadRequestError)
    assert overflow.body == original.body
    assert overflow.status_code == 400
    assert overflow.reported_input_tokens == tokens


def test_anthropic_rejection_stays_an_anthropic_error():
    overflow = as_context_overflow(_anthropic_400(ANTHROPIC))

    assert isinstance(overflow, ContextOverflowError)
    assert isinstance(overflow, anthropic.BadRequestError)
    assert overflow.reported_input_tokens == 210000


def test_other_sdk_errors_get_the_bisheng_class():
    class ZhipuError(Exception):
        def __init__(self, message):
            super().__init__(message)
            self.body = {"error": {"message": message}}
            self.status_code = 400

    overflow = as_context_overflow(ZhipuError(VLLM_LEGACY))

    assert isinstance(overflow, LLMContextOverflowError)
    assert overflow.body == {"error": {"message": VLLM_LEGACY}}
    assert overflow.status_code == 400


def test_unrelated_400_is_left_alone():
    assert as_context_overflow(_openai_400("Invalid value for 'temperature'")) is None


def test_input_tokens_unknown_when_not_stated():
    assert extract_input_tokens("prompt is too long") is None


# ---------------------------------------------------------------------------
# Through the BishengLLM call paths, with the status/telemetry decorators on.
# ---------------------------------------------------------------------------


class _FailingInner:
    def __init__(self, exc: Exception, streaming: bool):
        self.exc = exc
        self.streaming = streaming

    def _generate(self, *args, **kwargs):
        raise self.exc

    async def _agenerate(self, *args, **kwargs):
        raise self.exc

    def _stream(self, *args, **kwargs):
        raise self.exc
        yield  # pragma: no cover

    async def _astream(self, *args, **kwargs):
        raise self.exc
        yield  # pragma: no cover


@pytest.fixture
def status_writes(monkeypatch):
    writes = []

    async def _noop_async(*args, **kwargs):
        return None

    monkeypatch.setattr("bisheng.llm.domain.utils.bisheng_model_limit_check", _noop_async)
    monkeypatch.setattr("bisheng.llm.domain.utils.sync_bisheng_model_limit_check", lambda *a, **k: None)
    monkeypatch.setattr("bisheng.llm.domain.utils.upload_telemetry_log", lambda *a, **k: None)
    return writes


def _wrapper(exc: Exception, streaming: bool, writes: list) -> BishengLLM:
    inst = BishengLLM.model_construct(llm=_FailingInner(exc, streaming))
    object.__setattr__(inst, "server_info", SimpleNamespace(type="vllm"))
    object.__setattr__(inst, "model_info", SimpleNamespace(model_type="llm"))
    object.__setattr__(inst, "model_id", 7)

    async def update_model_status(status, remark=""):
        writes.append(status)

    object.__setattr__(inst, "update_model_status", update_model_status)
    object.__setattr__(inst, "sync_update_model_status", lambda status, remark="": writes.append(status))
    return inst


MESSAGES = [HumanMessage(content="hi")]


@pytest.mark.parametrize("streaming", [True, False])
def test_generate_converts_and_keeps_model_status(status_writes, streaming):
    inst = _wrapper(_openai_400(VLLM_LEGACY), streaming, status_writes)
    with pytest.raises(ContextOverflowError) as info:
        inst._generate(MESSAGES)

    assert isinstance(info.value.__cause__, openai.BadRequestError)
    assert status_writes == []


@pytest.mark.parametrize("streaming", [True, False])
async def test_agenerate_converts_and_keeps_model_status(status_writes, streaming):
    inst = _wrapper(_openai_400(VLLM_LEGACY), streaming, status_writes)
    with pytest.raises(ContextOverflowError):
        await inst._agenerate(MESSAGES)

    assert status_writes == []


def test_stream_converts_and_keeps_model_status(status_writes):
    inst = _wrapper(_openai_400(VLLM_LEGACY), True, status_writes)
    with pytest.raises(ContextOverflowError):
        list(inst._stream(MESSAGES))

    assert status_writes == []


async def test_astream_converts_and_keeps_model_status(status_writes):
    inst = _wrapper(_openai_400(VLLM_LEGACY), True, status_writes)
    with pytest.raises(ContextOverflowError):
        async for _ in inst._astream(MESSAGES):
            pass

    assert status_writes == []


async def test_other_errors_still_mark_the_model(status_writes):
    inst = _wrapper(_openai_400("Invalid API key"), True, status_writes)
    with pytest.raises(openai.BadRequestError) as info:
        async for _ in inst._astream(MESSAGES):
            pass

    assert not isinstance(info.value, ContextOverflowError)
    assert status_writes == [LLMModelStatus.ERROR.value]


def test_context_window_is_not_sent_to_the_provider():
    inst = BishengLLM.model_construct()
    server = SimpleNamespace(
        id=1, name="vllm", type="vllm", config={"openai_api_base": "http://vllm.local/v1", "openai_api_key": "k"}
    )
    model = SimpleNamespace(
        id=7,
        model_name="qwen3-32b",
        model_type="llm",
        config={"user_kwargs": '{"context_window": 133120, "top_p": 0.8}'},
    )
    object.__setattr__(inst, "server_info", server)
    object.__setattr__(inst, "model_info", model)

    params = inst._get_llm_params(server, model)

    assert "context_window" not in params
    assert params["top_p"] == 0.8
