"""Unit tests for the Linsight binary-content guards.

Covers both layers: the ``read_file`` tool guard (which must catch BOTH the
multimodal-block branch and the silent mojibake branch) and the model-request
backstop (which must make a ``video`` block survivable — it raises inside
langchain-core, not as an HTTP error).

``asyncio_mode = auto`` — async tests need no decorator.
"""

from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openai.chat_models.base import _convert_message_to_dict

from bisheng.linsight.domain.services.binary_content_guard import (
    BinaryReadGuardMiddleware,
    ModelContentGuardMiddleware,
    _looks_like_mojibake,
)


@dataclass
class FakeToolCallRequest:
    tool_call: dict
    tool: Any = None
    state: Any = None
    runtime: Any = None


@dataclass
class FakeModelRequest:
    messages: list = field(default_factory=list)

    def override(self, **kwargs):
        return FakeModelRequest(**{"messages": self.messages, **kwargs})


def read_call(file_path="/uploads/report.pdf"):
    return FakeToolCallRequest(tool_call={"name": "read_file", "args": {"file_path": file_path}, "id": "c1"})


def handler_returning(message):
    async def handler(_request):
        return message

    return handler


def file_block_message(mime="application/pdf", block_type="file"):
    return ToolMessage(
        content_blocks=[{"type": block_type, "base64": "JVBERi0xLjQ=", "mime_type": mime}],
        name="read_file",
        tool_call_id="c1",
        additional_kwargs={"read_file_media_type": mime},
    )


# --------------------------------------------------------------------------
# Layer 1 — read_file tool guard
# --------------------------------------------------------------------------


async def test_file_block_replaced_with_hint():
    mw = BinaryReadGuardMiddleware(has_code_interpreter=True)
    result = await mw.awrap_tool_call(read_call(), handler_returning(file_block_message()))

    assert isinstance(result.content, str)
    assert "/uploads/report.pdf" in result.content
    assert "/uploads/report.md" in result.content  # points at the text view
    assert "bisheng_code_interpreter" in result.content
    # the multimodal marker must not survive
    assert result.additional_kwargs == {}


async def test_audio_and_video_blocks_also_replaced():
    mw = BinaryReadGuardMiddleware(has_code_interpreter=True)
    for block_type, mime in (("audio", "audio/mpeg"), ("video", "video/mp4")):
        msg = file_block_message(mime=mime, block_type=block_type)
        result = await mw.awrap_tool_call(read_call("/uploads/clip.mp4"), handler_returning(msg))
        assert isinstance(result.content, str)
        assert "bisheng_code_interpreter" in result.content


async def test_mojibake_text_replaced():
    """The silent branch: .docx/.xlsx are NOT in deepagents' extension map, so
    they arrive as `decode(errors="replace")` soup with no error at all."""
    mw = BinaryReadGuardMiddleware(has_code_interpreter=True)
    soup = "PK\x03\x04" + "�" * 200
    msg = ToolMessage(content=soup, name="read_file", tool_call_id="c1")
    result = await mw.awrap_tool_call(read_call("/uploads/data.xlsx"), handler_returning(msg))

    assert "/uploads/data.xlsx" in result.content
    assert "�" not in result.content


async def test_plain_text_passes_through():
    mw = BinaryReadGuardMiddleware(has_code_interpreter=True)
    msg = ToolMessage(content="     1\t# Title\n     2\tbody", name="read_file", tool_call_id="c1")
    result = await mw.awrap_tool_call(read_call("/uploads/report.md"), handler_returning(msg))
    assert result.content == "     1\t# Title\n     2\tbody"


async def test_other_tools_untouched():
    mw = BinaryReadGuardMiddleware(has_code_interpreter=True)
    req = FakeToolCallRequest(tool_call={"name": "write_file", "args": {}, "id": "c2"})
    msg = file_block_message()
    result = await mw.awrap_tool_call(req, handler_returning(msg))
    assert result is msg


def test_mojibake_detector_tolerates_real_text():
    # A stray replacement char in a normal document must not trip the detector.
    assert not _looks_like_mojibake("正常的中文报告内容，只有一个坏字符 � 而已，其余都是可读文本。" * 3)
    assert not _looks_like_mojibake("short")
    assert _looks_like_mojibake("a" * 40 + "\x00")


# --------------------------------------------------------------------------
# Layer 2 — model-request backstop
# --------------------------------------------------------------------------


async def test_blocked_blocks_stripped_before_model_call():
    mw = ModelContentGuardMiddleware()
    request = FakeModelRequest(
        messages=[
            HumanMessage(content="分析这个文件"),
            ToolMessage(
                content=[{"type": "file", "file": {"file_data": "data:application/pdf;base64,AA"}}],
                name="read_file",
                tool_call_id="c1",
            ),
        ]
    )
    seen = {}

    async def handler(req):
        seen["messages"] = req.messages
        return AIMessage(content="ok")

    await mw.awrap_model_call(request, handler)

    tool_msg = seen["messages"][1]
    assert all(b["type"] == "text" for b in tool_msg.content)
    # original request object untouched
    assert request.messages[1].content[0]["type"] == "file"


async def test_video_block_becomes_serializable():
    """Regression: langchain-core raises ValueError on a `video` block, so it
    never reaches the HTTP layer where the error classifier could bucket it."""
    mw = ModelContentGuardMiddleware()
    raw = ToolMessage(
        content_blocks=[{"type": "video", "base64": "AAAA", "mime_type": "video/mp4"}],
        name="read_file",
        tool_call_id="c1",
    )

    try:
        _convert_message_to_dict(raw)
        raise AssertionError("expected langchain-core to reject a raw video block")
    except ValueError as exc:
        assert "video" in str(exc)

    seen = {}

    async def handler(req):
        seen["messages"] = req.messages
        return AIMessage(content="ok")

    await mw.awrap_model_call(FakeModelRequest(messages=[raw]), handler)

    # after the guard the very same message serializes cleanly
    payload = _convert_message_to_dict(seen["messages"][0])
    assert payload["role"] == "tool"
    assert all(b["type"] == "text" for b in payload["content"])


async def test_image_blocks_preserved():
    mw = ModelContentGuardMiddleware()
    image_block = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}}
    request = FakeModelRequest(messages=[HumanMessage(content=[image_block])])
    seen = {}

    async def handler(req):
        seen["messages"] = req.messages
        return AIMessage(content="ok")

    await mw.awrap_model_call(request, handler)
    assert seen["messages"][0].content == [image_block]


async def test_message_never_left_empty():
    mw = ModelContentGuardMiddleware()
    request = FakeModelRequest(
        messages=[ToolMessage(content=[{"type": "audio", "base64": "AA"}], name="read_file", tool_call_id="c1")]
    )
    seen = {}

    async def handler(req):
        seen["messages"] = req.messages
        return AIMessage(content="ok")

    await mw.awrap_model_call(request, handler)
    assert len(seen["messages"][0].content) == 1
    assert seen["messages"][0].content[0]["type"] == "text"


async def test_hint_omits_unbound_code_interpreter():
    """prompt ⟺ tool lockstep: never point at a tool this run does not have."""
    mw = BinaryReadGuardMiddleware(has_code_interpreter=False)
    result = await mw.awrap_tool_call(read_call(), handler_returning(file_block_message()))

    assert "bisheng_code_interpreter" not in result.content
    assert "/uploads/report.md" in result.content  # the route that still works
    assert "没有可用的代码执行工具" in result.content
