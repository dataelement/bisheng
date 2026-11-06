"""Markdown image annotate + request-scoped ImageRegistry (F061).

Does not import domain modules. Does not fetch pixels.
"""

from __future__ import annotations

import re
from typing import Any

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
        # list records which pictures the model actually looked at.
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


# "有哪些美女图片" wants the pictures on screen. Field / trend questions stay text.
# Only decides whether picture answers drop citation markers, never which picture is shown.
_SHOW_PICTURES_RE = re.compile(r"哪些.{0,12}图|美女|看图|显示图片|展示图片|有图|找出.{0,16}图")
_TEXT_ONLY_RE = re.compile(r"字段|走势|图意|图里|图上")


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


# The model shows a picture by writing its `![](url)` or a line that is only its id.
# An id inside a sentence is a mention, not a request to show the picture.
_ID_LINE_RE = re.compile(r"^[ \t]*[\u27e6\[［`]?(img#\d+)[\u27e7\]］`]?[ \t]*$")
_ID_LINE_PREFIX_RE = re.compile(r"^[ \t]*[\u27e6\[［`]?(?:i(?:m(?:g(?:#\d*)?)?)?)?[\u27e7\]］`]?[ \t]*$")


class ImageIdLineConverter:
    """Stream filter that renders a line holding only `img#N` as that picture.

    Text that cannot become such a line passes through at once; a line that
    still could is held until its newline or the final flush. ``inner`` is an
    optional downstream converter with the same feed / flush shape.
    """

    def __init__(self, registry: ImageRegistry, inner: Any | None = None) -> None:
        self._registry = registry
        self._inner = inner
        self._held = ""
        self._passing = False
        self.rendered_ids: list[str] = []

    @property
    def stats(self) -> Any:
        return getattr(self._inner, "stats", None)

    def _render(self, line: str) -> str:
        match = _ID_LINE_RE.match(line)
        if not match:
            return line
        image_id = match.group(1)
        entry = self._registry.get(image_id)
        if not entry:
            return line
        url = entry["url"]
        if image_id not in self.rendered_ids:
            self.rendered_ids.append(image_id)
        alt = url.rstrip("/").rsplit("/", 1)[-1] or image_id
        return f"![{alt}]({url})"

    def _convert(self, text: str) -> str:
        out: list[str] = []
        for piece in re.split(r"(\n)", text):
            if piece == "\n":
                out.append("\n" if self._passing else self._render(self._held) + "\n")
                self._held = ""
                self._passing = False
                continue
            if not piece:
                continue
            if self._passing:
                out.append(piece)
                continue
            candidate = self._held + piece
            if _ID_LINE_PREFIX_RE.match(candidate):
                self._held = candidate
            else:
                out.append(candidate)
                self._held = ""
                self._passing = True
        return "".join(out)

    def feed(self, text: str) -> str:
        out = self._convert(text or "")
        return self._inner.feed(out) if self._inner is not None else out

    def flush(self) -> str:
        tail = "" if self._passing else self._render(self._held)
        self._held = ""
        self._passing = False
        if self._inner is None:
            return tail
        return self._inner.feed(tail) + self._inner.flush()


def render_image_id_lines(text: str, registry: ImageRegistry) -> str:
    """Non-streaming form of ImageIdLineConverter."""
    converter = ImageIdLineConverter(registry)
    return converter.feed(text) + converter.flush()


def has_markdown_image(text: str) -> bool:
    return bool(_MARKDOWN_IMAGE_RE.search(text or ""))
