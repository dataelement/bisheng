"""Unit tests for run_vision_tool_loop and relocate (F061 T007).

Covers AC: AC-04, AC-06, AC-07, AC-13, AC-16, AC-17
"""

from __future__ import annotations

import re
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage

from bisheng.common.image_view import ImageRegistry, annotate
from bisheng.common.image_view.loop import IMAGE_VIEW_PROMPT_RULES, run_vision_tool_loop, suggest_image_ids
from bisheng.common.image_view.relocate import relocate_images_to_human

_DATA_URI = "data:image/png;base64,aaa"


class FakeLLM:
    def __init__(self, first: AIMessage, second: AIMessage | None = None):
        self.first = first
        self.second = second
        self.bind_calls: list[list] = []
        self.bind_kwargs: list[dict] = []
        self.stream_inputs: list[list] = []
        self._bound = False

    def bind_tools(self, tools, **kwargs):
        self.bind_calls.append(list(tools))
        self.bind_kwargs.append(dict(kwargs))
        bound = type(self)(self.first, self.second)
        bound.bind_calls = self.bind_calls
        bound.bind_kwargs = self.bind_kwargs
        bound.stream_inputs = self.stream_inputs
        bound._bound = True
        bound._parent = self
        return bound

    async def astream(self, messages, **kwargs):
        owner = getattr(self, "_parent", None) or self
        owner.stream_inputs.append(list(messages))
        if self._bound:
            yield self.first
            return
        yield self.second or AIMessage(content="plain answer")


def _registry() -> ImageRegistry:
    registry = ImageRegistry()
    annotate("see ![chart](/bisheng/knowledge/images/1/2/chart.png)", registry)
    return registry


def _messages() -> list:
    return [
        SystemMessage(content="base system"),
        HumanMessage(content="What is the trend? see ![chart](/bisheng/knowledge/images/1/2/chart.png)⟦img#1⟧"),
    ]


@pytest.fixture
def mock_fetch(monkeypatch):
    result = type("R", (), {"ok": True, "data_uri": _DATA_URI, "error": None})()
    fetch = AsyncMock(return_value=result)
    monkeypatch.setattr("bisheng.common.image_view.tool.fetch_and_encode", fetch)
    return fetch


@pytest.mark.asyncio
async def test_tool_call_round_has_no_pixels_and_does_not_yield_first_content(mock_fetch):
    llm = FakeLLM(
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
        second=AIMessage(content="The chart goes up."),
    )
    yielded: list[str] = []
    async for chunk in run_vision_tool_loop(llm, _messages(), _registry(), visual=True):
        yielded.append(getattr(chunk, "content", "") or "")

    assert yielded == ["The chart goes up."]
    assert len(llm.stream_inputs) == 2
    first_round = llm.stream_inputs[0]
    dumped = repr(first_round)
    assert "data:image" not in dumped
    assert "⟦img#1⟧" in dumped
    assert IMAGE_VIEW_PROMPT_RULES in first_round[0].content
    assert "![](url)" in first_round[0].content

    second_round = llm.stream_inputs[1]
    assert any(isinstance(m, ToolMessage) and "Viewed img#1" in str(m.content) for m in second_round)
    ai_with_tools = [m for m in second_round if isinstance(m, AIMessage) and m.tool_calls]
    assert ai_with_tools
    assert ai_with_tools[0].content == ""
    humans = [m for m in second_round if isinstance(m, HumanMessage) and isinstance(m.content, list)]
    assert humans
    image_blocks = [b for b in humans[-1].content if isinstance(b, dict) and b.get("type") == "image_url"]
    assert image_blocks
    assert image_blocks[0]["image_url"]["url"] == _DATA_URI
    assert any("What is the trend?" in str(m.content) for m in second_round)
    assert len(llm.bind_calls) == 1


@pytest.mark.asyncio
async def test_visual_false_is_single_round_without_bind_or_rules():
    llm = FakeLLM(first=AIMessage(content="no vision"))
    yielded: list[str] = []
    async for chunk in run_vision_tool_loop(llm, _messages(), _registry(), visual=False):
        yielded.append(chunk.content)

    assert yielded == ["plain answer"]
    assert llm.bind_calls == []
    assert IMAGE_VIEW_PROMPT_RULES not in str(llm.stream_inputs[0][0].content)


