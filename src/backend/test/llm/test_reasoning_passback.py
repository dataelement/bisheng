"""Earlier assistant reasoning goes back only with a tool-calling request.

DeepSeek thinking mode: with ``tools`` every earlier turn's ``reasoning_content``
is returned and spliced into the context; without ``tools`` it is ignored, so it
is not sent at all (another provider might not ignore it).
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from bisheng.core.ai.llm.chat_openai_compatible import ChatOpenAICompatible
from bisheng.core.ai.llm.chat_openai_reasoning import ChatOpenAIReasoning
from bisheng.core.ai.llm.custom_chat_deepseek import CustomChatDeepSeek

TOOLS = [
    {
        "type": "function",
        "function": {"name": "read_file", "parameters": {"type": "object", "properties": {}}},
    }
]


def _conversation() -> list:
    """Turn 1 (finished), then turn 2 in the middle of a tool call."""
    return [
        HumanMessage(content="第一问"),
        AIMessage(
            content="",
            tool_calls=[{"id": "c1", "name": "read_file", "args": {}}],
            additional_kwargs={"reasoning_content": "turn1-step1"},
        ),
        ToolMessage(content="内容", tool_call_id="c1"),
        AIMessage(content="第一问的答案", additional_kwargs={"reasoning_content": "turn1-final"}),
        HumanMessage(content="追问"),
        AIMessage(
            content="",
            tool_calls=[{"id": "c2", "name": "read_file", "args": {}}],
            additional_kwargs={"reasoning_content": "turn2-step1"},
        ),
        ToolMessage(content="内容", tool_call_id="c2"),
        AIMessage(content="没有思考过程的回复"),
    ]


def _assistant_reasoning(payload: dict) -> list:
    return [m.get("reasoning_content", "<absent>") for m in payload["messages"] if m["role"] == "assistant"]


def _vllm() -> ChatOpenAIReasoning:
    return ChatOpenAIReasoning(api_key="k", model="dsv4", base_url="http://10.0.0.3:8000/v1")


def test_tools_request_sends_every_turn_back():
    payload = _vllm()._get_request_payload(_conversation(), tools=TOOLS)

    assert _assistant_reasoning(payload) == ["turn1-step1", "turn1-final", "turn2-step1", "<absent>"]


def test_request_without_tools_sends_nothing():
    payload = _vllm()._get_request_payload(_conversation())

    assert _assistant_reasoning(payload) == ["<absent>"] * 4


def test_openai_compatible_subclasses_inherit_it():
    llm = ChatOpenAICompatible(api_key="k", model="m", base_url="https://example.com/v1")
    payload = llm._get_request_payload(_conversation(), tools=TOOLS)

    assert _assistant_reasoning(payload)[:3] == ["turn1-step1", "turn1-final", "turn2-step1"]


def test_official_openai_endpoint_is_left_alone():
    for llm in (
        ChatOpenAIReasoning(api_key="k", model="m"),
        ChatOpenAIReasoning(api_key="k", model="m", base_url="https://api.openai.com/v1"),
    ):
        payload = llm._get_request_payload(_conversation(), tools=TOOLS)
        assert _assistant_reasoning(payload) == ["<absent>"] * 4


def test_deepseek_fills_every_assistant_message_with_tools():
    llm = CustomChatDeepSeek(api_key="k", model="deepseek-chat", api_base="https://api.deepseek.com")
    payload = llm._get_request_payload(_conversation(), tools=TOOLS)

    assert _assistant_reasoning(payload) == ["turn1-step1", "turn1-final", "turn2-step1", ""]


def test_deepseek_sends_nothing_without_tools():
    llm = CustomChatDeepSeek(api_key="k", model="deepseek-chat", api_base="https://api.deepseek.com")
    payload = llm._get_request_payload(_conversation())

    assert _assistant_reasoning(payload) == ["<absent>"] * 4


def test_streamed_reasoning_survives_merge_and_checkpoint():
    merged = AIMessageChunk(content="", additional_kwargs={"reasoning_content": "先读"}) + AIMessageChunk(
        content="答", additional_kwargs={"reasoning_content": "文件"}
    )
    serde = JsonPlusSerializer()
    restored = serde.loads_typed(serde.dumps_typed(AIMessage(**merged.model_dump(exclude={"type"}))))

    assert restored.additional_kwargs["reasoning_content"] == "先读文件"
