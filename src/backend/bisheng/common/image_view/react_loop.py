"""Vision answer for knowledge-space / channel chat.

Pixels go to the visual model configured on the Image View builtin tool.
Does not construct ChatResponse and does not call view_image.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessage
from loguru import logger

from bisheng.common.image_view.annotate import (
    ImageRegistry,
    cited_display_ids,
    missing_viewed_markdown,
    question_wants_pictures,
)
from bisheng.common.image_view.fetch import fetch_and_encode
from bisheng.common.image_view.loop import (
    _last_user_question,
    _suggested_ids_for,
    failed_image_ids,
    prepare_vision_messages,
    resolve_image_view_llm,
)
from bisheng.common.image_view.tool import MAX_IMAGES_PER_TURN
from bisheng.common.image_view.vision_llm import viewed_images_human_message

REACT_RECURSION_LIMIT = 8


_CATALOG_LINE = re.compile(
    r"^\s*(?:[-*•]\s*)?(?:"
    r"(?:\[img#\d+\]|⟦img#\d+⟧|img#\d+)\s*(?:→|->)\s*\S+"
    r"|(?:\[img#\d+\]|⟦img#\d+⟧|img#\d+)\s*[:：]\s*/\S+"
    r"|\S+\s+(?:\[img#\d+\]|⟦img#\d+⟧)"
    r")\s*$"
)
_BARE_ID_LINE = re.compile(r"^\s*\[img#\d+\]\s*$")
_DESC_MARK = re.compile(r"(?:\[img#\d+\]|img#\d+)\s*[:：]")
_PROCESS_LINE = re.compile(
    r"我需要查看|请允许我先查看|先查看这些图片|包含以下图片|无法查看图片|无法从这些图片|"
    r"view_image|涉及色情|公序良俗|是否需要我继续|如需进一步处理|如您希望仅查找|"
    r"若您能提供|请单独请求|未在当前问题|根据当前查看|根据提供的图片内容"
)
_LIMIT_CLAUSE = re.compile(r"(?:单轮最多|未在本次调用|本次调用中加载|请单独请求)")
_IMG_TOKEN = re.compile(r"\[img#\d+\]|⟦img#\d+⟧|［img#\d+］|img#\d+")
_FILE_LABEL = re.compile(r"(?<!/)image\d+(?:\.\w+)?", re.IGNORECASE)
_PLACEHOLDER = re.compile(r"\*{2,}|＊{2,}|。{2,}|…+|\.{3,}")
_REST_FOLLOW = re.compile(r"^\s*(?:[-*•]\s*)?其余图片.*$")
_INVENTORY_HEADING = re.compile(r"包含的图片如下|其中包含的图片|参考资料，其中包含")
_REJECTION_BULLET = re.compile(
    r"^\s*[-*•]\s*.*(?:无美女|无女性|无车票|无证书|不属|未显示|非证书|不是.{0,12}图|系统后台管理界面)"
)
_NONMATCH_DUMP = re.compile(r"未在当前问题|无明确证书|也无证书")
# The model renames img#6 to "-6" after being told not to write 第N张.
_DASH_ID = re.compile(r"(?:^|[\s，,；;])-\d+\s*(?=为|是|未|：|:|，|,)")
_AFFIRM_SHOW = re.compile(r"是的[，,]?\s*有.{0,16}图")
_DENIAL_LINE = re.compile(r"因此没有|均未显示|所有图片均未|没有.{0,8}的图片")
_ORDINAL = re.compile(r"第[0-9一二三四五六七八九十两]+张")
_CITE_SPAN = re.compile("\ue200.*?\ue202", re.DOTALL)
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)\s]+\)")
_FENCED_IMAGE = re.compile(r"`+\s*(!\[[^\]]*\]\([^)\s]+\))\s*`+")
_BULLET_PREFIX = re.compile(r"^\s*[-*•]\s*")
# Anything left in a bullet label after ids, filenames, and wrappers is a real name.
_LABEL_NOISE = re.compile(
    r"img#\d+|image\d+(?:\.\w+)?|['\"“”‘’`]+|和|或|[（(][^）)]*[）)]|\s+",
    re.IGNORECASE,
)


def _hide_image_ids(line: str) -> str:
    clauses = [part for part in re.split(r"[；;]", line) if part.strip() and not _LIMIT_CLAUSE.search(part)]
    text = "；".join(clauses)
    text = _PLACEHOLDER.sub("", text)
    text = _FILE_LABEL.sub("", text)
    text = re.sub(r"其中[ \t]*和[ \t]*", "其中", text)
    text = _IMG_TOKEN.sub("\x00", text)
    text = _DASH_ID.sub("", text)
    text = re.sub(r"(?:[ \t]*\x00[ \t]*(?:和|或|、)?[ \t]*)+", "", text)
    text = re.sub(r"其中[，,]\s*的", "其中", text)
    text = re.sub(r"^[，,]\s*", "", text)
    text = re.sub(r"[（(][ \t、,，和或'\"“”‘’`]*[）)]", "", text)
    text = re.sub(r"['\"“”‘’]{2,}", "", text)
    text = re.sub(r"`+\s*`+", "", text)
    text = re.sub(r"即\s*([。．])", r"\1", text)
    text = re.sub(r"([-*•][ \t]*)[:：][ \t]*", r"\1", text)
    text = re.sub(r"^[:：][ \t]*", "", text)
    text = re.sub(r"而\s*是", "另外，是", text)
    text = re.sub(r"是[ \t]*([。．])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+([，。；：])", r"\1", text)
    text = text.strip(" ；")
    if text in {"-", "*", "•", "；", ""}:
        return ""
    if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]|!\[", text):
        return ""
    return text


def _inventory_line(line: str) -> bool:
    """A catalog, a per-picture rejection, or the heading that introduces them."""
    if (
        _CATALOG_LINE.match(line)
        or _BARE_ID_LINE.match(line)
        or _REST_FOLLOW.match(line)
        or _comparison_bullet(line)
        or _REJECTION_BULLET.match(line)
        or _NONMATCH_DUMP.search(line)
    ):
        return True
    return bool(_INVENTORY_HEADING.search(line) and "![" not in line)


def _drop_contradicted_denial(text: str) -> str:
    """When the model both denies and then shows a match, keep the match."""
    if not _AFFIRM_SHOW.search(text):
        return text
    kept = [line for line in text.splitlines() if _AFFIRM_SHOW.search(line) or not _DENIAL_LINE.search(line)]
    return "\n".join(kept)


def _strip_picture_citations(text: str, question: str) -> str:
    """Picture answers should not carry retrieval footnotes."""
    if not question_wants_pictures(question):
        return text
    if "\ue200" not in text and "ue200" not in text.lower():
        return text
    text = _CITE_SPAN.sub("", text)
    return text.replace("\ue200", "").replace("\ue201", "").replace("\ue202", "")


def cited_ids_on_shown_lines(text: str) -> list[str]:
    """img# ids on lines the user will see. A rejection catalog does not count."""
    found: list[str] = []
    for line in (text or "").splitlines():
        line = _FENCED_IMAGE.sub(r"\1", line)
        if _inventory_line(line):
            continue
        if _PROCESS_LINE.search(line) and not _DESC_MARK.search(line):
            continue
        for image_id in cited_display_ids(line):
            if image_id not in found:
                found.append(image_id)
    return found