@pytest.mark.asyncio
async def test_empty_registry_skips_bind_and_rules():
    llm = FakeLLM(first=AIMessage(content="no images"))
    async for _ in run_vision_tool_loop(
        llm, [SystemMessage(content="sys"), HumanMessage(content="hi")], ImageRegistry(), visual=True
    ):
        pass

    assert llm.bind_calls == []
    assert IMAGE_VIEW_PROMPT_RULES not in str(llm.stream_inputs[0][0].content)


def test_relocate_moves_image_blocks_off_tool_message():
    messages = [
        HumanMessage(content="question"),
        ToolMessage(
            content=[
                {"type": "text", "text": "ack"},
                {"type": "image_url", "image_url": {"url": _DATA_URI}},
            ],
            tool_call_id="call_1",
        ),
    ]
    out = relocate_images_to_human(messages)
    tool = next(m for m in out if isinstance(m, ToolMessage))
    assert tool.content == "ack"
    humans = [m for m in out if isinstance(m, HumanMessage)]
    assert any(
        isinstance(m.content, list) and any(b.get("type") == "image_url" for b in m.content if isinstance(b, dict))
        for m in humans
    )
    assert not any(
        isinstance(m, ToolMessage) and isinstance(m.content, list) and any(_is_image(b) for b in m.content) for m in out
    )


def _is_image(block: object) -> bool:
    return isinstance(block, dict) and block.get("type") in {"image_url", "image"}


class _StreamToolCallLLM(FakeLLM):
    """First bound round yields token-delta tool_call_chunks; second round is a full answer."""

    async def astream(self, messages, **kwargs):
        owner = getattr(self, "_parent", None) or self
        owner.stream_inputs.append(list(messages))
        if self._bound:
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": "view_image",
                        "args": "",
                        "id": "call_1",
                        "index": 0,
                        "type": "tool_call_chunk",
                    }
                ],
            )
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": None,
                        "args": '{"image_ids": ["img#1"], "quality": "standard"}',
                        "id": None,
                        "index": 0,
                        "type": "tool_call_chunk",
                    }
                ],
            )
            return
        yield self.second or AIMessage(content="The chart goes up.")


@pytest.mark.asyncio
async def test_streamed_tool_call_chunks_are_merged_before_invoke(mock_fetch):
    llm = _StreamToolCallLLM(first=AIMessage(content=""), second=AIMessage(content="The chart goes up."))
    yielded: list[str] = []
    async for chunk in run_vision_tool_loop(llm, _messages(), _registry(), visual=True):
        yielded.append(getattr(chunk, "content", "") or "")

    assert yielded == ["The chart goes up."]
    mock_fetch.assert_awaited_once()
    second_round = llm.stream_inputs[1]
    assert any(isinstance(m, ToolMessage) and "Viewed img#1" in str(m.content) for m in second_round)


@pytest.mark.asyncio
async def test_empty_tool_args_do_not_abort_the_stream(mock_fetch):
    llm = FakeLLM(
        first=AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "view_image",
                    "args": {},
                    "id": "call_1",
                    "type": "tool_call",
                }
            ],
        ),
        second=AIMessage(content="answered without pixels"),
    )
    yielded: list[str] = []
    async for chunk in run_vision_tool_loop(llm, _messages(), _registry(), visual=True):
        yielded.append(getattr(chunk, "content", "") or "")

    assert yielded == ["answered without pixels"]
    mock_fetch.assert_not_called()
    second_round = llm.stream_inputs[1]
    assert any(isinstance(m, ToolMessage) and "image_ids" in str(m.content) for m in second_round)


@pytest.mark.asyncio
async def test_string_image_ids_are_coerced_to_list(mock_fetch):
    llm = FakeLLM(
        first=AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "view_image",
                    "args": {"image_ids": "img#1"},
                    "id": "call_1",
                    "type": "tool_call",
                }
            ],
        ),
        second=AIMessage(content="ok"),
    )
    async for _ in run_vision_tool_loop(llm, _messages(), _registry(), visual=True):
        pass

    mock_fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_screenshot_question_forces_view_image_tool_choice(mock_fetch):
    llm = FakeLLM(
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
        second=AIMessage(content="fields from the screenshot"),
    )
    messages = [
        SystemMessage(content="base system"),
        HumanMessage(content="# 用户问题\n```\n开户申请那张界面截图里，表单上有哪些字段？\n```"),
    ]
    async for _ in run_vision_tool_loop(llm, messages, _registry(), visual=True):
        pass

    assert llm.bind_kwargs
    assert llm.bind_kwargs[0].get("tool_choice") == {
        "type": "function",
        "function": {"name": "view_image"},
    }


