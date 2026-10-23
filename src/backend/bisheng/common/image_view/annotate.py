"""Markdown image annotate + request-scoped ImageRegistry (F061).

Does not import domain modules. Does not fetch pixels.
"""

from __future__ import annotations

import re

# Keep citation private-use (U+E200) untouched; only rewrite markdown images.
_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_ANCHOR_LEFT = "\u27e6"  # ⟦
_ANCHOR_RIGHT = "\u27e7"  # ⟧


class ImageRegistry:
    """Request-scoped map of img#N -> {url}. Same URL reuses the same N."""

    def __init__(self) -> None:
        self._by_id: dict[str, dict[str, str]] = {}
        self._url_to_id: dict[str, str] = {}
        self._viewed: list[tuple[str, str]] = []
        # Survives pop_viewed: the queue feeds the next HumanMessage, this
        # list is what the answer-side markdown splice uses.
        self._viewed_ids: list[str] = []

    def record_viewed(self, image_id: str, data_uri: str) -> None:
        self._viewed.append((image_id, data_uri))
        if image_id not in self._viewed_ids:
            self._viewed_ids.append(image_id)

    def pop_viewed(self) -> list[tuple[str, str]]:
        items = list(self._viewed)
        self._viewed.clear()
        return items

    def viewed_ids(self) -> list[str]:
        return list(self._viewed_ids)

    def register(self, url: str) -> str:
        existing = self._url_to_id.get(url)
        if existing:
            return existing
        image_id = f"img#{len(self._by_id) + 1}"
        self._by_id[image_id] = {"url": url}
        self._url_to_id[url] = image_id
        return image_id

    def get(self, image_id: str) -> dict[str, str] | None:
        return self._by_id.get(image_id)

    def ids(self) -> list[str]:
        """img#N in registration order."""
        return list(self._by_id)

    def __len__(self) -> int:
        return len(self._by_id)


def annotate(text: str, registry: ImageRegistry) -> str:
    """Append ⟦img#N⟧ after each markdown image. Same URL shares one N."""

    def _replace(match: re.Match[str]) -> str:
        url = match.group(2)
        image_id = registry.register(url)
        return f"{match.group(0)}{_ANCHOR_LEFT}{image_id}{_ANCHOR_RIGHT}"

    return _MARKDOWN_IMAGE_RE.sub(_replace, text)


# Weak VL models claim they will show the image but omit `![](url)`.
# The model's answer is the decision; we only repair a forgotten markdown tag.
_CLAIMED_DISPLAY_RE = re.compile(
    r"我将显示|如下图|相关图片如下|图片如下|见下图|该图片清晰"
    r"|I(?:['’]ll| will) (?:show|display)"
    r"|here (?:is|are) the (?:image|picture|screenshot)s?",
    re.IGNORECASE,
)


def should_splice_viewed_images(answer: str) -> bool:
    """True when the model decided to show pictures but omitted `![](url)`."""
    return bool(_CLAIMED_DISPLAY_RE.search(answer or ""))


# "有哪些美女图片" wants the pictures on screen. Field / trend questions stay text.
_SHOW_PICTURES_RE = re.compile(r"哪些.{0,12}图|美女|看图|显示图片|展示图片|有图|找出.{0,16}图")
_TEXT_ONLY_RE = re.compile(r"字段|走势|图意|图里|图上")
_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")


def question_wants_pictures(question: str) -> bool:
    text = question or ""
    if _TEXT_ONLY_RE.search(text):
        return False
    return bool(_SHOW_PICTURES_RE.search(text))


_IMG_ID = re.compile(r"img#\d+")


def cited_display_ids(text: str, registry: ImageRegistry | None = None) -> list[str]:
    """img# ids the model wrote. Relevance is the model's decision, not a second pass."""
    del registry
    found: list[str] = []
    for match in _IMG_ID.finditer(text or ""):
        image_id = match.group(0)
        if image_id not in found:
            found.append(image_id)
    return found


def _has_rendered_image(content: str, url: str) -> bool:
    """True when a real markdown image is outside code, so the UI will draw it."""
    visible = _INLINE_CODE_RE.sub("", _FENCED_CODE_RE.sub("", content or ""))
    return bool(re.search(r"!\[[^\]]*\]\(" + re.escape(url) + r"\)", visible))


def missing_viewed_markdown(
    content: str,
    registry: ImageRegistry,
    *,
    question: str = "",
    only_ids: list[str] | None = None,
) -> str:
    """Append markdown only when the model decided to show a picture and forgot `![](url)`.

    Which pictures match the question is the model's call: it writes `![](url)`
    for those. This repair uses the ids it named. With no ids, it only fills in
    a forgotten tag when exactly one picture was viewed. Several viewed pictures
    and no named id must not be appended together.
    """
    del question
    if not should_splice_viewed_images(content):
        return ""
    named = cited_display_ids(content) if only_ids is None else only_ids
    viewed = set(registry.viewed_ids())
    source = [image_id for image_id in named if image_id in viewed]
    if not source:
        viewed_ids = registry.viewed_ids()
        source = viewed_ids if len(viewed_ids) == 1 else []
    blocks: list[str] = []
    for image_id in source:
        entry = registry.get(image_id)
        if not entry:
            continue
        url = entry["url"]
        if _has_rendered_image(content, url):
            continue
        alt = url.rstrip("/").rsplit("/", 1)[-1] or image_id
        blocks.append(f"![{alt}]({url})")
    if not blocks:
        return ""
    return "\n\n" + "\n\n".join(blocks)
