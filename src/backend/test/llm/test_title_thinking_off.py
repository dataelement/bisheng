"""Conversation titles are requested with the model's thinking switched off."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from bisheng.common.utils import title_generator
from bisheng.llm.domain.const import LLMServerType
from bisheng.llm.domain.llm.llm import BishengLLM, thinking_off_extra_body
from bisheng.llm.domain.models import LLMModel, LLMServer

CHAT_TEMPLATE_OFF = {"chat_template_kwargs": {"thinking": False, "enable_thinking": False}}


@pytest.mark.parametrize(
    "server_type, expected",
    [
        (LLMServerType.VLLM.value, CHAT_TEMPLATE_OFF),
        (LLMServerType.OPENAI_COMPATIBLE.value, CHAT_TEMPLATE_OFF),
        (LLMServerType.QWEN.value, {"enable_thinking": False}),
        (LLMServerType.VOLCENGINE.value, {"thinking": {"type": "disabled"}}),
        (LLMServerType.OPENAI.value, None),
        (LLMServerType.AZURE_OPENAI.value, None),
        (LLMServerType.DEEPSEEK.value, None),
    ],
)
def test_switch_per_provider(server_type, expected):
    assert thinking_off_extra_body(server_type, None) == expected


def test_switch_keeps_the_clients_own_body():
    """Call-time extra_body replaces the client's, so its fields must be carried over."""
    current = {"enable_search": True, "chat_template_kwargs": {"foo": 1, "thinking": True}}

    merged = thinking_off_extra_body(LLMServerType.VLLM.value, current)

    assert merged == {
        "enable_search": True,
        "chat_template_kwargs": {"foo": 1, "thinking": False, "enable_thinking": False},
    }
    assert current["chat_template_kwargs"]["thinking"] is True  # caller's dict untouched


def _snapshot_llm(server_type: str, model_config: dict | None = None) -> BishengLLM:
    server = LLMServer(id=1, name="s", type=server_type, config={"openai_api_base": "http://127.0.0.1:9/v1"})
    model = LLMModel(id=2, server_id=1, name="m", model_name="dsv4", model_type="llm", online=True, config=model_config)
    return BishengLLM.get_class_instance_from_snapshot(
        model_info=model, server_info=server, app_id="t", app_type="daily_chat", app_name="t", user_id=1
    )


def test_vllm_request_payload_carries_the_switch():
    llm = _snapshot_llm(LLMServerType.VLLM.value)

    payload = llm.llm._get_request_payload([HumanMessage(content="hi")], **llm.thinking_off_kwargs())

    assert payload["extra_body"] == CHAT_TEMPLATE_OFF


def test_openai_gets_no_switch():
    assert _snapshot_llm(LLMServerType.OPENAI.value).thinking_off_kwargs() == {}


def _patch_prompt(monkeypatch):
    loader = SimpleNamespace(render_prompt=lambda *_a, **_k: SimpleNamespace(prompt="Name this conversation"))
    monkeypatch.setattr(title_generator, "get_prompt_manager", AsyncMock(return_value=loader))
    monkeypatch.setattr(title_generator, "get_prompt_manager_sync", lambda: loader)


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_title_call_sends_the_switch(monkeypatch, asynchronous):
    _patch_prompt(monkeypatch)
    off = {"extra_body": {"enable_thinking": False}}
    response = AIMessage(content="Travel plan")
    llm = SimpleNamespace(
        thinking_off_kwargs=lambda: off,
        invoke=MagicMock(return_value=response),
        ainvoke=AsyncMock(return_value=response),
    )

    if asynchronous:
        assert await title_generator.generate_conversation_title_async("Travel", llm) == "Travel plan"
        llm.ainvoke.assert_awaited_once_with([HumanMessage(content="Name this conversation")], **off)
    else:
        assert title_generator.generate_conversation_title_sync("Travel", llm) == "Travel plan"
        llm.invoke.assert_called_once_with([HumanMessage(content="Name this conversation")], **off)


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_rejected_switch_retries_with_provider_defaults(monkeypatch, asynchronous):
    _patch_prompt(monkeypatch)
    response = AIMessage(content="Travel plan")

    def answer(_messages, **kwargs):
        if kwargs:
            raise ValueError("400 unknown field chat_template_kwargs")
        return response

    async def aanswer(messages, **kwargs):
        return answer(messages, **kwargs)

    llm = SimpleNamespace(
        thinking_off_kwargs=lambda: {"extra_body": CHAT_TEMPLATE_OFF},
        invoke=MagicMock(side_effect=answer),
        ainvoke=AsyncMock(side_effect=aanswer),
    )

    if asynchronous:
        assert await title_generator.generate_conversation_title_async("Travel", llm) == "Travel plan"
        assert llm.ainvoke.await_count == 2
    else:
        assert title_generator.generate_conversation_title_sync("Travel", llm) == "Travel plan"
        assert llm.invoke.call_count == 2


def test_qwen_payload_keeps_web_search_while_switching_thinking_off():
    llm = _snapshot_llm(LLMServerType.QWEN.value, {"enable_web_search": True})

    payload = llm.llm._get_request_payload([HumanMessage(content="hi")], **llm.thinking_off_kwargs())

    assert payload["extra_body"]["enable_search"] is True
    assert payload["extra_body"]["enable_thinking"] is False
