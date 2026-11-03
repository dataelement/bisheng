"""MiniMax M2.7 tool calls must not expose its truncated upstream SSE arguments."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from bisheng.common.errcode.dsh import DshUpstreamErrorError
from bisheng.dsh.domain.schemas.chat import ChatCapabilities, DshChatRequest
from bisheng.dsh.infrastructure.chat_adapter import DshChatAdapter
from bisheng.dsh.infrastructure.model_capabilities import model_capabilities
from bisheng.llm.domain.llm.llm import BishengLLM
from bisheng.llm.domain.models import LLMModel, LLMServer


@pytest.mark.parametrize(
    "provider,url,model,buffered",
    [
        ("minimax", "https://enterprise.invalid/minimax", "MiniMax-M2.7", True),
        ("openai", "https://api.minimaxi.com/v1", "MiniMax-M2.7", True),
        ("openai", "https://api.minimax.io/v1", "MiniMax-M2.7-highspeed", True),
        ("openai", "https://api.minimax.cn/v1", "MiniMax-M2.7", True),
        ("openai", "https://api.minimaxi.com.attacker.invalid/v1", "MiniMax-M2.7", False),
        ("openai", "https://api.minimaxi.com/v1", "another-model", False),
        ("openai", "https://api.openai.com/v1", "another-model", False),
    ],
)
def test_only_affected_model_and_provider_disable_upstream_tool_streaming(provider, url, model, buffered):
    caps = model_capabilities(
        SimpleNamespace(model_name=model, config={}),
        SimpleNamespace(type=provider, config={"openai_api_base": url}),
    )
    assert caps.reasoning_split is buffered
    assert "reasoning_split" not in caps.client_fields()
    assert caps.tool_streaming is not buffered
    assert caps.client_fields()["streaming"] is True
    assert caps.client_fields()["tools"] is True
    assert "tool_streaming" not in caps.client_fields()


@pytest.mark.parametrize("scenario", ["valid", "repair", "invalid", "xml"])
async def test_governed_wrapper_receives_whole_arguments_before_emitting_tools(monkeypatch, scenario):
    requests = []

    async def handle(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload["stream"] is False
        assert payload["reasoning_split"] is True
        assert "stream_options" not in payload
        valid = scenario == "valid" or (scenario != "invalid" and len(requests) == 2)
        args = '{"command":"echo hello","timeoutMs":120000}' if valid else '{"command":"echo hello","timeoutMs": '
        xml = scenario == "xml" and len(requests) == 1
        if len(requests) == 2:
            assert payload["tool_choice"] == "required"
            assert "incomplete or unparsed" in payload["messages"][-1]["content"]
        return httpx.Response(
            200,
            json={
                "id": "upstream-id",
                "model": "MiniMax-M2.7",
                "object": "chat.completion",
                "created": 1,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop" if xml else "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": 'I will run the check.\n<tool_call><invoke name="bash">' if xml else None,
                            "tool_calls": None
                            if xml
                            else [
                                {"id": "call-1", "type": "function", "function": {"name": "bash", "arguments": args}}
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            },
        )

    monkeypatch.setattr("bisheng.llm.domain.utils.upload_telemetry_log", lambda *a, **kw: None)
    monkeypatch.setattr(BishengLLM, "update_model_status", AsyncMock())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        wrapper = BishengLLM.get_class_instance_from_snapshot(
            model_info=LLMModel(
                id=1,
                server_id=1,
                model_name="MiniMax-M2.7",
                model_type="llm",
                online=True,
                config={"user_kwargs": {"http_async_client": client}},
            ),
            server_info=LLMServer(
                id=1,
                name="fixture",
                type="openai",
                limit_flag=False,
                config={"api_key": "fixture", "base_url": "https://fixture.invalid/v1"},
            ),
            streaming=True,
            app_id="fixture",
            app_name="fixture",
            app_type="dsh_desktop",
            user_id=1,
            max_retries=0,
        )
        request = DshChatRequest(
            model="bisheng:1",
            messages=[{"role": "user", "content": "generate a tool call"}],
            stream=True,
            tools=[{"type": "function", "function": {"name": "bash", "parameters": {"type": "object"}}}],
        )
        execution = DshChatAdapter().prepare(
            request, wrapper, ChatCapabilities(reasoning_split=True, tool_streaming=False)
        )
        deltas = []
        if scenario != "invalid":
            async for delta in execution.stream():
                deltas.append(delta)
            call = deltas[0]["tool_calls"][0]
            assert call["index"] == 0
            assert json.loads(call["function"]["arguments"])["timeoutMs"] == 120000
            assert execution.finish_reason == "tool_calls"
        else:
            with pytest.raises(DshUpstreamErrorError):
                async for delta in execution.stream():
                    deltas.append(delta)
            assert deltas == []
        assert len(requests) == (1 if scenario == "valid" else 2)
        assert execution.usage.total_tokens == (120 if scenario == "valid" else 240)
        assert wrapper.llm.streaming is True
        assert wrapper.streaming is True
