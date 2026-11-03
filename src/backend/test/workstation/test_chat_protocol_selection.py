"""Workstation Chat calls must not inherit the Responses protocol switch."""

import json

import httpx
import pytest
from langchain_core.messages import HumanMessage

from bisheng.llm.domain.llm.llm import BishengLLM
from bisheng.llm.domain.models import LLMModel, LLMServer


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("with_tools", [False, True])
async def test_workstation_selects_chat_wire_protocol_without_mutating_model(stream, with_tools, monkeypatch):
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
        original_params = BishengLLM._get_llm_params

        def client_params(self, server, model):
            return {
                **original_params(self, server, model),
                "http_async_client": http_client,
                "max_retries": 0,
                "streaming": stream,
            }

        monkeypatch.setattr(BishengLLM, "_get_llm_params", client_params)
        config = {"user_kwargs": json.dumps({"use_responses_api": True})}
        model_info = LLMModel(id=42, server_id=7, model_name="test", model_type="llm", config=config)
        server = LLMServer(id=7, type="openai", config={"api_key": "test", "base_url": "https://supplier.invalid/v1"})
        original = BishengLLM.get_class_instance_from_snapshot(
            model_info=model_info, server_info=server, app_id="test", app_type="dsh_desktop", app_name="test", user_id=1
        )
        model = original.llm
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
    assert original.llm.use_responses_api is False
    assert model_info.config == config
