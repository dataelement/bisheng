"""F087 P1: token counting for task-mode compression (design decision 10).

``estimate_tokens`` counts each CJK character as one token and other text at four
characters per token. ``count_context_tokens`` takes the provider-reported total
of the latest model reply as the base and estimates only what came after it.
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from bisheng.linsight.domain.services.context_budget import count_context_tokens, estimate_tokens


def _ai(content="", total=None, tool_calls=None):
    kwargs = {"content": content, "tool_calls": tool_calls or []}
    if total is not None:
        kwargs["usage_metadata"] = {"input_tokens": total - 10, "output_tokens": 10, "total_tokens": total}
    return AIMessage(**kwargs)


def test_chinese_counts_one_token_per_character():
    text = "长文档内容" * 200  # 1000 CJK characters
    estimated = estimate_tokens([HumanMessage(content=text)])

    assert 1000 <= estimated <= 1010  # plus per-message overhead


def test_ascii_counts_four_characters_per_token():
    estimated = estimate_tokens([HumanMessage(content="a" * 4000)])

    assert 1000 <= estimated <= 1010


def test_mixed_text_adds_both_parts():
    estimated = estimate_tokens([HumanMessage(content="中文" * 100 + "ab" * 200)])

    assert 300 <= estimated <= 310  # 200 CJK + 400 ASCII chars / 4


def test_tool_call_arguments_are_counted():
    call = {"name": "write_file", "args": {"content": "报告正文" * 250}, "id": "w"}
    estimated = estimate_tokens([_ai(tool_calls=[call])])

    assert estimated >= 1000


def test_usage_base_plus_only_the_newer_messages():
    messages = [
        SystemMessage(content="system " * 1000),
        HumanMessage(content="问题"),
        _ai(total=50_000, tool_calls=[{"name": "fetch", "args": {}, "id": "f"}]),
        ToolMessage(content="结果" * 1000, tool_call_id="f"),  # 2000 CJK chars, newer than the usage
    ]

    total = count_context_tokens(messages)

    assert 52_000 <= total <= 52_020


def test_without_usage_everything_is_estimated():
    messages = [HumanMessage(content="问题" * 500), _ai(content="回答" * 500)]

    assert count_context_tokens(messages) == estimate_tokens(messages)


def test_synthetic_reply_without_usage_falls_back_to_an_earlier_one():
    messages = [
        HumanMessage(content="q"),
        _ai(total=10_000, tool_calls=[{"name": "task", "args": {}, "id": "t"}]),
        ToolMessage(content="子任务结果" * 100, tool_call_id="t"),
        _ai(content="⚠️ 本步已被跳过"),  # degraded synthetic reply: no usage
    ]

    total = count_context_tokens(messages)

    expected_delta = estimate_tokens(messages[2:])
    assert total == 10_000 + expected_delta


def test_tools_are_estimated_only_without_a_usage_base():
    tools = [{"name": "fetch", "description": "读取" * 100, "parameters": {}}]
    no_base = [HumanMessage(content="q")]
    with_base = [HumanMessage(content="q"), _ai(total=1000)]

    assert count_context_tokens(no_base, tools=tools) > count_context_tokens(no_base)
    # The reported total already includes the tool schemas sent with that call.
    assert count_context_tokens(with_base, tools=tools) == count_context_tokens(with_base)
