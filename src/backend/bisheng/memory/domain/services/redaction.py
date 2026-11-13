"""Redaction of memory tool events (design decision 10, AC-09).

Every place that persists or streams a tool call replaces the input and output of
tools whose name starts with ``memory_`` with ``{"redacted": true, "op", "item_ids"}``.
The owner reads the original text through the memory API by item id.
"""

from __future__ import annotations

import json
import re

from loguru import logger

MEMORY_TOOL_PREFIX = "memory_"
REPLAY_TEXT = "记忆操作已完成"
WRITE_OUTPUT_KEY = "memory_tool"
_ID_RE = re.compile(r"\bid=([^\s\[\]（]+)")


# The built-in memory tools. Redaction matches these exact names only, so a
# third-party tool that merely starts with "memory_" keeps its normal behaviour.
MEMORY_TOOL_NAMES = frozenset({"memory_write", "memory_search"})


def is_memory_tool(name: str | None) -> bool:
    return bool(name) and str(name) in MEMORY_TOOL_NAMES


def is_reserved_tool_name(name: str | None) -> bool:
    """``memory_`` is a reserved prefix for author-configured tools while memory is on."""
    return bool(name) and str(name).startswith(MEMORY_TOOL_PREFIX)


def is_memory_tool_output(text) -> bool:
    """Fixed-prefix check used where only the content is known (workspace offload)."""
    if not isinstance(text, str):
        return False
    from bisheng.memory.domain.services.search import SEARCH_HEADER

    stripped = text.lstrip()
    return stripped.startswith(SEARCH_HEADER) or stripped.startswith('{"' + WRITE_OUTPUT_KEY + '"')


def _as_obj(payload):
    if isinstance(payload, (dict, list)):
        return payload
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except (ValueError, TypeError):
            return payload
    content = getattr(payload, "content", None)
    if content is not None:
        return _as_obj(content)
    return payload


def redact_tool_event(name: str | None, payload, op: str | None = None):
    """Return a content-free stand-in for a memory tool's input or output."""
    if not is_memory_tool(name):
        return payload
    obj = _as_obj(payload)
    item_ids: list[str] = []
    if isinstance(obj, dict):
        if obj.get("redacted") is True:
            return {"redacted": True, "op": obj.get("op") or op, "item_ids": list(obj.get("item_ids") or [])}
        op = op or obj.get("op") or obj.get("action")
        for key in ("item_id", "related_item_id"):
            if obj.get(key):
                item_ids.append(str(obj[key]))
    elif isinstance(obj, str):
        item_ids = list(dict.fromkeys(_ID_RE.findall(obj)))
    if not op:
        op = "search" if str(name) == "memory_search" else "write"
    return {"redacted": True, "op": op, "item_ids": item_ids}


def redact_text(name: str | None, payload) -> str:
    """JSON-string form of ``redact_tool_event`` for string-typed sinks."""
    if not is_memory_tool(name):
        return payload
    return json.dumps(redact_tool_event(name, payload), ensure_ascii=False)


def replay_placeholder() -> str:
    """Neutral text a later turn sees instead of a redacted memory tool result."""
    return REPLAY_TEXT


def split_reserved_tools(tools: list) -> tuple[list, list]:
    """Drop author-configured tools that use the reserved ``memory_`` prefix."""
    kept, dropped = [], []
    for tool in tools or []:
        (dropped if is_reserved_tool_name(getattr(tool, "name", None)) else kept).append(tool)
    for tool in dropped:
        logger.warning("tool {!r} uses the reserved memory_ prefix; the built-in memory tool wins", tool.name)
    return kept, dropped