@pytest.mark.asyncio
async def test_plain_summary_question_does_not_force_tool_choice(mock_fetch):
    llm = FakeLLM(first=AIMessage(content="the doc is a handbook"))
    messages = [
        SystemMessage(content="base system"),
        HumanMessage(content="# 用户问题\n```\n这篇文档写了啥？\n```"),
    ]
    async for _ in run_vision_tool_loop(llm, messages, _registry(), visual=True):
        pass

    assert llm.bind_kwargs
    assert "tool_choice" not in llm.bind_kwargs[0]


@pytest.mark.asyncio
async def test_image_catalog_history_is_dropped_from_first_round(mock_fetch):
    llm = FakeLLM(first=AIMessage(content="answer"))
    catalog = "\n".join(f"### img#{i} — guessed caption" for i in range(1, 8))
    messages = [
        SystemMessage(content="base system"),
        HumanMessage(content="文档中的图片写了啥？"),
        AIMessage(content=catalog),
        HumanMessage(content="这篇文档写了啥？ see ![chart](/bisheng/knowledge/images/1/2/chart.png)⟦img#1⟧"),
    ]
    async for _ in run_vision_tool_loop(llm, messages, _registry(), visual=True):
        pass

    first_round = llm.stream_inputs[0]
    assert not any(isinstance(m, AIMessage) and "img#1" in str(m.content) for m in first_round)
    assert any(isinstance(m, HumanMessage) and "这篇文档写了啥" in str(m.content) for m in first_round)


@pytest.mark.asyncio
async def test_short_img_mention_history_dropped_when_question_needs_pixels(mock_fetch):
    llm = FakeLLM(first=AIMessage(content="answer"))
    messages = [
        SystemMessage(content="base system"),
        HumanMessage(content="开户申请那张界面截图里，表单上有哪些字段？"),
        AIMessage(content="根据截图（img#1），该图片仅显示标志，建议查看 img#7。"),
        HumanMessage(content="# 用户问题\n```\n开户申请表单上有哪些字段？\n```"),
    ]
    async for _ in run_vision_tool_loop(llm, messages, _registry(), visual=True):
        pass

    first_round = llm.stream_inputs[0]
    assert not any(isinstance(m, AIMessage) and "img#" in str(m.content) for m in first_round)


_OPENING_HANDBOOK = """
首钢集团司库系统账户管理模块用户操作手册
![cover](/bisheng/knowledge/images/1/6/image_1_3.jpeg)⟦img#1⟧
![logo](/bisheng/knowledge/images/1/6/image_1_1.jpeg)⟦img#2⟧
目录
1.1.1 开户申请..................................................................1

1.1.1.开户申请
成员单位去合作金融机构开立账户前，需提交账户申请。经办人在账户开户申请界面可查询单据。
管控要点：
![ctrl](/bisheng/knowledge/images/1/6/image_3_4.jpeg)⟦img#4⟧
操作路径：司库管理 事项申请
![path](/bisheng/knowledge/images/1/6/image_4_9.jpeg)⟦img#6⟧
操作路径：司库管理 银行账户 开户申请（查看已审批的账户开户申请单）
![list](/bisheng/knowledge/images/1/6/image_4_10.jpeg)⟦img#9⟧
点击单据号可查看开户申请详情：
![form](/bisheng/knowledge/images/1/6/image_4_8.jpeg)⟦img#10⟧

1.1.2.开户登记
选中单据点击待登记，检查登记表单信息，点击保存并提交：
![register](/bisheng/knowledge/images/1/6/image_6_14.jpeg)⟦img#14⟧

1.3.1.销户申请
经办人在账户销户申请界面可查询单据。
操作路径：司库管理 银行账户 销户申请
![close](/bisheng/knowledge/images/1/6/image_10_28.jpeg)⟦img#28⟧
"""


def test_suggest_image_ids_prefers_heading_near_question_not_cover():
    question = "开户申请那张界面截图里，表单上有哪些字段？"
    suggested = suggest_image_ids(_OPENING_HANDBOOK, question)
    assert suggested
    assert "img#1" not in suggested
    assert "img#2" not in suggested
    assert any(image_id in suggested for image_id in ("img#6", "img#9", "img#10"))


