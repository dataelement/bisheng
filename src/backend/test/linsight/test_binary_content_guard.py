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
    mw = ModelContentGuardMiddleware(supports_vision=True)
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


# --------------------------------------------------------------------------
# Backend-refusal upgrade + image payload validation (P0/P1 follow-up)
# --------------------------------------------------------------------------


async def test_backend_binary_error_upgraded_to_routed_hint():
    """The backend refuses binary reads itself now, but it cannot know whether the
    code interpreter is bound this run — the guard is the layer that does."""
    from bisheng.linsight.domain.services.workspace_backend import BINARY_READ_ERROR_PREFIX

    refusal = ToolMessage(
        content=f"Error: {BINARY_READ_ERROR_PREFIX} 'uploads/data.xlsx' is a binary file and cannot be read as text.",
        name="read_file",
        tool_call_id="c1",
        status="error",
    )
    mw = BinaryReadGuardMiddleware(has_code_interpreter=True)
    result = await mw.awrap_tool_call(read_call("/uploads/data.xlsx"), handler_returning(refusal))

    assert "bisheng_code_interpreter" in result.content
    assert "pandas" in result.content


async def test_backend_binary_error_without_code_interpreter():
    from bisheng.linsight.domain.services.workspace_backend import BINARY_READ_ERROR_PREFIX

    refusal = ToolMessage(
        content=f"Error: {BINARY_READ_ERROR_PREFIX} 'uploads/data.xlsx' is binary.",
        name="read_file",
        tool_call_id="c1",
        status="error",
    )
    mw = BinaryReadGuardMiddleware(has_code_interpreter=False)
    result = await mw.awrap_tool_call(read_call("/uploads/data.xlsx"), handler_returning(refusal))

    assert "bisheng_code_interpreter" not in result.content
    assert "没有可用的代码执行工具" in result.content


async def test_ordinary_tool_error_passes_through():
    """Only OUR binary marker is upgraded; a plain not-found must stay verbatim."""
    msg = ToolMessage(content="Error: File '/output/nope.md' not found", name="read_file", tool_call_id="c1")
    mw = BinaryReadGuardMiddleware(has_code_interpreter=True, supports_vision=True)
    result = await mw.awrap_tool_call(read_call("/output/nope.md"), handler_returning(msg))

    assert result.content == "Error: File '/output/nope.md' not found"


async def test_valid_image_block_survives_read_guard():
    """Post-P0 the backend emits REAL base64 for images; that must reach the model
    (it is the one multimodal shape endpoints accept)."""
    import base64

    payload = base64.standard_b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32).decode("ascii")
    msg = ToolMessage(
        content_blocks=[{"type": "image", "base64": payload, "mime_type": "image/png"}],
        name="read_file",
        tool_call_id="c1",
    )
    mw = BinaryReadGuardMiddleware(has_code_interpreter=True, supports_vision=True)
    result = await mw.awrap_tool_call(read_call("/output/chart.png"), handler_returning(msg))

    assert isinstance(result.content, list)
    assert result.content[0]["type"] == "image"


async def test_corrupt_image_block_replaced_by_read_guard():
    """A mojibake payload dressed as an image would 400 the request or feed the
    model noise — worse than dropping it."""
    msg = ToolMessage(
        content_blocks=[{"type": "image", "base64": "���PNG�", "mime_type": "image/png"}],
        name="read_file",
        tool_call_id="c1",
    )
    mw = BinaryReadGuardMiddleware(has_code_interpreter=True)
    result = await mw.awrap_tool_call(read_call("/output/chart.png"), handler_returning(msg))

    assert isinstance(result.content, str)
    assert "/output/chart.png" in result.content


async def test_corrupt_image_stripped_before_model_call():
    mw = ModelContentGuardMiddleware(has_code_interpreter=False, supports_vision=True)
    request = FakeModelRequest(
        messages=[HumanMessage(content=[{"type": "image", "base64": "���", "mime_type": "image/png"}])]
    )
    seen = {}

    async def handler(req):
        seen["messages"] = req.messages
        return AIMessage(content="ok")

    await mw.awrap_model_call(request, handler)

    block = seen["messages"][0].content[0]
    assert block["type"] == "text"
    assert "base64" in block["text"]
    # prompt ⟺ tool lockstep applies to this replacement text too
    assert "bisheng_code_interpreter" not in block["text"]


async def test_http_image_url_is_not_flagged():
    """No inline payload to validate — a plain URL must pass untouched."""
    mw = ModelContentGuardMiddleware(supports_vision=True)
    block = {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}}
    request = FakeModelRequest(messages=[HumanMessage(content=[block])])
    seen = {}

    async def handler(req):
        seen["messages"] = req.messages
        return AIMessage(content="ok")

    await mw.awrap_model_call(request, handler)
    assert seen["messages"][0].content == [block]


