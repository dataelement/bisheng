"""Behavioral tests for the provider-specific ChatModels extracted out of
BishengLLM: ChatQwen (VL content flattening), ChatMinimax / ChatMoonshot
(builtin web-search), and ChatMoonshot's web-search tool-call feedback loop.

These run fully offline — payload assembly and the loop are tested without any
network call by inspecting `_get_request_payload` and by patching the inner
`ChatOpenAI._generate`.
"""

from unittest import mock

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI

from bisheng.core.ai import ChatMinimax, ChatMoonshot, ChatQwen
from bisheng.core.ai.llm.chat_qwen import _flatten_qwen_content

_COMMON = dict(model="test-model", api_key="k", base_url="http://localhost/v1", streaming=False)


# --- ChatQwen ---------------------------------------------------------------


def test_qwen_flattens_list_content():
    msg = AIMessage(content=[{"type": "text", "text": "hello "}, {"type": "text", "text": "world"}])
    _flatten_qwen_content(msg)
    assert msg.content == "hello world"


def test_qwen_leaves_string_content_untouched():
    msg = AIMessage(content="plain string")
    _flatten_qwen_content(msg)
    assert msg.content == "plain string"


def test_qwen_create_chat_result_flattens():
    llm = ChatQwen(**_COMMON)
    raw = ChatResult(
        generations=[
            ChatGeneration(message=AIMessage(content=[{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]))
        ]
    )
    with mock.patch.object(ChatOpenAI, "_create_chat_result", return_value=raw):
        result = llm._create_chat_result({})
    assert result.generations[0].message.content == "ab"


# --- ChatMinimax web search -------------------------------------------------


def test_minimax_injects_web_search_when_enabled():
    llm = ChatMinimax(enable_web_search=True, **_COMMON)
    payload = llm._get_request_payload([HumanMessage("hi")])
    assert {"type": "web_search"} in payload["tools"]


def test_minimax_no_web_search_when_disabled():
    llm = ChatMinimax(enable_web_search=False, **_COMMON)
    payload = llm._get_request_payload([HumanMessage("hi")])
    assert "tools" not in payload or all(t.get("type") != "web_search" for t in payload["tools"])


def test_minimax_does_not_duplicate_web_search():
    llm = ChatMinimax(enable_web_search=True, **_COMMON)
    bound = llm.bind(tools=[{"type": "web_search"}])
    payload = llm._get_request_payload([HumanMessage("hi")], tools=[{"type": "web_search"}])
    assert sum(1 for t in payload["tools"] if t.get("type") == "web_search") == 1
    del bound


# --- ChatMoonshot web search ------------------------------------------------


def test_moonshot_injects_builtin_web_search_when_enabled():
    llm = ChatMoonshot(enable_web_search=True, **_COMMON)
    payload = llm._get_request_payload([HumanMessage("hi")])
    assert any(
        t.get("type") == "builtin_function" and t.get("function", {}).get("name") == "$web_search"
        for t in payload["tools"]
    )


def test_moonshot_no_tool_when_disabled():
    llm = ChatMoonshot(enable_web_search=False, **_COMMON)
    payload = llm._get_request_payload([HumanMessage("hi")])
    assert "tools" not in payload or all(t.get("type") != "builtin_function" for t in payload["tools"])


def _ws_tool_call_result():
    return ChatResult(
        generations=[
            ChatGeneration(
                message=AIMessage(
                    content="",
                    tool_calls=[{"name": "$web_search", "args": {"q": "x"}, "id": "tc1", "type": "tool_call"}],
                ),
                generation_info={"finish_reason": "tool_calls"},
            )
        ]
    )


def _final_result():
    return ChatResult(
        generations=[
            ChatGeneration(
                message=AIMessage(content="final answer"),
                generation_info={"finish_reason": "stop"},
            )
        ]
    )


def test_moonshot_web_search_loop_feeds_tool_results_and_returns_final():
    llm = ChatMoonshot(enable_web_search=True, **_COMMON)
    seen_message_counts = []

    def fake_generate(self, messages, stop=None, run_manager=None, **kwargs):
        seen_message_counts.append(len(messages))
        # First round asks for web search; second round returns the answer.
        return _ws_tool_call_result() if len(seen_message_counts) == 1 else _final_result()

    with mock.patch.object(ChatOpenAI, "_generate", new=fake_generate):
        result = llm._generate([HumanMessage("search please")])

    assert result.generations[0].message.content == "final answer"
    # Two inner calls: the second one must include the appended assistant+tool messages.
    assert seen_message_counts == [1, 3]


def test_moonshot_no_loop_when_web_search_disabled():
    llm = ChatMoonshot(enable_web_search=False, **_COMMON)
    calls = []

    def fake_generate(self, messages, stop=None, run_manager=None, **kwargs):
        calls.append(len(messages))
        return _final_result()

    with mock.patch.object(ChatOpenAI, "_generate", new=fake_generate):
        result = llm._generate([HumanMessage("hi")])

    assert result.generations[0].message.content == "final answer"
    assert calls == [1]  # single passthrough, no loop
