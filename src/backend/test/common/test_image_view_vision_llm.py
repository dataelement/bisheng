"""VisionToolBindWrapper in common (F061 T016).

Covers AC: AC-03, AC-04, AC-06, AC-07
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import Runnable

from bisheng.common.image_view import IMAGE_VIEW_PROMPT_RULES, ImageRegistry, annotate
from bisheng.common.image_view.vision_llm import VisionToolBindWrapper

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
