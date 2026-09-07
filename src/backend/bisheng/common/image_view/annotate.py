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

    def record_viewed(self, image_id: str, data_uri: str) -> None:
        self._viewed.append((image_id, data_uri))

    def pop_viewed(self) -> list[tuple[str, str]]:
        items = list(self._viewed)
        self._viewed.clear()
        return items

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
