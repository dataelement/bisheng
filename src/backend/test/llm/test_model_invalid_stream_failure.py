"""An HTTP 200 carrying invalid JSON must remain a model-service failure."""

from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import HumanMessage

from bisheng.common.services.failure_context import FailureContextAdapter
from bisheng.core.ai import ChatOpenAICompatible
from bisheng.llm.domain.llm.llm import BishengLLM


def make_model(body, content_type):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=body, headers={"content-type": content_type})
    )
    inner = ChatOpenAICompatible(
        model="mock-malformed-response",
        api_key="unused",
        base_url="https://model.invalid/v1",
        http_client=httpx.Client(transport=transport),
        http_async_client=httpx.AsyncClient(transport=transport),
        max_retries=0,
    )
    model = BishengLLM.model_construct(llm=inner)
    object.__setattr__(model, "model_info", SimpleNamespace(name="Mock model"))
    return model


@pytest.mark.parametrize(
    "body,content_type", [(b'{"choices":', "application/json"), (b'data: {"choices":\n\n', "text/event-stream")]
)
@pytest.mark.parametrize("method", ["_stream", "_astream", "_generate", "_agenerate"])
async def test_malformed_provider_stream_keeps_model_classification(body, content_type, method):
    model = make_model(body, content_type)
    with pytest.raises(Exception) as caught:
        # Only skip quota/telemetry; exercise the real SDK and failure boundary.
        if method == "_astream":
            async for _ in BishengLLM._astream.__wrapped__(model, [HumanMessage(content="hi")]):
                pass
        elif method == "_stream":
            list(BishengLLM._stream.__wrapped__(model, [HumanMessage(content="hi")]))
        elif method == "_generate":
            BishengLLM._generate.__wrapped__(model, [HumanMessage(content="hi")])
        else:
            await BishengLLM._agenerate.__wrapped__(model, [HumanMessage(content="hi")])
    info = FailureContextAdapter.from_error(caught.value)
    assert info is not None
    assert info["category"] == "model_service"
    assert info["service"] == "llm"
    assert info["operation"] == "invoke_model"
    assert FailureContextAdapter.public_payload({}, exc=caught.value)["failure_info"] == info


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_valid_empty_content_chunk_is_not_an_invalid_response(asynchronous):
    # Empty text is legal (e.g. tool-call / usage frames); only zero chunks fail.
    model = make_model(
        b'data: {"id":"test","choices":[{"index":0,"delta":{"content":""},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
        "text/event-stream",
    )
    if asynchronous:
        chunks = [chunk async for chunk in BishengLLM._astream.__wrapped__(model, [HumanMessage(content="hi")])]
    else:
        chunks = list(BishengLLM._stream.__wrapped__(model, [HumanMessage(content="hi")]))
    assert len(chunks) == 1
