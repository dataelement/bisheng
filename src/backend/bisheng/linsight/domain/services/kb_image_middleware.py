"""F004 T059 (AC-49): pictures in knowledge results, for both runtime profiles.

Daily chat reads retrieved pictures with a model wrapper
(``common/image_view/vision_llm.py``). That wrapper cannot sit on the unified
factory (design §5 pitfall 12), so this middleware does the same job with the
pieces of ``common/image_view`` that carry no wrapper logic:

- ``annotate`` / ``ImageRegistry`` number every markdown picture of a knowledge
  result as ``⟦img#N⟧``;
- a ``view_image`` tool lets the model ask for the pixels of some numbers;
- the request after that tool call carries the pixels on ONE user message placed
  after the whole batch of tool messages (tool messages must stay contiguous,
  and some endpoints reject an image on a tool message).

How the four obstacles of pitfall 12 are handled:

1. Nothing is buffered. The model decides to call ``view_image``; no call is
   injected into its output, so the answer streams as usual.
2. No run state lives in this object. The numbering is rebuilt from the
   messages of the thread on every model call (same messages, same numbers), and
   pixels are fetched again when this process did not fetch them. A run that
   resumes on another node therefore keeps its numbers.
3. The retrieval tools are not changed. The numbering is added to the request
   here, for whichever knowledge tool the profile binds.
4. Pictures are attached to a user message once, here. No image block is put on
   a tool message, so ``ModelContentGuardMiddleware`` has nothing to move.

Mounted when the run's model reads images, or when the workbench image-reading
model is configured. In the second case that model looks at the pictures and the
run's model receives its notes as text.

Nothing here enters graph state: the numbering, the rules and the pixels are
added to the request only. Nothing here raises into the agent loop.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.constants import TAG_NOSTREAM
from langchain_core.tools import StructuredTool
from loguru import logger

from bisheng.common.image_view.annotate import ImageRegistry, annotate
from bisheng.common.image_view.fetch import fetch_and_encode
from bisheng.common.image_view.loop import IMAGE_VIEW_PROMPT_RULES
from bisheng.common.image_view.tool import MAX_IMAGES_PER_TURN, TOOL_NAME, ViewImageArgs

VIEW_IMAGE_GUIDE = (
    "以上规则只在检索结果里出现图片编号时适用。检索结果里图片后面的 `⟦img#N⟧` 是图片编号。需要知道图片里的内容时，调用 "
    f"{TOOL_NAME}(image_ids=[...]) 查看对应编号的图片，一次最多 {MAX_IMAGES_PER_TURN} 张；"
    "不需要图片内容的问题不要调用。本节只说明如何查看图片，不改变上文其它任何要求。"
)
VISION_NOTE_PREFIX = "图片查看结果："
VISION_UNAVAILABLE = "图片查看模型暂时不可用，无法读取这些图片的内容。请如实告诉用户，不要根据周围文字猜测图片内容。"

_ANCHOR = "⟦img#"
_VIEWED_RE = re.compile(r"Viewed (img#\d+)")


def _state_messages(state: Any) -> list:
    if isinstance(state, dict):
        return list(state.get("messages") or [])
    return list(getattr(state, "messages", None) or [])


def _plain_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block if isinstance(block, str) else str(block.get("text") or "")
            for block in content
            if isinstance(block, (str, dict))
        )
    return str(content or "")


class KbImageViewMiddleware(AgentMiddleware):
    """Number retrieved pictures, offer ``view_image``, attach the pixels after the tool batch.

    :param kb_tool_names: names of the knowledge tools whose results carry pictures.
    :param main_model_sees_images: the run's model reads images (``WSModel.visual``).
    :param vision_model: the workbench image-reading model; used only when the
        run's model does not read images.
    """

    def __init__(
        self,
        kb_tool_names: Iterable[str],
        *,
        main_model_sees_images: bool,
        vision_model: Any = None,
    ) -> None:
        super().__init__()
        self._kb_tool_names = frozenset(kb_tool_names)
        self._main_model_sees_images = bool(main_model_sees_images)
        self._vision_model = vision_model
        # Caches of THIS process, rebuilt from the thread when empty (see module note 2).
        self._registry = ImageRegistry()
        self._pixels: dict[str, str] = {}
        self._notes: dict[tuple[str, ...], str] = {}
        self.tools = [self._build_tool()]

    @property
    def name(self) -> str:
        return "KbImageView"

    # ------------------------------------------------------------------ tool

    def _build_tool(self) -> StructuredTool:
        async def _run(image_ids: list[str], quality: str = "standard") -> str:
            return await self._view(list(image_ids or []))

        return StructuredTool.from_function(
            func=None,
            coroutine=_run,
            name=TOOL_NAME,
            description=(
                "查看检索结果里带编号的图片。必填参数 image_ids（img#N 列表），选标题或上下文与问题相符的编号，"
                f"不要默认选 img#1，不要传 URL。一次最多 {MAX_IMAGES_PER_TURN} 张。"
            ),
            args_schema=ViewImageArgs,
        )

    async def _view(self, image_ids: list[str]) -> str:
        lines: list[str] = []
        for image_id in image_ids[:MAX_IMAGES_PER_TURN]:
            entry = self._registry.get(image_id)
            if not entry:
                lines.append(f"Image {image_id} is not available in this turn.")
                continue
            data_uri, reason = await self._fetch(image_id, entry["url"])
            if data_uri:
                # The next request shows the pixels; this line lets the answer copy the picture.
                lines.append(
                    f"Viewed {image_id} at standard quality. "
                    f"Include ![]({entry['url']}) only when these pixels answer the question; "
                    "omit this picture when they do not."
                )
            else:
                lines.append(f"Image {image_id} is not available ({reason or 'fetch'}).")
        overflow = image_ids[MAX_IMAGES_PER_TURN:]
        if overflow:
            lines.append(f"{', '.join(overflow)} not fetched: limit is {MAX_IMAGES_PER_TURN} images per turn.")
        return "\n".join(lines) or "No image id was given."

    async def _fetch(self, image_id: str, url: str) -> tuple[str | None, str | None]:
        cached = self._pixels.get(image_id)
        if cached:
            return cached, None
        try:
            result = await fetch_and_encode(url)
        except Exception as exc:
            # A picture that cannot be fetched is reported to the model, not raised into the loop.
            logger.opt(exception=True).warning("knowledge image {} could not be fetched", image_id)
            return None, type(exc).__name__
        if result.ok and result.data_uri:
            self._pixels[image_id] = result.data_uri
            return result.data_uri, None
        return None, result.reason

    # ----------------------------------------------------------------- hooks

    async def awrap_model_call(self, request, handler):
        try:
            prepared = await self._prepare(request)
        except Exception:
            logger.opt(exception=True).warning("knowledge image preparation failed; the request goes out unchanged")
            prepared = request
        return await handler(prepared)

    def wrap_model_call(self, request, handler):
        # The sync path cannot fetch pixels; it still numbers the pictures.
        try:
            prepared = self._numbered(request)
        except Exception:
            logger.opt(exception=True).warning("knowledge image preparation failed; the request goes out unchanged")
            prepared = request
        return handler(prepared)

    # ----------------------------------------------------------- preparation

    def _is_kb_result(self, message: Any) -> bool:
        return (
            isinstance(message, ToolMessage)
            and message.name in self._kb_tool_names
            and isinstance(message.content, str)
        )

    def _numbered(self, request):
        """Number the pictures of every knowledge result and say how to look at them."""
        # The whole thread, in order: the numbers do not depend on which part of the
        # history this request still carries (summarisation trims the request only).
        for message in _state_messages(getattr(request, "state", None)):
            if self._is_kb_result(message) and _ANCHOR not in message.content:
                annotate(message.content, self._registry)
        messages = []
        for message in request.messages:
            if self._is_kb_result(message) and _ANCHOR not in message.content:
                numbered = annotate(message.content, self._registry)
                if numbered != message.content:
                    message = message.model_copy(update={"content": numbered})
            messages.append(message)
        from deepagents.middleware._utils import append_to_system_message

        # Appended on every call, pictures or not: a section that appears with the
        # first picture changes the prompt mid-thread and the provider re-reads the
        # rest of it and the whole history (design 决策 15, §5 #36).
        system_message = append_to_system_message(
            request.system_message, f"{IMAGE_VIEW_PROMPT_RULES}\n\n{VIEW_IMAGE_GUIDE}"
        )
        if not len(self._registry):
            return request.override(system_message=system_message)
        return request.override(messages=messages, system_message=system_message)

    async def _prepare(self, request):
        prepared = self._numbered(request)
        if not len(self._registry):
            return prepared
        state_messages = _state_messages(getattr(request, "state", None)) or list(request.messages)
        batch = self._trailing_batch(state_messages)
        viewed_ids = self._viewed_ids(batch)
        if not viewed_ids:
            return prepared
        viewed: list[tuple[str, str]] = []
        for image_id in viewed_ids:
            entry = self._registry.get(image_id)
            if not entry:
                continue
            data_uri, _reason = await self._fetch(image_id, entry["url"])
            if data_uri:
                viewed.append((image_id, data_uri))
        if not viewed:
            return prepared
        extra = await self._pixels_message(viewed, state_messages, batch)
        return prepared.override(messages=self._insert_after_batch(list(prepared.messages), batch, extra))

    @staticmethod
    def _trailing_batch(messages: list) -> list[ToolMessage]:
        start = len(messages)
        while start > 0 and isinstance(messages[start - 1], ToolMessage):
            start -= 1
        return list(messages[start:])

    @staticmethod
    def _viewed_ids(batch: list[ToolMessage]) -> list[str]:
        found: list[str] = []
        for message in batch:
            if message.name != TOOL_NAME:
                continue
            for image_id in _VIEWED_RE.findall(_plain_text(message.content)):
                if image_id not in found:
                    found.append(image_id)
        return found[:MAX_IMAGES_PER_TURN]

    async def _pixels_message(
        self, viewed: list[tuple[str, str]], state_messages: list, batch: list[ToolMessage]
    ) -> HumanMessage:
        from bisheng.common.image_view.vision_llm import viewed_images_human_message

        pixels = viewed_images_human_message(viewed, self._registry)
        if self._main_model_sees_images:
            return pixels
        # The run's model cannot read images: the image-reading model looks, this model gets the notes.
        key = tuple(str(message.tool_call_id) for message in batch)
        note = self._notes.get(key)
        if note is None:
            note = await self._describe(pixels, state_messages)
            self._notes[key] = note
        return HumanMessage(content=note)

    async def _describe(self, pixels: HumanMessage, state_messages: list) -> str:
        from bisheng.common.image_view.vision_llm import _VISION_NOTE_TAIL, _VISION_OBSERVER_RULES

        question = next(
            (_plain_text(m.content) for m in reversed(state_messages) if isinstance(m, HumanMessage)),
            "",
        )
        try:
            # TAG_NOSTREAM: this call runs inside the agent's ``model`` node, so
            # without the tag LangGraph streams its tokens in ``stream_mode="messages"``
            # and the unified mapper publishes the picture notes as answer text.
            reply = await self._vision_model.ainvoke(
                [
                    SystemMessage(content=_VISION_OBSERVER_RULES),
                    HumanMessage(content=[{"type": "text", "text": f"用户的问题：{question}"}, *pixels.content]),
                ],
                config={"tags": [TAG_NOSTREAM]},
            )
        except Exception:
            logger.opt(exception=True).warning("the image-reading model failed; the answer goes on without pixels")
            return VISION_UNAVAILABLE
        text = _plain_text(getattr(reply, "content", reply)).strip()
        if not text:
            return VISION_UNAVAILABLE
        return f"{VISION_NOTE_PREFIX}\n{text}\n\n{_VISION_NOTE_TAIL}"

    @staticmethod
    def _insert_after_batch(messages: list, batch: list[ToolMessage], extra: HumanMessage) -> list:
        """Put ``extra`` right after the last tool message of ``batch`` (never inside the batch)."""
        call_ids = {message.tool_call_id for message in batch}
        last = max(
            (i for i, m in enumerate(messages) if isinstance(m, ToolMessage) and m.tool_call_id in call_ids),
            default=None,
        )
        if last is None:
            return [*messages, extra]
        # Tool messages of one AI message stay together: skip any that follow.
        while last + 1 < len(messages) and isinstance(messages[last + 1], ToolMessage):
            last += 1
        return [*messages[: last + 1], extra, *messages[last + 1 :]]