# --------------------------------------------------------------------------
# Layer 2 — tool-message images are relocated into a user turn
# --------------------------------------------------------------------------


def image_tool_message(path="/scratch/S1_p5.png", tool_call_id="c1", payload="aGk="):
    """The exact shape deepagents' `read_file` returns for an image
    (`deepagents/middleware/filesystem.py`): a multimodal block in the TOOL role."""
    return ToolMessage(
        content_blocks=[{"type": "image", "base64": payload, "mime_type": "image/png"}],
        name="read_file",
        tool_call_id=tool_call_id,
        additional_kwargs={"read_file_path": path, "read_file_media_type": "image/png"},
    )


def ai_tool_call(*ids):
    return AIMessage(
        content="",
        tool_calls=[{"name": "read_file", "args": {"file_path": f"/scratch/{i}.png"}, "id": i} for i in ids],
    )


async def collect(mw, messages):
    request = FakeModelRequest(messages=messages)
    seen = {}

    async def handler(req):
        seen["messages"] = req.messages
        return AIMessage(content="ok")

    await mw.awrap_model_call(request, handler)
    return request, seen["messages"]


async def test_tool_image_relocated_into_a_user_turn():
    """Regression: Kimi K3 answers `image_url parts are supported only in user
    messages` with a 400 that fails the whole session. Every mainstream endpoint
    accepts an image in the user role, so the block is MOVED rather than dropped
    (dropping it would regress the scanned-page workflow this feature exists for)."""
    mw = ModelContentGuardMiddleware(supports_vision=True)
    request, out = await collect(mw, [ai_tool_call("c1"), image_tool_message()])

    assert len(out) == 3

    tool_payload = _convert_message_to_dict(out[1])
    assert tool_payload["role"] == "tool"
    # the tool result survives as non-empty text, and names the file it read
    assert all(b["type"] == "text" for b in tool_payload["content"])
    assert "/scratch/S1_p5.png" in tool_payload["content"][0]["text"]

    carrier = _convert_message_to_dict(out[2])
    assert carrier["role"] == "user"
    assert [b["type"] for b in carrier["content"]] == ["text", "text", "image_url"]
    assert carrier["content"][2]["image_url"]["url"] == "data:image/png;base64,aGk="

    # request-only: the state/checkpoint copy keeps the original shape, so this is
    # reversible and a rollback cannot leave a rewritten history behind.
    assert request.messages[1].content[0]["type"] == "image"


async def test_carrier_goes_after_the_whole_tool_batch():
    """Ordering rule: every tool message answering one `tool_calls` batch must be
    contiguous and precede any other role. Inserting the carrier directly after the
    image-bearing tool message would split the batch — trading a 400 for a 400."""
    mw = ModelContentGuardMiddleware(supports_vision=True)
    _, out = await collect(
        mw,
        [
            ai_tool_call("c1", "c2"),
            image_tool_message(tool_call_id="c1"),
            ToolMessage(content="plain text result", name="read_file", tool_call_id="c2"),
            AIMessage(content="done"),
        ],
    )

    assert [_convert_message_to_dict(m)["role"] for m in out] == ["assistant", "tool", "tool", "user", "assistant"]


async def test_each_tool_batch_gets_its_own_carrier():
    mw = ModelContentGuardMiddleware(supports_vision=True)
    _, out = await collect(
        mw,
        [
            ai_tool_call("c1"),
            image_tool_message(tool_call_id="c1"),
            ai_tool_call("c2"),
            image_tool_message(path="/scratch/b.png", tool_call_id="c2"),
        ],
    )

    assert [_convert_message_to_dict(m)["role"] for m in out] == [
        "assistant",
        "tool",
        "user",
        "assistant",
        "tool",
        "user",
    ]


async def test_multiple_relocated_images_keep_order():
    mw = ModelContentGuardMiddleware(supports_vision=True)
    _, out = await collect(
        mw,
        [
            ai_tool_call("c1", "c2"),
            image_tool_message(path="/scratch/a.png", tool_call_id="c1", payload="YQ=="),
            image_tool_message(path="/scratch/b.png", tool_call_id="c2", payload="Yg=="),
        ],
    )

    carrier = out[3]
    labels = [b["text"] for b in carrier.content if b["type"] == "text"]
    assert "/scratch/a.png" in labels[1]
    assert "/scratch/b.png" in labels[2]
    assert [b["base64"] for b in carrier.content if b["type"] == "image"] == ["YQ==", "Yg=="]


