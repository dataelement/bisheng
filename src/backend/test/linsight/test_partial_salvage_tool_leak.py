"""Regression: the partial-result salvage must never surface a raw ToolMessage.

Background — session ``af702150…`` (task mode): a run spun in the code-interpreter
loop, hit the LangGraph recursion ceiling (L4), and the partial-result salvage
fell back to ``_last_assistant_text``. That value came from
``_extract_last_message_text``, which used to return ``messages[-1]`` WITHOUT
checking the role. On an abort the trailing message is typically a raw
``bisheng_code_interpreter`` ``ToolMessage`` — a ``{"exitcode":0,"log":
"\\nError: No module named 'pdfminer'\\n=== PDF文本内容(fitz…) ==="}`` blob — so the
apology preamble ended up followed by that raw JSON, shown to the user as
"已完成的分析内容".

Fix: walk backward to the last AIMessage carrying text; skip Tool/Human/System
messages; return None when the model never produced any text (caller then
degrades to a friendly failure instead of dumping tool JSON).
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from bisheng.linsight.domain.task_exec import LinsightWorkflowTask

extract = LinsightWorkflowTask._extract_last_message_text

# The exact code-interpreter blob that leaked in the original case.
_LEAK_BLOB = (
    '{"exitcode": 0, "log": "\\nError: No module named \'pdfminer\'\\n'
    '=== PDF文本内容(fitz, 前3000字) ===\\n油脂油料市场早报 | 数据截止：2026/7/13…"}'
)


def _tool_msg(content: str, name: str = "bisheng_code_interpreter") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id="call_1", name=name)


def test_skips_trailing_tool_message():
    """The core leak: a trailing ToolMessage must not be returned as the answer."""
    messages = [
        HumanMessage(content="连接数据库生成早报"),
        AIMessage(content="我已经完成数据分析，下面生成报告。"),
        _tool_msg(_LEAK_BLOB),
    ]
    assert extract(messages) == "我已经完成数据分析，下面生成报告。"


def test_exact_leak_case_produces_no_raw_json():
    """Replicates the real case; the salvaged text must not contain the raw blob."""
    messages = [
        AIMessage(content="第一章大豆CNF升贴水分析已完成。"),
        AIMessage(content="", tool_calls=[{"name": "bisheng_code_interpreter", "args": {}, "id": "c1"}]),
        _tool_msg(_LEAK_BLOB),
    ]
    result = extract(messages)
    assert result == "第一章大豆CNF升贴水分析已完成。"
    assert "pdfminer" not in (result or "")
    assert "exitcode" not in (result or "")


def test_returns_ai_text_when_last():
    """Regression: a normal run ending in an AIMessage still returns that text."""
    messages = [HumanMessage(content="你好"), AIMessage(content="你好，有什么可以帮你？")]
    assert extract(messages) == "你好，有什么可以帮你？"


def test_skips_toolcall_only_ai_message():
    """An AIMessage with tool_calls but no text is skipped; earlier text wins."""
    messages = [
        AIMessage(content="这是模型真正说的话。"),
        AIMessage(content="", tool_calls=[{"name": "read_file", "args": {}, "id": "r1"}]),
        _tool_msg("file contents..."),
    ]
    assert extract(messages) == "这是模型真正说的话。"


def test_none_when_no_assistant_text():
    """No AIMessage text at all -> None, so the caller degrades to a friendly fail."""
    messages = [
        HumanMessage(content="做点事"),
        AIMessage(content="", tool_calls=[{"name": "bisheng_code_interpreter", "args": {}, "id": "c1"}]),
        _tool_msg(_LEAK_BLOB),
    ]
    assert extract(messages) is None


def test_skips_human_and_system_messages():
    messages = [
        AIMessage(content="早报草稿已生成。"),
        SystemMessage(content="system directive"),
        HumanMessage(content="再改一版"),
    ]
    assert extract(messages) == "早报草稿已生成。"


def test_empty_and_none():
    assert extract([]) is None
    assert extract(None) is None


def test_dict_shaped_messages():
    """Dict-shaped messages: role/type must be honored, tool dict skipped."""
    messages = [
        {"role": "assistant", "content": "字典形态的助手回复"},
        {"role": "tool", "name": "bisheng_code_interpreter", "content": _LEAK_BLOB},
    ]
    assert extract(messages) == "字典形态的助手回复"


def test_dict_shaped_langchain_type_key():
    """LangChain dict serialization uses `type`, not `role`."""
    messages = [
        {"type": "ai", "content": "assistant via type key"},
        {"type": "tool", "content": _LEAK_BLOB},
    ]
    assert extract(messages) == "assistant via type key"


def test_content_block_list():
    """Multimodal/content-block list on an AIMessage is flattened to text."""
    messages = [
        _tool_msg("noise"),
        AIMessage(content=[{"type": "text", "text": "块文本结论"}, {"type": "text", "text": "第二块"}]),
    ]
    assert extract(messages) == "块文本结论第二块"


def test_is_assistant_message_discriminator():
    assert LinsightWorkflowTask._is_assistant_message(AIMessage(content="x")) is True
    assert LinsightWorkflowTask._is_assistant_message(_tool_msg("y")) is False
    assert LinsightWorkflowTask._is_assistant_message(HumanMessage(content="z")) is False
    assert LinsightWorkflowTask._is_assistant_message({"role": "assistant", "content": "a"}) is True
    assert LinsightWorkflowTask._is_assistant_message({"role": "tool", "content": "b"}) is False