def _comparison_bullet(line: str) -> bool:
    """A list item whose name slot is only an id, a filename, or empty wrappers."""
    if not _BULLET_PREFIX.match(line):
        return False
    body = _BULLET_PREFIX.sub("", line, count=1)
    label = body.split("：", 1)[0].split(":", 1)[0]
    if _MD_IMAGE.search(label):
        return False
    return _LABEL_NOISE.sub("", label) == ""


def _visible_image_line(line: str) -> str:
    """Render a picture the model wrapped in backticks, and drop an empty name in front of it."""
    line = _FENCED_IMAGE.sub(r"\1", line)
    images = _MD_IMAGE.findall(line)
    if not images:
        return line
    prefix = _MD_IMAGE.sub("", line)
    prefix = re.sub(r"对应的图片(?:为)?|图片为|如下", "", prefix)
    if _comparison_bullet(line) or not re.search(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", prefix):
        return "\n".join(images)
    return line


def _drop_ordinal_rebuttal(text: str) -> str:
    """Drop sentences that name pictures as 第N张. That order is not what the user sees."""
    if len(_ORDINAL.findall(text)) < 2:
        return text
    kept: list[str] = []
    for line in text.splitlines():
        images = _MD_IMAGE.findall(line)
        sentences = re.split(r"(?<=[。！？])", line)
        visible = "".join(part for part in sentences if part.strip() and not _ORDINAL.search(part)).strip()
        if images and not _MD_IMAGE.search(visible):
            visible = "\n".join(images) if not visible else f"{visible}\n" + "\n".join(images)
        if visible:
            kept.append(visible)
    return "\n".join(kept)


def strip_view_narration(text: str) -> str:
    """Drop image catalogs, tool narration, and internal img# ids from a vision answer."""
    kept: list[str] = []
    for line in (text or "").splitlines():
        line = _FENCED_IMAGE.sub(r"\1", line)
        if _inventory_line(line):
            images = _MD_IMAGE.findall(line)
            if images and "![" in line:
                kept.extend(images)
            continue
        if "![" in line:
            line = _visible_image_line(_hide_image_ids(line))
            if line:
                kept.append(line)
            continue
        mark = _DESC_MARK.search(line)
        if mark and _PROCESS_LINE.search(line[: mark.start()]):
            line = line[mark.start() :].lstrip(" -—")
        elif _PROCESS_LINE.search(line):
            continue
        line = _hide_image_ids(line)
        if not line or _REST_FOLLOW.match(line):
            continue
        kept.append(line)
    cleaned = _drop_ordinal_rebuttal(_drop_contradicted_denial("\n".join(kept)))
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _ids_to_view(messages: list, registry: ImageRegistry) -> list[str]:
    suggested = [image_id for image_id in _suggested_ids_for(messages) if registry.get(image_id)]
    if suggested:
        return suggested[:MAX_IMAGES_PER_TURN]
    failed = failed_image_ids(messages)
    return [image_id for image_id in registry.ids() if image_id not in failed][:MAX_IMAGES_PER_TURN]


async def _attach_viewed_pixels(messages: list, registry: ImageRegistry) -> list:
    viewed: list[tuple[str, str]] = []
    for image_id in _ids_to_view(messages, registry):
        entry = registry.get(image_id)
        if not entry:
            continue
        result = await fetch_and_encode(entry["url"])
        if result.ok and result.data_uri:
            registry.record_viewed(image_id, result.data_uri)
            viewed.append((image_id, result.data_uri))
    prepared = prepare_vision_messages(messages)
    if viewed:
        prepared.append(viewed_images_human_message(viewed, registry))
    return prepared


def _chunk_text(chunk: Any) -> str:
    content = getattr(chunk, "content", "") or ""
    return content if isinstance(content, str) else ""


async def run_react_vision_stream(
    llm: Any,
    messages: list,
    registry: ImageRegistry,
    *,
    visual: bool,
    user_id: int | None = None,
    app_type: Any | None = None,
) -> AsyncIterator[Any]:
    """Yield one cleaned answer. Pixels go to the Image View tool's visual model."""
    if not visual or len(registry) == 0:
        logger.info("image_view skip visual={} registry_size={}", visual, len(registry))
        async for chunk in llm.astream(messages):
            yield chunk
        return

    vision_llm = await resolve_image_view_llm(user_id=user_id, app_type=app_type)
    if vision_llm is None:
        async for chunk in llm.astream(messages):
            yield chunk
        return

    logger.info("image_view configured model registry_size={}", len(registry))
    prepared = await _attach_viewed_pixels(messages, registry)
    question = _last_user_question(messages)
    parts: list[str] = []
    async for chunk in vision_llm.astream(prepared):
        text = _chunk_text(chunk)
        if text:
            parts.append(text)
    raw = "".join(parts)
    cited_ids = cited_ids_on_shown_lines(raw)
    cleaned = _strip_picture_citations(strip_view_narration(raw), question)
    visible = cleaned or ""
    if cleaned:
        yield AIMessage(content=cleaned)
    extra = missing_viewed_markdown(visible, registry, question=question, only_ids=cited_ids)
    if extra:
        logger.info("image_view splice markdown cited_ids={}", cited_ids)
        yield AIMessage(content=extra)