async def test_openai_native_image_url_in_a_tool_message_is_relocated():
    """The other shape an image arrives in — same role problem, same fix."""
    mw = ModelContentGuardMiddleware(supports_vision=True)
    block = {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGk="}}
    _, out = await collect(
        mw,
        [ai_tool_call("c1"), ToolMessage(content=[block], name="read_file", tool_call_id="c1")],
    )

    assert _convert_message_to_dict(out[1])["role"] == "tool"
    assert all(b["type"] == "text" for b in out[1].content)
    assert out[2].content[-1] == block


async def test_user_images_are_not_relocated():
    """Only the tool role is the problem — a human attachment is already legal and
    must not gain a spurious carrier turn."""
    mw = ModelContentGuardMiddleware(supports_vision=True)
    block = {"type": "image", "base64": "aGk=", "mime_type": "image/png"}
    _, out = await collect(mw, [HumanMessage(content=[block])])

    assert len(out) == 1
    assert out[0].content == [block]


async def test_corrupt_tool_image_is_stripped_not_relocated():
    """A payload that is not real base64 stays useless in any role: moving it would
    only relocate the 400. It keeps the strip path, and adds no carrier turn."""
    mw = ModelContentGuardMiddleware(has_code_interpreter=False, supports_vision=True)
    _, out = await collect(
        mw,
        [
            ai_tool_call("c1"),
            ToolMessage(
                content=[{"type": "image", "base64": "���", "mime_type": "image/png"}],
                name="read_file",
                tool_call_id="c1",
            ),
        ],
    )

    assert len(out) == 2
    assert out[1].content[0]["type"] == "text"
    assert "base64" in out[1].content[0]["text"]


# --------------------------------------------------------------------------
# The `visual` gate — a model with no declared vision capability gets no image
# --------------------------------------------------------------------------


async def test_image_read_refused_when_the_model_has_no_vision():
    """`WSModel.visual` off means the endpoint would reject the image (or the model
    would see nothing). Refuse at the TOOL layer, where the hint can name why."""
    mw = BinaryReadGuardMiddleware(has_code_interpreter=True, supports_vision=False)
    msg = image_tool_message(path="/scratch/page5.png")
    result = await mw.awrap_tool_call(read_call("/scratch/page5.png"), handler_returning(msg))

    assert isinstance(result.content, str)
    assert "/scratch/page5.png" in result.content
    assert "视觉" in result.content  # names the checkbox the admin has to tick
    assert "bisheng_code_interpreter" in result.content  # the route that still works
    assert result.additional_kwargs == {}


async def test_no_vision_hint_forbids_guessing():
    """Honesty over a plausible answer: a model told nothing will describe the page
    anyway. The hint must demand it says the check did not happen."""
    mw = BinaryReadGuardMiddleware(has_code_interpreter=True, supports_vision=False)
    result = await mw.awrap_tool_call(read_call("/scratch/p.png"), handler_returning(image_tool_message()))

    assert "不要凭猜测描述图片内容" in result.content
    assert "never guess" in result.content


async def test_no_vision_hint_omits_unbound_code_interpreter():
    """prompt ⟺ tool lockstep, same rule as the binary hint."""
    mw = BinaryReadGuardMiddleware(has_code_interpreter=False, supports_vision=False)
    result = await mw.awrap_tool_call(read_call("/scratch/p.png"), handler_returning(image_tool_message()))

    assert "bisheng_code_interpreter" not in result.content


async def test_no_vision_model_call_strips_images_in_any_role():
    """Backstop for images the tool guard never saw — the real case is a replayed
    checkpoint from a turn that ran on a vision model before the admin switched it."""
    mw = ModelContentGuardMiddleware(supports_vision=False)
    block = {"type": "image", "base64": "aGk=", "mime_type": "image/png"}
    _, out = await collect(mw, [HumanMessage(content=[block]), ai_tool_call("c1"), image_tool_message()])

    assert len(out) == 3  # no carrier turn was added
    assert out[0].content[0]["type"] == "text"
    assert out[2].content[0]["type"] == "text"
    assert all("image_url" not in str(_convert_message_to_dict(m)) for m in out)


def test_guards_fail_closed_on_vision():
    """Both guards default to no-vision: a call site that forgets the flag must lose
    image reads, never leak a payload the endpoint would reject."""
    assert BinaryReadGuardMiddleware()._supports_vision is False
    assert ModelContentGuardMiddleware()._supports_vision is False


def test_build_binary_guards_pairs_both_layers():
    """A new subagent must get both guards by construction — its subgraph is never
    wrapped by the parent's middleware."""
    from bisheng.linsight.domain.services.binary_content_guard import build_binary_guards

    guards = build_binary_guards(has_code_interpreter=True, supports_vision=True)
    assert [type(g).__name__ for g in guards] == ["BinaryReadGuardMiddleware", "ModelContentGuardMiddleware"]
    assert all(g._has_code_interpreter for g in guards)
    assert all(g._supports_vision for g in guards)
