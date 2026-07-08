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
