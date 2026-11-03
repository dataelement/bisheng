"""Workstation Chat calls must not inherit the Responses protocol switch."""

import json

import httpx
import pytest
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from bisheng.workstation.domain.services.chat_helpers import use_chat_completions


class WrappedModel(BaseModel):
    llm: ChatOpenAI


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("with_tools", [False, True])
async def test_workstation_selects_chat_wire_protocol_without_mutating_model(stream, with_tools):
    requests = []

    async def upstream(request):
        requests.append(request)
        if stream:
            body = (
                'data: {"id":"x","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"hello"},"finish_reason":null}]}\n\n'
                'data: {"id":"x","object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
                "data: [DONE]\n\n"
            )
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as http_client:
        original = WrappedModel(
            llm=ChatOpenAI(
                model="test",
                api_key="test",
                base_url="https://supplier.invalid/v1",
                use_responses_api=True,
                http_async_client=http_client,
                max_retries=0,
            )
        )
        selected = use_chat_completions(original)
        model = selected.llm
        if with_tools:
            model = model.bind_tools(
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "description": "Lookup",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ]
            )
        if stream:
            chunks = [chunk.content async for chunk in model.astream([HumanMessage(content="hi")])]
            assert "".join(chunks) == "hello"
        else:
            assert (await model.ainvoke([HumanMessage(content="hi")])).content == "hello"

    assert requests[0].url.path == "/v1/chat/completions"
    assert json.loads(requests[0].content)["model"] == "test"
    assert original.llm.use_responses_api is True
    assert selected is not original and selected.llm.use_responses_api is False


def test_unrelated_model_is_unchanged():
    model = object()
    assert use_chat_completions(model) is model
