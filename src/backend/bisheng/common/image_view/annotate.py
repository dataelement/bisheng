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
    r"我将显示|如下图|相关图片如下|图片如下|见下图"
    r"|I(?:['’]ll| will) (?:show|display)"
    r"|here (?:is|are) the (?:image|picture|screenshot)s?",
    re.IGNORECASE,
)


def should_splice_viewed_images(answer: str) -> bool:
    """True when the model decided to show pictures but omitted `![](url)`."""
    return bool(_CLAIMED_DISPLAY_RE.search(answer or ""))


def missing_viewed_markdown(content: str, registry: ImageRegistry) -> str:
    """Markdown to append so the UI can render images the model already viewed.

    The model decides whether to show a picture by writing `![](url)`. Weak VL
    models often write "I will show img#7" instead — splice only then, and only
    for successfully viewed ids.
    """
    if not should_splice_viewed_images(content):
        return ""
    blocks: list[str] = []
    for image_id in registry.viewed_ids():
        entry = registry.get(image_id)
        if not entry:
            continue
        url = entry["url"]
        if url in content:
            continue
        alt = url.rstrip("/").rsplit("/", 1)[-1] or image_id
        blocks.append(f"![{alt}]({url})")
    if not blocks:
        return ""
    return "\n\n" + "\n\n".join(blocks)
