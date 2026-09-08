"""run_react_vision_stream (F061 T019).

Covers AC: AC-02, AC-03, AC-04, AC-06, AC-07, AC-13, AC-16, AC-17
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict

from bisheng.common.image_view import IMAGE_VIEW_PROMPT_RULES, ImageRegistry, annotate
from bisheng.common.image_view.react_loop import REACT_RECURSION_LIMIT, run_react_vision_stream
from bisheng.common.image_view.vision_llm import VisionToolBindWrapper

_DATA_URI = "data:image/png;base64,aaa"

_OPENING_HANDBOOK = """
首钢集团司库系统账户管理模块用户操作手册
![cover](/bisheng/knowledge/images/1/6/image_1_3.jpeg)⟦img#1⟧
1.1.1.开户申请
操作路径：司库管理 银行账户 开户申请（查看已审批的账户开户申请单）
![list](/bisheng/knowledge/images/1/6/image_4_10.jpeg)⟦img#9⟧
点击单据号可查看开户申请详情：
![form](/bisheng/knowledge/images/1/6/image_4_8.jpeg)⟦img#10⟧
1.3.1.销户申请
![close](/bisheng/knowledge/images/1/6/image_10_28.jpeg)⟦img#28⟧
"""


class _SkipGraphLLM:
    def __init__(self):
        self.stream_inputs: list[list] = []
        self.bind_calls: list = []

    def bind_tools(self, tools, **kwargs):
        self.bind_calls.append(list(tools))
        return self

    async def astream(self, messages, **kwargs):
        self.stream_inputs.append(list(messages))
        yield AIMessage(content="plain answer")


class _FakeVisionModel(BaseChatModel):
    """First turn: tool_calls or prose. After a ToolMessage: final answer."""

    model_config = ConfigDict(extra="allow")

    def __init__(self, first: AIMessage, second: AIMessage | None = None):
        super().__init__()
        self.first = first
        self.second = second or AIMessage(content="The chart goes up.")
        self.bind_kwargs: list[dict] = []
        self.generate_inputs: list[list[BaseMessage]] = []

    @property
    def _llm_type(self) -> str:
        return "fake-vision-react"

    def bind_tools(self, tools, **kwargs):
        self.bind_kwargs.append(dict(kwargs))
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.generate_inputs.append(list(messages))
        if any(isinstance(message, ToolMessage) for message in messages):
            msg = self.second
        else:
            msg = self.first
        return ChatResult(generations=[ChatGeneration(message=msg)])


def _registry_one() -> ImageRegistry:
    registry = ImageRegistry()
    annotate("see ![chart](/bisheng/knowledge/images/1/2/chart.png)", registry)
    return registry


def _trend_messages() -> list:
    return [
        SystemMessage(content="base system"),
        HumanMessage(content="这张图的走势 see ![chart](/bisheng/knowledge/images/1/2/chart.png)⟦img#1⟧"),
    ]


def _numbered_registry(count: int) -> ImageRegistry:
    registry = ImageRegistry()
    for index in range(1, count + 1):
        registry.register(f"/bisheng/knowledge/images/1/6/image_{index}.png")
    return registry


@pytest.fixture
def mock_fetch(monkeypatch):
    result = type("R", (), {"ok": True, "data_uri": _DATA_URI, "error": None})()
    fetch = AsyncMock(return_value=result)
    monkeypatch.setattr("bisheng.common.image_view.tool.fetch_and_encode", fetch)
    return fetch


def test_recursion_limit_is_eight():
    assert REACT_RECURSION_LIMIT == 8


async def test_visual_false_skips_graph(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("should not build graph")

    monkeypatch.setattr("bisheng.common.image_view.react_loop.create_react_agent", boom)
    llm = _SkipGraphLLM()
    yielded: list[str] = []
    async for chunk in run_react_vision_stream(llm, _trend_messages(), _registry_one(), visual=False):
        yielded.append(getattr(chunk, "content", "") or "")
    assert yielded == ["plain answer"]
    assert llm.bind_calls == []


async def test_empty_registry_skips_graph(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("should not build graph")

    monkeypatch.setattr("bisheng.common.image_view.react_loop.create_react_agent", boom)
    llm = _SkipGraphLLM()
    async for _ in run_react_vision_stream(
        llm, [SystemMessage(content="sys"), HumanMessage(content="hi")], ImageRegistry(), visual=True
    ):
        pass
    assert llm.bind_calls == []
    assert IMAGE_VIEW_PROMPT_RULES not in str(llm.stream_inputs[0][0].content)


async def test_tool_call_round_hides_prose_and_attaches_pixels(mock_fetch, monkeypatch):
    captured: dict = {}
    real_create = __import__("bisheng.common.image_view.react_loop", fromlist=["create_react_agent"]).create_react_agent

    def wrap_create(*args, **kwargs):
        agent = real_create(*args, **kwargs)
        original = agent.astream_events

        async def spy(inp, version="v2", config=None, **kw):
            captured["config"] = config
            async for event in original(inp, version=version, config=config, **kw):
                yield event

        agent.astream_events = spy
        return agent

    monkeypatch.setattr("bisheng.common.image_view.react_loop.create_react_agent", wrap_create)

    llm = _FakeVisionModel(
        first=AIMessage(
            content="calling tool",
            tool_calls=[
                {
                    "name": "view_image",
                    "args": {"image_ids": ["img#1"], "quality": "standard"},
                    "id": "call_1",
                    "type": "tool_call",
                }
            ],
        ),
        second=AIMessage(content="The chart goes up. ![](/bisheng/knowledge/images/1/2/chart.png)"),
    )
    yielded: list[str] = []
    async for chunk in run_react_vision_stream(llm, _trend_messages(), _registry_one(), visual=True):
        yielded.append(getattr(chunk, "content", "") or "")

    joined = "".join(yielded)
    assert "calling tool" not in joined
    assert joined.count("The chart goes up.") == 1
    assert captured["config"]["recursion_limit"] == 8
    second = next(inputs for inputs in llm.generate_inputs if any(isinstance(m, ToolMessage) for m in inputs))
    dumped = repr(second)
    humans = [m for m in second if isinstance(m, HumanMessage) and isinstance(m.content, list)]
    assert humans
    image_blocks = [b for b in humans[-1].content if isinstance(b, dict) and b.get("type") == "image_url"]
    assert image_blocks
    assert image_blocks[0]["image_url"]["url"] == _DATA_URI
    first = llm.generate_inputs[0]
    assert "data:image" not in repr(first)
    assert "⟦img#1⟧" in repr(first)


async def test_ignored_tool_choice_injects_and_hides_prose(mock_fetch):
    llm = _FakeVisionModel(
        first=AIMessage(content="guessed fields from the surrounding handbook text"),
        second=AIMessage(content="fields from the form screenshot"),
    )
    messages = [
        SystemMessage(content="base system"),
        HumanMessage(content=f"{_OPENING_HANDBOOK}\n# 用户问题\n```\n开户申请表单上有哪些字段？\n```"),
    ]
    yielded: list[str] = []
    async for chunk in run_react_vision_stream(llm, messages, _numbered_registry(28), visual=True):
        yielded.append(getattr(chunk, "content", "") or "")

    joined = "".join(yielded)
    assert "guessed fields" not in joined
    assert joined.count("fields from the form screenshot") == 1
    mock_fetch.assert_awaited()
    first_ai = next(m for inputs in llm.generate_inputs for m in inputs if isinstance(m, AIMessage) and m.tool_calls)
    ids = first_ai.tool_calls[0]["args"]["image_ids"]
    assert "img#1" not in ids
    assert any(image_id in ids for image_id in ("img#9", "img#10"))


async def test_after_view_plain_text_is_not_injected(mock_fetch):
    llm = _FakeVisionModel(
        first=AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "view_image",
                    "args": {"image_ids": ["img#1"], "quality": "standard"},
                    "id": "call_1",
                    "type": "tool_call",
                }
            ],
        ),
        second=AIMessage(content="final answer after viewing"),
    )
    yielded: list[str] = []
    async for chunk in run_react_vision_stream(llm, _trend_messages(), _registry_one(), visual=True):
        yielded.append(getattr(chunk, "content", "") or "")
    joined = "".join(yielded)
    assert joined.count("final answer after viewing") == 1
    # Trend / field questions view pixels but must not paste the screenshot.
    assert "chart.png" not in joined
    assert len([inp for inp in llm.generate_inputs if any(isinstance(m, ToolMessage) for m in inp)]) == 1
    # Second model turn is the answer; no extra inject round after that.
    answer_turns = [inp for inp in llm.generate_inputs if any(isinstance(m, ToolMessage) for m in inp)]
    last = answer_turns[-1]
    assert not any(
        isinstance(m, AIMessage) and m.tool_calls and getattr(m, "id", None) == "view_image_forced" for m in last
    )


async def test_after_view_splices_markdown_when_user_asks_to_show(mock_fetch):
    llm = _FakeVisionModel(
        first=AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "view_image",
                    "args": {"image_ids": ["img#1"], "quality": "standard"},
                    "id": "call_1",
                    "type": "tool_call",
                }
            ],
        ),
        second=AIMessage(content="我将显示开户登记相关截图。"),
    )
    messages = [
        SystemMessage(content="base system"),
        HumanMessage(content="把开户登记界面说明相关的图片显示出来"),
    ]
    yielded: list[str] = []
    async for chunk in run_react_vision_stream(llm, messages, _registry_one(), visual=True):
        yielded.append(getattr(chunk, "content", "") or "")
    joined = "".join(yielded)
    assert "我将显示开户登记相关截图。" in joined
    assert "chart.png](/bisheng/knowledge/images/1/2/chart.png)" in joined


async def test_stream_deltas_are_not_repeated_by_chain_end(monkeypatch):
    """Knowledge-space concatenates every yielded chunk; full-message replay duplicates the answer."""

    events = [
        {"event": "on_chat_model_start", "name": "ChatOpenAI", "data": {}},
        {
            "event": "on_chat_model_stream",
            "name": "ChatOpenAI",
            "data": {"chunk": AIMessageChunk(content="根据提供的参考资料，开户申请表单的图片是 img#4。")},
        },
        {
            "event": "on_chat_model_stream",
            "name": "ChatOpenAI",
            "data": {"chunk": AIMessageChunk(content="该图片位于开户登记章节中。")},
        },
        {
            "event": "on_chat_model_end",
            "name": "ChatOpenAI",
            "data": {
                "output": AIMessage(
                    content="根据提供的参考资料，开户申请表单的图片是 img#4。该图片位于开户登记章节中。"
                )
            },
        },
        {
            "event": "on_chain_end",
            "name": "_VisionCallRunnable",
            "data": {
                "output": AIMessage(
                    content="根据提供的参考资料，开户申请表单的图片是 img#4。该图片位于开户登记章节中。"
                )
            },
        },
    ]

    class _FakeAgent:
        async def astream_events(self, *args, **kwargs):
            for event in events:
                yield event

    monkeypatch.setattr(
        "bisheng.common.image_view.react_loop.create_react_agent",
        lambda *args, **kwargs: _FakeAgent(),
    )
    monkeypatch.setattr(
        "bisheng.common.image_view.react_loop.ToolNode",
        lambda *args, **kwargs: object(),
    )

    yielded: list[str] = []
    async for chunk in run_react_vision_stream(_SkipGraphLLM(), _trend_messages(), _registry_one(), visual=True):
        yielded.append(getattr(chunk, "content", "") or "")
    joined = "".join(yielded)
    assert joined == "根据提供的参考资料，开户申请表单的图片是 img#4。该图片位于开户登记章节中。"


async def test_wrapper_is_not_runnable():
    from langchain_core.runnables import Runnable

    wrapper = VisionToolBindWrapper(_SkipGraphLLM(), ImageRegistry(), [])
    assert not isinstance(wrapper, Runnable)
