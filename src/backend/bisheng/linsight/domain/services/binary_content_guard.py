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

from bisheng.linsight.domain.services.workspace_backend import BINARY_READ_ERROR_PREFIX

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


# Inlined rather than importing `string`/`re`: frozenset membership is one pass and
# keeps this module import-light.
_B64_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=-_")
_B64_SAMPLE_CHARS = 8192


def _is_valid_base64(value: Any) -> bool:
    """Cheap structural check that ``value`` could be base64 (no decode).

    The failure mode this exists for is a payload that is really replace-decoded
    binary: such a string is dominated by U+FFFD from its very first bytes, so an
    alphabet test on the head is decisive. Two deliberate looseness choices:

    - only the head is sampled, keeping the cost constant for multi-MB images on a
      check that runs for every outgoing request;
    - padding is NOT required and the URL-safe alphabet is accepted, because a
      length-mod-4 rule would reject unpadded-but-valid payloads — false-flagging a
      good image is worse than passing a bad one, which the provider rejects anyway.
    """
    if not isinstance(value, str) or not value:
        return False
    head = "".join(value[:_B64_SAMPLE_CHARS].split())
    if not head:
        return False
    return set(head) <= _B64_CHARS


def _broken_image_payload(block: dict) -> bool:
    """True when an ``image`` block carries a payload that is not valid base64.

    ``image`` is the one multimodal shape we forward to the provider, so a corrupt
    one is worse than a dropped one: the request either 400s or the model
    hallucinates over noise. Data-URI (`image_url`) forms are checked after the
    comma; a plain http(s) URL has no payload to validate and passes through.
    """
    block_type = block.get("type")
    if block_type == "image":
        # Absent payload -> nothing to validate (e.g. a provider-side file id).
        payload = block.get("base64") or block.get("data")
        return payload is not None and not _is_valid_base64(payload)
    if block_type == "image_url":
        raw = block.get("image_url")
        url = raw.get("url") if isinstance(raw, dict) else raw
        if not isinstance(url, str) or not url.startswith("data:"):
            return False
        _, _, payload = url.partition(",")
        return not _is_valid_base64(payload)
    return False


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

        # The backend now refuses binary reads itself (workspace_backend
        # ``_binary_read_result``) and marks the error. It cannot know whether the
        # code interpreter is bound this run, so upgrade its terse message to the
        # routed hint here — the one place that does know.
        if isinstance(content, str) and BINARY_READ_ERROR_PREFIX in content:
            logger.info("[linsight-binary-guard] backend refused a binary read for {}", file_path)
            return _replace_tool_content(result, _binary_read_hint(file_path, self._has_code_interpreter))

        # Backstop for payloads the backend never saw (a different backend, a tool
        # that reads bytes itself). Post-P0 the workspace no longer produces this.
        if isinstance(content, str) and _looks_like_mojibake(content):
            logger.info("[linsight-binary-guard] read_file returned mojibake for {}", file_path)
            return _replace_tool_content(result, _binary_read_hint(file_path, self._has_code_interpreter))

        # A corrupt image survives `_non_text_block_types` (image is allowed) but is
        # useless to the model and may 400 the request — treat it like any binary.
        if isinstance(content, list) and any(isinstance(b, dict) and _broken_image_payload(b) for b in content):
            logger.info("[linsight-binary-guard] read_file returned an invalid image payload for {}", file_path)
            return _replace_tool_content(result, _binary_read_hint(file_path, self._has_code_interpreter))

        return result


def _replace_tool_content(message: ToolMessage, text: str) -> ToolMessage:
    """Rebuild ``message`` with plain-text content, dropping multimodal kwargs.

    ``additional_kwargs`` carries deepagents' ``read_file_media_type`` marker on
    the multimodal path; it is meaningless once the payload is text, so it goes.
    """
    return message.model_copy(update={"content": text, "additional_kwargs": {}})


class ModelContentGuardMiddleware(AgentMiddleware):
    """Strip provider-hostile content blocks from every outgoing model request.

    Args:
        has_code_interpreter: whether the sandboxed code interpreter is bound this
            run. Gates the replacement text's suggested route, same lockstep rule
            as ``BinaryReadGuardMiddleware`` and the uploaded-files pointer block.
    """

    def __init__(self, has_code_interpreter: bool = False) -> None:
        super().__init__()
        self._has_code_interpreter = has_code_interpreter

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        sanitized, stripped = _sanitize_messages(request.messages, self._has_code_interpreter)
        if stripped:
            logger.warning("[linsight-content-guard] stripped {} block(s) before model call", sorted(stripped))
            request = request.override(messages=sanitized)
        return await handler(request)


def _sanitize_messages(messages: list, has_code_interpreter: bool = False) -> tuple[list, set[str]]:
    """Return ``(messages, stripped_types)`` with blocked blocks turned into text."""
    route = (
        " Use bisheng_code_interpreter to inspect the original file instead."
        if has_code_interpreter
        else " No code execution tool is available this run; answer from the parsed text view."
    )
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
                        f"endpoint cannot accept it.{route}",
                    }
                )
                continue
            # `image` stays (it is the one shape endpoints accept) — unless its
            # payload is not real base64, in which case forwarding it either 400s
            # the request or feeds the model noise it will confabulate over.
            if isinstance(block, dict) and _broken_image_payload(block):
                stripped.add("image:invalid-base64")
                changed = True
                new_content.append(
                    {
                        "type": "text",
                        "text": "[System] An image attachment was removed here: its payload is not "
                        f"valid base64 and cannot be rendered.{route}",
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


def build_binary_guards(has_code_interpreter: bool) -> list[AgentMiddleware]:
    """The pair of guards every graph that owns ``read_file`` must carry.

    Middleware is per-subgraph in langgraph: a subagent's model and tool calls are
    NOT wrapped by the parent graph's stack, so each one needs its own instances.
    Returning them from a single factory means a new subagent (e.g. the planned
    data-analyst) gets both by construction instead of by remembering to.
    """
    return [
        BinaryReadGuardMiddleware(has_code_interpreter=has_code_interpreter),
        ModelContentGuardMiddleware(has_code_interpreter=has_code_interpreter),
    ]