@pytest.mark.asyncio
async def test_screenshot_question_hints_matching_image_ids(mock_fetch):
    llm = FakeLLM(first=AIMessage(content="the doc is a handbook"))
    messages = [
        SystemMessage(content="base system"),
        HumanMessage(content=f"{_OPENING_HANDBOOK}\n# 用户问题\n```\n开户申请那张界面截图里，表单上有哪些字段？\n```"),
    ]
    async for _ in run_vision_tool_loop(llm, messages, _registry(), visual=True):
        pass

    system = llm.stream_inputs[0][0].content
    assert "本题附近标题更匹配的图片：" in system
    hinted_ids = re.findall(r"img#\d+", system.split("本题附近标题更匹配的图片：", 1)[-1].split("。", 1)[0])
    assert "img#1" not in hinted_ids
    assert any(token in hinted_ids for token in ("img#6", "img#9", "img#10"))
    assert "img#28" not in hinted_ids


def test_suggest_image_ids_does_not_rank_unrelated_close_account_section():
    question = "开户申请表单上有哪些字段？"
    suggested = suggest_image_ids(_OPENING_HANDBOOK, question)
    assert "img#28" not in suggested
    assert any(image_id in suggested for image_id in ("img#9", "img#10"))


def _numbered_registry(count: int) -> ImageRegistry:
    registry = ImageRegistry()
    for index in range(1, count + 1):
        registry.register(f"/bisheng/knowledge/images/1/6/image_{index}.png")
    return registry


def _tool_call_ids(message: AIMessage) -> list[str]:
    call = message.tool_calls[0]
    args = call["args"] if isinstance(call, dict) else call.get("args")
    return list(args.get("image_ids") or [])


@pytest.mark.asyncio
async def test_forced_view_overrides_wrong_image_ids_and_blanks_first_prose(mock_fetch):
    llm = FakeLLM(
        first=AIMessage(
            content="hallucinated field list from surrounding text",
            tool_calls=[
                {
                    "name": "view_image",
                    "args": {"image_ids": ["img#7", "img#8"], "quality": "standard"},
                    "id": "call_1",
                    "type": "tool_call",
                }
            ],
        ),
        second=AIMessage(content="fields from the form screenshot"),
    )
    messages = [
        SystemMessage(content="base system"),
        HumanMessage(content=f"{_OPENING_HANDBOOK}\n# 用户问题\n```\n开户申请表单上有哪些字段？\n```"),
    ]
    async for _ in run_vision_tool_loop(llm, messages, _numbered_registry(28), visual=True):
        pass

    second_round = llm.stream_inputs[1]
    ai = next(m for m in second_round if isinstance(m, AIMessage) and m.tool_calls)
    assert ai.content == ""
    ids = _tool_call_ids(ai)
    assert "img#7" not in ids
    assert "img#8" not in ids
    assert "img#1" not in ids
    assert "img#28" not in ids
    assert any(image_id in ids for image_id in ("img#6", "img#9", "img#10"))
    assert "hallucinated field list" not in str(second_round)


@pytest.mark.asyncio
async def test_ignored_tool_choice_injects_suggested_view_and_hides_first_prose(mock_fetch):
    llm = FakeLLM(
        first=AIMessage(content="guessed fields from the surrounding handbook text"),
        second=AIMessage(content="fields from the form screenshot"),
    )
    messages = [
        SystemMessage(content="base system"),
        HumanMessage(content=f"{_OPENING_HANDBOOK}\n# 用户问题\n```\n开户申请表单上有哪些字段？\n```"),
    ]
    yielded: list[str] = []
    async for chunk in run_vision_tool_loop(llm, messages, _numbered_registry(28), visual=True):
        yielded.append(getattr(chunk, "content", "") or "")

    assert yielded == ["fields from the form screenshot"]
    assert "guessed fields" not in "".join(yielded)
    assert len(llm.stream_inputs) == 2
    mock_fetch.assert_awaited()
    ai = next(m for m in llm.stream_inputs[1] if isinstance(m, AIMessage) and m.tool_calls)
    ids = _tool_call_ids(ai)
    assert "img#1" not in ids
    assert any(image_id in ids for image_id in ("img#6", "img#9", "img#10"))
