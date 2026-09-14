"""VisionToolBindWrapper in common (F061 T016).

Covers AC: AC-03, AC-04, AC-06, AC-07
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import Runnable

from bisheng.common.image_view import IMAGE_VIEW_PROMPT_RULES, ImageRegistry, annotate
from bisheng.common.image_view.vision_llm import (
    RETRIEVE_BEFORE_VIEW_RULES,
    VisionToolBindWrapper,
    maybe_inject_view_image,
)

_DATA_URI = "data:image/png;base64,aaa"


class _NamedTool:
    def __init__(self, name: str):
        self.name = name


class _RecordingLLM:
    def __init__(self):
        self.bind_calls: list[list[str]] = []
        self.bind_kwargs: list[dict] = []
        self.stream_messages: list[list] = []

    def bind_tools(self, tools, **kwargs):
        self.bind_calls.append([getattr(tool, "name", "") for tool in tools])
        self.bind_kwargs.append(dict(kwargs))
        return _Bound(self)


class _Bound:
    def __init__(self, parent: _RecordingLLM):
        self.parent = parent

    async def ainvoke(self, messages, config=None, **kwargs):
        self.parent.stream_messages.append(list(messages))
        return AIMessage(content="ok")

    def invoke(self, messages, config=None, **kwargs):
        self.parent.stream_messages.append(list(messages))
        return AIMessage(content="ok")


async def test_vision_wrapper_empty_registry_binds_only_base_tools():
    llm = _RecordingLLM()
    registry = ImageRegistry()
    wrapper = VisionToolBindWrapper(llm, registry, [_NamedTool("web_search")])
    assert not isinstance(wrapper, Runnable)
    runnable = wrapper({}, None)
    result = await runnable.ainvoke([HumanMessage(content="hi")])
    assert result.content == "ok"
    assert llm.bind_calls == [["web_search"]]
    joined = "".join(str(m.content) for m in llm.stream_messages[0])
    assert IMAGE_VIEW_PROMPT_RULES not in joined
    assert "view_image" not in joined


async def test_vision_wrapper_nonempty_registry_binds_view_image_and_rules():
    llm = _RecordingLLM()
    registry = ImageRegistry()
    annotate("![chart](/bisheng/knowledge/images/1/2/c.png)", registry)
    wrapper = VisionToolBindWrapper(llm, registry, [_NamedTool("web_search")])
    runnable = wrapper({}, None)
    await runnable.ainvoke([SystemMessage(content="base"), HumanMessage(content="trend")])
    assert llm.bind_calls == [["web_search", "view_image"]]
    joined = "".join(str(m.content) for m in llm.stream_messages[0])
    assert IMAGE_VIEW_PROMPT_RULES in joined


async def test_vision_wrapper_pop_viewed_appends_human_image_blocks():
    llm = _RecordingLLM()
    registry = ImageRegistry()
    annotate("![chart](/bisheng/knowledge/images/1/2/c.png)", registry)
    registry.record_viewed("img#1", _DATA_URI)
    wrapper = VisionToolBindWrapper(llm, registry, [_NamedTool("web_search")])
    runnable = wrapper({}, None)
    await runnable.ainvoke([HumanMessage(content="hi")])
    messages = llm.stream_messages[0]
    assert not any(isinstance(m, ToolMessage) and isinstance(m.content, list) for m in messages)
    humans = [m for m in messages if isinstance(m, HumanMessage) and isinstance(m.content, list)]
    assert humans
    blocks = [block for block in humans[-1].content if isinstance(block, dict) and block.get("type") == "image_url"]
    assert blocks
    assert blocks[0]["image_url"]["url"] == _DATA_URI
    assert registry.pop_viewed() == []


async def test_vision_wrapper_pixel_question_forces_retrieve_before_view_image():
    llm = _RecordingLLM()
    registry = ImageRegistry()
    wrapper = VisionToolBindWrapper(
        llm,
        registry,
        [_NamedTool("bisheng_code_interpreter"), _NamedTool("search_knowledge_bases")],
        retrieve_tool_name="search_knowledge_bases",
    )
    question = HumanMessage(content="开户登记界面说明相关的图片")
    runnable = wrapper({"messages": [question]}, None)
    result = await runnable.ainvoke([question])
    assert llm.bind_calls == [["bisheng_code_interpreter", "search_knowledge_bases"]]
    assert llm.bind_kwargs[0]["tool_choice"]["function"]["name"] == "search_knowledge_bases"
    assert result.tool_calls[0]["name"] == "search_knowledge_bases"
    assert result.tool_calls[0]["args"]["query"] == "开户登记界面说明相关的图片"
    joined = "".join(str(m.content) for m in llm.stream_messages[0])
    assert RETRIEVE_BEFORE_VIEW_RULES in joined
    assert IMAGE_VIEW_PROMPT_RULES not in joined


async def test_vision_wrapper_does_not_reforce_retrieve_after_search():
    llm = _RecordingLLM()
    registry = ImageRegistry()
    wrapper = VisionToolBindWrapper(
        llm,
        registry,
        [_NamedTool("search_knowledge_bases")],
        retrieve_tool_name="search_knowledge_bases",
    )
    messages = [
        HumanMessage(content="开户登记界面说明相关的图片"),
        ToolMessage(content="[]", tool_call_id="s1", name="search_knowledge_bases"),
    ]
    runnable = wrapper({"messages": messages}, None)
    result = await runnable.ainvoke(messages)
    assert "tool_choice" not in llm.bind_kwargs[0]
    assert result.content == "ok"
    assert not result.tool_calls


async def test_vision_wrapper_nonempty_registry_still_prefers_view_image():
    llm = _RecordingLLM()
    registry = ImageRegistry()
    annotate("![chart](/bisheng/knowledge/images/1/2/c.png)", registry)
    wrapper = VisionToolBindWrapper(
        llm,
        registry,
        [_NamedTool("search_knowledge_bases")],
        retrieve_tool_name="search_knowledge_bases",
    )
    question = HumanMessage(content="开户登记界面说明相关的图片")
    runnable = wrapper({"messages": [question]}, None)
    await runnable.ainvoke([question])
    assert llm.bind_calls == [["search_knowledge_bases", "view_image"]]
    assert llm.bind_kwargs[0]["tool_choice"]["function"]["name"] == "view_image"


async def test_vision_wrapper_relocates_tool_images_to_human():
    llm = _RecordingLLM()
    registry = ImageRegistry()
    wrapper = VisionToolBindWrapper(llm, registry, [_NamedTool("web_search")])
    runnable = wrapper({}, None)
    await runnable.ainvoke(
        [
            HumanMessage(content="q"),
            ToolMessage(
                content=[{"type": "image_url", "image_url": {"url": _DATA_URI}}],
                tool_call_id="c1",
            ),
        ]
    )
    messages = llm.stream_messages[0]
    assert not any(isinstance(m, ToolMessage) and isinstance(m.content, list) for m in messages)
    humans = [m for m in messages if isinstance(m, HumanMessage) and isinstance(m.content, list)]
    assert humans
    assert any(isinstance(block, dict) and block.get("type") == "image_url" for block in humans[-1].content)


async def test_failed_view_image_still_injects_suggested_ids():
    registry = ImageRegistry()
    annotate(
        "1.1.2.开户登记\n![register](/bisheng/knowledge/images/1/6/image_6_14.jpeg)",
        registry,
    )
    messages = [
        HumanMessage(content="把开户登记界面说明相关的图片显示出来"),
        ToolMessage(
            content="1.1.2.开户登记\n![register](/bisheng/knowledge/images/1/6/image_6_14.jpeg)⟦img#1⟧",
            tool_call_id="s1",
            name="search_knowledge_bases",
        ),
        ToolMessage(content="Image img#19 is not available (too_small).", tool_call_id="v0", name="view_image"),
    ]
    ai = AIMessage(content="let me try more images")
    out = maybe_inject_view_image(ai, messages, registry)
    assert out.tool_calls
    assert out.tool_calls[0]["name"] == "view_image"
    assert "img#1" in out.tool_calls[0]["args"]["image_ids"]


async def test_inject_skips_retry_when_suggested_ids_already_failed():
    registry = ImageRegistry()
    annotate(
        "1.1.2.开户登记\n![register](/bisheng/knowledge/images/1/6/image_6_14.jpeg)",
        registry,
    )
    messages = [
        HumanMessage(content="把开户登记界面说明相关的图片显示出来"),
        ToolMessage(
            content="1.1.2.开户登记\n![register](/bisheng/knowledge/images/1/6/image_6_14.jpeg)⟦img#1⟧",
            tool_call_id="s1",
            name="search_knowledge_bases",
        ),
        ToolMessage(
            content="Image img#1 is not available (too_small).",
            tool_call_id="v0",
            name="view_image",
        ),
    ]
    ai = AIMessage(
        content="",
        tool_calls=[{"name": "view_image", "args": {"image_ids": ["img#1"]}, "id": "c1", "type": "tool_call"}],
    )
    out = maybe_inject_view_image(ai, messages, registry)
    assert not out.tool_calls


async def test_vision_wrapper_stops_forcing_view_image_when_candidates_exhausted():
    llm = _RecordingLLM()
    registry = ImageRegistry()
    annotate(
        "1.1.2.开户登记\n![register](/bisheng/knowledge/images/1/6/image_6_14.jpeg)",
        registry,
    )
    wrapper = VisionToolBindWrapper(llm, registry, [_NamedTool("search_knowledge_bases")])
    messages = [
        HumanMessage(content="把开户登记界面说明相关的图片显示出来"),
        ToolMessage(
            content="1.1.2.开户登记\n![register](/bisheng/knowledge/images/1/6/image_6_14.jpeg)⟦img#1⟧",
            tool_call_id="s1",
            name="search_knowledge_bases",
        ),
        ToolMessage(
            content="Image img#1 is not available (too_small).",
            tool_call_id="v0",
            name="view_image",
        ),
    ]
    runnable = wrapper({"messages": messages}, None)
    result = await runnable.ainvoke(messages)
    assert "tool_choice" not in llm.bind_kwargs[0]
    assert result.content == "ok"
    assert not result.tool_calls
