"""Binary-content guards for Linsight task mode.

Two independent ``AgentMiddleware`` layers that keep raw binary bytes out of the
model conversation. Both exist because the workspace legitimately holds ORIGINAL
uploads (xlsx / docx / pdf …) alongside their parsed ``.md`` views — the originals
are there for ``bisheng_code_interpreter`` (pandas / python-docx / fitz), never
for the model to read directly.

**Layer 1 — ``BinaryReadGuardMiddleware`` (tool layer, the useful one).**
``read_file`` is a deepagents kernel tool we do not own. It routes on the file
EXTENSION (``deepagents.backends.utils._EXTENSION_TO_FILE_TYPE``), so:

- ``.pdf`` / ``.ppt`` / ``.pptx``  -> a ``file`` content block  -> providers that
  only accept ``text`` / ``image_url`` reject the whole request with HTTP 400;
- ``.mp3`` / ``.wav`` / …         -> an ``audio`` block          -> same 400;
- ``.mp4`` / ``.mov`` / …         -> a ``video`` block           -> langchain-core
  raises ``ValueError: Block of type video is not supported`` at serialization
  time, i.e. a client-side crash rather than an HTTP error;
- **everything else** (``.docx``, ``.xlsx``, ``.zip`` …) is treated as TEXT, and
  ``WorkspaceBackend.aread`` hands it over as ``decode("utf-8", errors="replace")``
  mojibake — no error at all, just U+FFFD soup silently fed to the model. That
  silent branch is the nastiest of the four.

So this guard deliberately does NOT key off the extension: it inspects what the
tool actually returned and replaces any non-text payload with an actionable text
hint pointing at the ``.md`` view and the code interpreter.

**Layer 2 — ``ModelContentGuardMiddleware`` (model-request layer, the backstop).**
Strips ``file`` / ``audio`` / ``video`` blocks from the outgoing message list
whatever their origin (checkpoint replay, a future tool, a human attachment).
``video`` in particular MUST die here: it raises inside langchain-core before any
HTTP call, so ``llm_error_classifier`` never sees a status code to bucket.

``image`` blocks are left alone on purpose — they are the one multimodal shape
mainstream providers do accept, and dropping them would break vision models.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command
from loguru import logger

READ_FILE_TOOL = "read_file"
# Bound only when the user selected it, so every prompt/hint that names it must be
# gated on its presence in the run's tool list. Lives here because the guard's hint
# text and the factory's wiring are its two consumers.
CODE_INTERPRETER_TOOL = "bisheng_code_interpreter"

# Content-block types that no mainstream OpenAI-compatible endpoint accepts from
# us. `image` is intentionally absent (see module docstring).
_BLOCKED_BLOCK_TYPES = frozenset({"file", "audio", "video", "input_audio"})

# A `decode("utf-8", errors="replace")` of binary bytes is dominated by U+FFFD.
# Real text files carry a few at most (a stray mis-encoded byte), so a small
# ratio separates the two cleanly. NUL bytes never appear in legitimate text.
_REPLACEMENT_CHAR = "�"
_MOJIBAKE_RATIO = 0.05
_MOJIBAKE_MIN_CHARS = 32


def _binary_read_hint(file_path: str, has_code_interpreter: bool) -> str:
    """Actionable replacement for a binary ``read_file`` result.

    Tells the model three things: this file is not readable as text, where its
    text view lives, and which tool actually can open it. Bilingual because task
    language varies and this text lands directly in the model's context.

    ``has_code_interpreter`` gates the "open it with Python" route — pointing at
    a tool that is not bound this run just trades one dead end for another.
    """
    stem = file_path.rsplit(".", 1)[0] if "." in file_path else file_path
    if has_code_interpreter:
        route_zh = (
            "- 若需要精确数据（表格数值、单元格、样式、页面坐标）：用 bisheng_code_interpreter "
            "写 Python 读原件 —— Excel 用 pandas/openpyxl，Word 用 python-docx，PDF 用 fitz(PyMuPDF)。\n"
        )
        route_en = (
            f"Read `{stem}.md` for its parsed text view, or open the original with "
            f"bisheng_code_interpreter (pandas/openpyxl, python-docx, fitz)."
        )
    else:
        route_zh = "- 本次没有可用的代码执行工具，无法读取原件：请基于文本视图作答，并在结论中说明受限之处。\n"
        route_en = f"Read `{stem}.md` for its parsed text view; no code execution tool is available this run."
    return (
        f"[System] `{file_path}` 是原始二进制文件，不能用 read_file 直接阅读。\n"
        f"- 若需要阅读内容：改读同名的文本视图 `{stem}.md`（解析成功时会与原件同目录并存）。\n"
        f"{route_zh}"
        f"- 不要再对该路径重复调用 read_file，结果不会变。\n"
        f"[System] `{file_path}` is a raw binary file and cannot be read as text. "
        f"{route_en} Do not call read_file on this path again."
    )


def _looks_like_mojibake(text: str) -> bool:
    """True when ``text`` is binary bytes that got lossily decoded as UTF-8."""
    if not text or len(text) < _MOJIBAKE_MIN_CHARS:
        return False
    if "\x00" in text:
        return True
    return (text.count(_REPLACEMENT_CHAR) / len(text)) > _MOJIBAKE_RATIO


def _non_text_block_types(content: Any) -> set[str]:
    """Block types in ``content`` that are neither text nor image."""
    if not isinstance(content, list):
        return set()
    found = set()
    for block in content:
        if isinstance(block, dict):
            block_type = block.get("type")
            if block_type and block_type not in ("text", "image", "image_url"):
                found.add(block_type)
    return found


class BinaryReadGuardMiddleware(AgentMiddleware):
    """Replace binary ``read_file`` payloads with an actionable text hint.

    Args:
        has_code_interpreter: whether the sandboxed code interpreter is bound for
            this run. Keeps the hint's suggested route in lockstep with the tools
            actually available (same contract as the uploaded-files pointer block).
    """

    def __init__(self, has_code_interpreter: bool = False) -> None:
        super().__init__()
        self._has_code_interpreter = has_code_interpreter

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        result = await handler(request)
        if request.tool_call.get("name") != READ_FILE_TOOL or not isinstance(result, ToolMessage):
            return result

        file_path = str(request.tool_call.get("args", {}).get("file_path") or "")
        content = result.content

        blocked = _non_text_block_types(content)
        if blocked:
            logger.info("[linsight-binary-guard] read_file returned {} block(s) for {}", sorted(blocked), file_path)
            return _replace_tool_content(result, _binary_read_hint(file_path, self._has_code_interpreter))

        if isinstance(content, str) and _looks_like_mojibake(content):
            logger.info("[linsight-binary-guard] read_file returned mojibake for {}", file_path)
            return _replace_tool_content(result, _binary_read_hint(file_path, self._has_code_interpreter))

        return result


def _replace_tool_content(message: ToolMessage, text: str) -> ToolMessage:
    """Rebuild ``message`` with plain-text content, dropping multimodal kwargs.

    ``additional_kwargs`` carries deepagents' ``read_file_media_type`` marker on
    the multimodal path; it is meaningless once the payload is text, so it goes.
    """
    return message.model_copy(update={"content": text, "additional_kwargs": {}})


class ModelContentGuardMiddleware(AgentMiddleware):
    """Strip provider-hostile content blocks from every outgoing model request."""

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        sanitized, stripped = _sanitize_messages(request.messages)
        if stripped:
            logger.warning("[linsight-content-guard] stripped {} block(s) before model call", sorted(stripped))
            request = request.override(messages=sanitized)
        return await handler(request)


def _sanitize_messages(messages: list) -> tuple[list, set[str]]:
    """Return ``(messages, stripped_types)`` with blocked blocks turned into text."""
    stripped: set[str] = set()
    out = []
    for message in messages:
        content = getattr(message, "content", None)
        if not isinstance(content, list):
            out.append(message)
            continue

        new_content = []
        changed = False
        for block in content:
            if isinstance(block, dict) and block.get("type") in _BLOCKED_BLOCK_TYPES:
                stripped.add(block["type"])
                changed = True
                new_content.append(
                    {
                        "type": "text",
                        "text": f"[System] A `{block['type']}` attachment was removed here: this model "
                        f"endpoint cannot accept it. Use bisheng_code_interpreter to inspect the "
                        f"original file instead.",
                    }
                )
                continue
            new_content.append(block)

        if not changed:
            out.append(message)
            continue
        # A message whose blocks were ALL blocked would otherwise go out empty,
        # which some endpoints reject as hard as the original payload.
        if not new_content:
            new_content = [{"type": "text", "text": "[System] Unsupported attachment removed."}]
        out.append(message.model_copy(update={"content": new_content}))

    return out, stripped
