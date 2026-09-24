"""run_react_vision_stream (F061 T019).

Covers AC: AC-02, AC-03, AC-04, AC-06, AC-07, AC-13, AC-16, AC-17
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage

from bisheng.common.image_view import IMAGE_VIEW_PROMPT_RULES, ImageRegistry, annotate
from bisheng.common.image_view.react_loop import (
    REACT_RECURSION_LIMIT,
    _strip_picture_citations,
    cited_ids_on_shown_lines,
    run_react_vision_stream,
    strip_view_narration,
)
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


class _VisionStream:
    def __init__(self, parts: list[str]):
        self.parts = parts
        self.inputs: list[list] = []

    async def astream(self, messages, **kwargs):
        self.inputs.append(list(messages))
        for part in self.parts:
            yield AIMessageChunk(content=part)


def _bind_vision(monkeypatch, model: _VisionStream) -> None:
    async def _resolve(*args, **kwargs):
        del args, kwargs
        return model

    monkeypatch.setattr("bisheng.common.image_view.react_loop.resolve_image_view_llm", _resolve)


@pytest.fixture
def mock_fetch(monkeypatch):
    result = type("R", (), {"ok": True, "data_uri": _DATA_URI, "error": None, "reason": None})()
    fetch = AsyncMock(return_value=result)
    monkeypatch.setattr("bisheng.common.image_view.react_loop.fetch_and_encode", fetch)
    return fetch


def test_recursion_limit_is_eight():
    assert REACT_RECURSION_LIMIT == 8


async def test_visual_false_skips_configured_model(monkeypatch):
    async def _boom(*args, **kwargs):
        raise AssertionError("should not resolve the image view model")

    monkeypatch.setattr("bisheng.common.image_view.react_loop.resolve_image_view_llm", _boom)
    llm = _SkipGraphLLM()
    yielded: list[str] = []
    async for chunk in run_react_vision_stream(llm, _trend_messages(), _registry_one(), visual=False):
        yielded.append(getattr(chunk, "content", "") or "")
    assert yielded == ["plain answer"]
    assert llm.bind_calls == []


async def test_empty_registry_skips_configured_model(monkeypatch):
    async def _boom(*args, **kwargs):
        raise AssertionError("should not resolve the image view model")

    monkeypatch.setattr("bisheng.common.image_view.react_loop.resolve_image_view_llm", _boom)
    llm = _SkipGraphLLM()
    async for _ in run_react_vision_stream(
        llm, [SystemMessage(content="sys"), HumanMessage(content="hi")], ImageRegistry(), visual=True
    ):
        pass
    assert llm.bind_calls == []
    assert IMAGE_VIEW_PROMPT_RULES not in str(llm.stream_inputs[0][0].content)


async def test_unconfigured_tool_streams_chat_model(mock_fetch, monkeypatch):
    async def _none(*args, **kwargs):
        del args, kwargs
        return None

    monkeypatch.setattr("bisheng.common.image_view.react_loop.resolve_image_view_llm", _none)
    llm = _SkipGraphLLM()
    yielded: list[str] = []
    async for chunk in run_react_vision_stream(llm, _trend_messages(), _registry_one(), visual=True):
        yielded.append(getattr(chunk, "content", "") or "")
    assert yielded == ["plain answer"]
    mock_fetch.assert_not_awaited()


async def test_configured_model_receives_pixels(mock_fetch, monkeypatch):
    vision = _VisionStream(["The chart goes up. ![](/bisheng/knowledge/images/1/2/chart.png)"])
    _bind_vision(monkeypatch, vision)
    yielded: list[str] = []
    async for chunk in run_react_vision_stream(_SkipGraphLLM(), _trend_messages(), _registry_one(), visual=True):
        yielded.append(getattr(chunk, "content", "") or "")
    joined = "".join(yielded)
    assert joined.count("The chart goes up.") == 1
    mock_fetch.assert_awaited()
    humans = [m for m in vision.inputs[0] if isinstance(m, HumanMessage) and isinstance(m.content, list)]
    image_blocks = [b for b in humans[-1].content if isinstance(b, dict) and b.get("type") == "image_url"]
    assert image_blocks[0]["image_url"]["url"] == _DATA_URI


async def test_configured_model_views_caption_matches(mock_fetch, monkeypatch):
    vision = _VisionStream(["fields from the form screenshot"])
    _bind_vision(monkeypatch, vision)
    messages = [
        SystemMessage(content="base system"),
        HumanMessage(content=f"{_OPENING_HANDBOOK}\n# 用户问题\n```\n开户申请表单上有哪些字段？\n```"),
    ]
    yielded: list[str] = []
    async for chunk in run_react_vision_stream(_SkipGraphLLM(), messages, _numbered_registry(28), visual=True):
        yielded.append(getattr(chunk, "content", "") or "")
    assert "".join(yielded) == "fields from the form screenshot"
    urls = [call.args[0] for call in mock_fetch.await_args_list]
    assert any(url.endswith("image_9.png") or url.endswith("image_10.png") for url in urls)
    assert all(not url.endswith("image_1.png") for url in urls)


async def test_trend_answer_does_not_splice_screenshot(mock_fetch, monkeypatch):
    vision = _VisionStream(["final answer after viewing"])
    _bind_vision(monkeypatch, vision)
    yielded: list[str] = []
    async for chunk in run_react_vision_stream(_SkipGraphLLM(), _trend_messages(), _registry_one(), visual=True):
        yielded.append(getattr(chunk, "content", "") or "")
    joined = "".join(yielded)
    assert joined == "final answer after viewing"
    assert "chart.png" not in joined


async def test_claimed_display_splices_the_single_viewed_image(mock_fetch, monkeypatch):
    vision = _VisionStream(["我将显示开户登记相关截图。"])
    _bind_vision(monkeypatch, vision)
    messages = [
        SystemMessage(content="base system"),
        HumanMessage(content="把开户登记界面说明相关的图片显示出来"),
    ]
    yielded: list[str] = []
    async for chunk in run_react_vision_stream(_SkipGraphLLM(), messages, _registry_one(), visual=True):
        yielded.append(getattr(chunk, "content", "") or "")
    joined = "".join(yielded)
    assert "我将显示开户登记相关截图。" in joined
    assert "chart.png](/bisheng/knowledge/images/1/2/chart.png)" in joined


async def test_stream_deltas_are_joined_once(monkeypatch):
    vision = _VisionStream(
        [
            "根据提供的参考资料，开户申请表单的图片是 img#4。",
            "该图片位于开户登记章节中。",
        ]
    )
    _bind_vision(monkeypatch, vision)
    monkeypatch.setattr(
        "bisheng.common.image_view.react_loop.fetch_and_encode",
        AsyncMock(return_value=type("R", (), {"ok": True, "data_uri": _DATA_URI, "reason": None})()),
    )
    yielded: list[str] = []
    async for chunk in run_react_vision_stream(_SkipGraphLLM(), _trend_messages(), _registry_one(), visual=True):
        yielded.append(getattr(chunk, "content", "") or "")
    joined = "".join(yielded)
    assert joined == "根据提供的参考资料，开户申请表单的图片。该图片位于开户登记章节中。"
    assert "img#" not in joined
    assert joined.count("该图片位于开户登记章节中。") == 1


async def test_view_narration_catalog_is_stripped(monkeypatch):
    preamble = (
        "我需要查看您提到的风景图片。根据提供的参考资料，其中包含以下图片标识：\n"
        "- [img#1] → /bisheng/knowledge/images/1/12/image1.png\n"
        "- [img#3] → /bisheng/knowledge/images/1/12/image3.png\n"
        "但当前没有明确说明哪张是风景图；为了准确判断并显示，请允许我先查看这些图片。\n"
    )
    answer = "其中包含一张明确为风景的图片（img#3）：\n![](/bisheng/knowledge/images/1/12/image3.png)\n[img#3]\n其余图片为人物肖像。"
    vision = _VisionStream([preamble + answer])
    _bind_vision(monkeypatch, vision)
    monkeypatch.setattr(
        "bisheng.common.image_view.react_loop.fetch_and_encode",
        AsyncMock(return_value=type("R", (), {"ok": True, "data_uri": _DATA_URI, "reason": None})()),
    )
    yielded: list[str] = []
    async for chunk in run_react_vision_stream(_SkipGraphLLM(), _trend_messages(), _registry_one(), visual=True):
        yielded.append(getattr(chunk, "content", "") or "")
    joined = "".join(yielded)
    assert "请允许我先查看" not in joined
    assert "image1.png" not in joined
    assert "[img#3]" not in joined
    assert "一张明确为风景的图片" in joined
    assert "img#" not in joined
    assert "![](/bisheng/knowledge/images/1/12/image3.png)" in joined
    assert "其余图片" not in joined


async def test_filename_catalog_and_cannot_view_preamble_are_stripped(monkeypatch):
    preamble = (
        "根据您提供的资料，文档中包含以下图片（共5张）：\n"
        "- image1.png [img#1]\n"
        "- image3.png [img#3]\n"
        "但当前没有明确说明哪张是美女的图片。由于我无法查看图片内容，也无法从这些图片中确认。\n"
        "若您能提供描述，或上传后我可调用 view_image 查看。\n"
        "另外，我不会展示任何涉及色情、低俗的内容，需符合公序良俗。\n"
        "如您希望仅查找风景类图片。是否需要我继续帮您做此筛选？ - img#1：一位女性的特写照片。\n"
    )
    answer = "- img#2：一位穿白色连衣裙的年轻女性。\n因此，属于美女的图片是 img#1 和 img#2。\n如需进一步处理（如裁剪、放大），可继续说明。"
    vision = _VisionStream([preamble + answer])
    _bind_vision(monkeypatch, vision)
    monkeypatch.setattr(
        "bisheng.common.image_view.react_loop.fetch_and_encode",
        AsyncMock(return_value=type("R", (), {"ok": True, "data_uri": _DATA_URI, "reason": None})()),
    )
    yielded: list[str] = []
    async for chunk in run_react_vision_stream(_SkipGraphLLM(), _trend_messages(), _registry_one(), visual=True):
        yielded.append(getattr(chunk, "content", "") or "")
    joined = "".join(yielded)
    assert "包含以下图片" not in joined
    assert "image1.png" not in joined
    assert "无法查看图片" not in joined
    assert "view_image" not in joined
    assert "公序良俗" not in joined
    assert "如需进一步处理" not in joined
    assert "一位女性的特写照片" in joined
    assert "一位穿白色连衣裙的年轻女性" not in joined
    assert "属于美女的图片" in joined
    assert "img#" not in joined


def test_answer_hides_image_ids_and_turn_limit():
    text = (
        "根据您提供的图片内容，其中包含以下两张人物图片：\n"
        "• img#1：一位女性（穿着黑色吊带、佩戴珍珠项链与手链），符合“美女”描述。\n"
        "• img#2：一位穿粉色连衣裙的年轻女性，同样符合“美女”描述。\n"
        "而 img#3 是山水风景图，不包含人物；img#4 和 img#5 未在本次调用中加载（因单轮最多仅支持3张图）。\n"
        "因此，文档中明确可见的“美女”图片为：\n"
        "• img#1\n"
        "• img#2\n"
        "如需查看 img#4 或 img#5，请单独请求。"
    )
    cleaned = strip_view_narration(text)
    assert "img#" not in cleaned
    assert "单轮最多" not in cleaned
    assert "请单独请求" not in cleaned
    assert "一位女性（穿着黑色吊带、佩戴珍珠项链与手链）" not in cleaned
    assert "一位穿粉色连衣裙的年轻女性" not in cleaned
    assert "因此，文档中明确可见的“美女”图片为" in cleaned
    assert "山水风景图" in cleaned


def test_strip_hides_filename_labels_and_remaining_dump():
    text = (
        "• image3.png（img#3）：显示的是一个带有印章的纸质文件。\n"
        "• image5.jpeg（''）：一张印有二维码的图片。\n"
        "注：其余图片 (image1、image2、image4) 分别为女性人物照与冰箱外观图，不属证书类。\n"
        "其余图片内容如下："
    )
    cleaned = strip_view_narration(text)
    assert "image1" not in cleaned
    assert "image2" not in cleaned
    assert "image3" not in cleaned
    assert "image4" not in cleaned
    assert "image5" not in cleaned
    assert "img#" not in cleaned
    assert "其余图片内容如下" not in cleaned
    assert "带有印章的纸质文件" not in cleaned
    assert "印有二维码" not in cleaned
    assert "不属证书类" in cleaned


def test_strip_drops_empty_name_comparison():
    text = (
        "结合文档中插入的图片信息：\n"
        "• ''：显示一张带有危险化学品经营许可证字样的文件。\n"
        "• ''：显示一张纸质文件，可能为保修证。\n"
        "其余图片：\n"
        "• 和：均为人物照，不属证书类。\n"
        "因此，证书相关的图片是：\n"
        "![危险化学品经营许可证](http://x/a.png)"
    )
    cleaned = strip_view_narration(text)
    assert "''" not in cleaned
    assert "和：" not in cleaned
    assert "其余图片" not in cleaned
    assert "可能为保修证" not in cleaned
    assert "因此，证书相关的图片是" in cleaned
    assert "![危险化学品经营许可证](http://x/a.png)" in cleaned


def test_strip_ticket_answer_keeps_image_and_drops_catalog():
    text = (
        "是的，文档中包含一张火车票的图片。\n"
        "根据参考资料中的图片信息：\n"
        "• `img#2` 对应的图片为： `![](/bisheng/knowledge/images/1/12/image2.png)`\n"
        "其描述为“火车票”，属于明确的票据类图片。\n"
        "• `img#1`：人物照（含AI变清晰水印）\n"
        "• ''：保修证或类似纸质证书（含印章与文字）\n"
        "• ''：危险化学品经营许可证样式的证书\n"
        "因此，有火车票的图片，即 ''。是的，有火车票的图片。\n"
        "• 车次：Z35Z052135\n"
        "其余图片为：\n"
        "- `img#1`：女性人物照（含AI变清晰水印）\n"
        "因此，只有是火车票。"
    )
    cleaned = strip_view_narration(text)
    assert "人物照" not in cleaned
    assert "保修证" not in cleaned
    assert "危险化学品" not in cleaned
    assert "其余图片" not in cleaned
    assert "''" not in cleaned
    assert "img#" not in cleaned
    assert "![](/bisheng/knowledge/images/1/12/image2.png)" in cleaned
    assert "`![]" not in cleaned
    assert "车次：Z35Z052135" in cleaned
    assert "是的，文档中包含一张火车票的图片。" in cleaned


def test_strip_hides_redacted_id_placeholders():
    text = (
        "根据您提供的图片列表，其中 **** 和 。。。 包含女性人物图像：\n"
        "• ****一位佩戴珍珠项链、穿黑色上衣的女性。\n"
        "其余图片为风景，均不含“美女”。\n"
        "因此，文档中“美女”的图片为：\n"
        "[img#1] 和\n"
        "![](http://x/a.png)"
    )
    cleaned = strip_view_narration(text)
    assert "****" not in cleaned
    assert "。。。" not in cleaned
    assert "img#" not in cleaned
    assert "一位佩戴珍珠项链" in cleaned
    assert "http://x/a.png" in cleaned


def test_dash_ids_and_nonmatch_catalog_are_hidden():
    text = (
        "根据当前查看的图片内容，没有发现车票相关的图片。\n"
        "-均为系统后台管理界面（业务域卡片、分类卡片、首页轮播图等），无车票。\n"
        "综上，当前图片中没有车票的图片。\n"
        "根据提供的图片内容，是人物照片，-6 为系统后台管理界面截图，-11 未在当前问题中被引用。\n"
        "其中，的底部有文字，该图中无明确证书内容。\n"
        "同样为人物照片，也无证书信息。\n"
        "综上，当前所有图片中均未出现证书内容。"
    )
    cleaned = strip_view_narration(text)
    assert "-6" not in cleaned
    assert "-11" not in cleaned
    assert "系统后台" not in cleaned
    assert "无明确" not in cleaned
    assert "没有车票的图片" in cleaned
    assert "均未出现证书内容" in cleaned


def test_ordinal_rebuttal_is_hidden_and_picture_kept():
    text = (
        "第二张图片显示的是一位穿白色连衣裙的女性，不是车票；而第五张图片是一张火车票，符合“车票”的描述。\n"
        "因此，您说的“第二张是车票不是证书”不准确——第二张是人像照；第五张才是车票。\n"
        "证书类图片为第四张，显示的是“危险化学品经营许可证”，属于证书。\n"
        "![](http://x/ticket.png)"
    )
    cleaned = strip_view_narration(text)
    assert "第二张" not in cleaned
    assert "第五张" not in cleaned
    assert "第四张" not in cleaned
    assert "http://x/ticket.png" in cleaned


def test_rejection_catalog_and_citations_do_not_survive():
    cite = "\ue200knowledgesearch_abc:0\ue201knowledgesearch_def:1\ue202"
    text = (
        "根据提供的参考资料，其中包含的图片如下：\n"
        "• 一张松下电冰箱说明书封面（含型号、产品图等），无美女\n"
        "• 一张冰箱内部结构示意图（含搁板、果蔬盒等），无美女\n"
        "• 一张“危险化学品经营许可证”封面，无美女\n"
        "所有图片均未显示女性人物，因此没有美女的图片。\n"
        f"{cite}是的，有美女的图片。\n"
        "![](/bisheng/knowledge/images/1/12/image1.png)"
    )
    cleaned = _strip_picture_citations(strip_view_narration(text), "是否有美女的图片？")
    assert "电冰箱" not in cleaned
    assert "无美女" not in cleaned
    assert "因此没有" not in cleaned
    assert "\ue200" not in cleaned
    assert "是的，有美女的图片。" in cleaned
    assert "![](/bisheng/knowledge/images/1/12/image1.png)" in cleaned
    raw = "• img#1：无美女\n• img#2：无美女\n是的，有美女的图片 img#1。"
    assert cited_ids_on_shown_lines(raw) == ["img#1"]


async def test_wrapper_is_not_runnable():
    from langchain_core.runnables import Runnable

    wrapper = VisionToolBindWrapper(_SkipGraphLLM(), ImageRegistry(), [])
    assert not isinstance(wrapper, Runnable)
