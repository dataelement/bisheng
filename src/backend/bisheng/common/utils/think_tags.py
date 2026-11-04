"""Helpers to strip reasoning-model ``<think>`` markers from text.

Some reasoning models (e.g. qwen3.5) leave the ``<think>`` / ``</think>``
boundary markers in their output — either inlined into the answer ``content``
or left dangling inside the extracted ``reasoning_content`` (a vLLM/SGLang
reasoning-parser boundary artifact). BiSheng has no central place that strips
them, so they leak into user-visible surfaces (chat titles, the linsight
thinking narration).

These two helpers cover the two distinct semantics such surfaces need:

- ``strip_think_block`` — the block content is noise to DISCARD (answers/titles).
- ``strip_reasoning_tags`` — the block content is the thinking we want to KEEP;
  only the markers are noise (the reasoning narration stream).

NOTE: several other call sites still inline their own
``re.sub("<think>.*</think>", "", ...)`` (``knowledge_imp.parse_document_title``,
``knowledge/rag/.../abstract``, ``common/chat/utils``). They can be migrated onto
``strip_think_block`` later; left untouched here to bound this change.
"""

import re


class ThinkBlockStreamFilter:
    """Discard inline reasoning without leaking tags split across deltas."""

    _tag = re.compile(r"</?think\s*>", re.IGNORECASE)

    def __init__(self):
        self._buffer = ""
        self._inside = False

    def feed(self, text: str) -> str:
        self._buffer += text
        visible = []
        while self._buffer:
            start = self._buffer.find("<")
            if start != 0:
                end = start if start > 0 else len(self._buffer)
                if not self._inside:
                    visible.append(self._buffer[:end])
                self._buffer = self._buffer[end:]
                continue
            match = self._tag.match(self._buffer)
            if match:
                self._inside = not self._buffer.startswith("</")
                self._buffer = self._buffer[match.end() :]
                continue
            lowered = self._buffer.lower()
            if any(tag.startswith(lowered) for tag in ("<think", "</think")) or re.fullmatch(r"</?think\s*", lowered):
                break
            if not self._inside:
                visible.append("<")
            self._buffer = self._buffer[1:]
        return "".join(visible)

    def flush(self) -> str:
        # An unfinished tag or reasoning block is withheld, never shown at EOF.
        self._buffer = ""
        self._inside = False
        return ""


# A complete reasoning block. Non-greedy so multiple blocks are each removed
# (the legacy copies use greedy ``.*``, which over-deletes across blocks).
_THINK_BLOCK_RE = re.compile(r"<think\s*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)

# A single ``<think>`` / ``</think>`` marker, tolerating a streaming-truncated
# tail (a bare ``<think`` with no closing ``>``, as happens when the token is
# split across stream chunks — the leak seen in the linsight narration).
_THINK_TAG_RE = re.compile(r"</?think\s*>?", re.IGNORECASE)


def strip_think_block(text: str) -> str:
    """Remove complete ``<think>...</think>`` regions, keeping surrounding text.

    Use for a full (non-streaming) **answer / title** string, where the
    reasoning inside the block is noise to discard. Any stray unpaired marker
    left over (e.g. a lone ``<think>`` with no close) is dropped too, and the
    result is stripped.
    """
    if not text:
        return text
    cleaned = _THINK_BLOCK_RE.sub("", text)
    cleaned = _THINK_TAG_RE.sub("", cleaned)
    return cleaned.strip()


def strip_reasoning_tags(text: str) -> str:
    """Remove only the ``<think>`` / ``</think>`` markers, keeping inner text.

    Use for a **reasoning_content narration** stream, where the text between
    the markers IS the thinking to show — only the boundary markers (including
    a streaming-truncated ``<think``) are noise. Internal spacing is preserved
    so per-chunk deltas still concatenate cleanly downstream.
    """
    if not text:
        return text
    return _THINK_TAG_RE.sub("", text)
