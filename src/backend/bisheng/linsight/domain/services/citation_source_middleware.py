"""Per-turn citation source table and one-shot "add [Sn]" reminder (F069 P1).

``LinsightCitationSourceMiddleware`` gives the model, on EVERY model call, the
session's handle table (``S1 知识库·<title>（<loc>）`` ...) as an ephemeral
HumanMessage at the tail of the request — the strongest position and the one
that survives deepagents' summarization truncating old tool arguments (design
§5 #8). When the previous turn wrote an ``output/*.md`` deliverable that carries
zero ``[Sn]`` runs, the main-graph instance appends a second ephemeral message
asking the model to patch the handles in with ``edit_file`` — at most once per
file per session (AC-15), deduplicated through the session handle table in
Redis because middleware instances are rebuilt on every resume / continue
(design §5 #13).

Why ``awrap_model_call`` and not ``wrap_tool_call`` (design §3 decision 5):
deepagents' ``FilesystemMiddleware`` evicts large tool results by REPLACING the
ToolMessage wholesale, so a hint appended to a tool result is discarded exactly
when it matters; a soft hint placed there historically produced a 79-turn fixed
point. Appending to ``request.messages`` never enters graph state — the same
shape as ``_with_wrap_up_nudge`` in ``resilience_middleware`` and
``_repeat_nudge`` in ``tool_loop_middleware``.

Invariants: never touches graph state, never returns ``status=error``, never
raises into the agent loop — any preparation failure degrades to the untouched
request (a Linsight tool exception kills the whole task).
"""

from __future__ import annotations

import posixpath
import re
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from loguru import logger

from bisheng.citation.domain.services.citation_handle_service import (
    HANDLE_TTL_SECONDS,
    count_handle_runs,
    handle_redis_key,
)
from bisheng.core.cache.redis_manager import get_redis_client

SOURCE_TABLE_HEADER = "【本轮可用来源编号】（写正文时在句末标 [Sn]）"
SOURCE_TABLE_OVERFLOW_LINE = "其余编号见检索结果。"
_TITLE_MAX_CHARS = 40
_TYPE_LABEL_WEB = "网页"
_TYPE_LABEL_KB = "知识库"

NUDGE_TEMPLATE = (
    "output/{basename} 已写入成功，但正文没有来源编号。"
    "请用 edit_file 在依据检索资料的句子末尾补上 [Sn]（编号见上方来源表），不要重写整份文件。"
)
NUDGE_LOG_PREFIX = "[linsight-citation-nudge]"

# Deliverable markdown only: ``output/report.md``, ``/output/a/b.md``; never
# ``scratch/…`` or ``output/x.html``.
_DELIVERABLE_MD_RE = re.compile(r"^/?output/.+\.md$", re.IGNORECASE)
_WRITE_TOOLS = {"write_file": "content", "edit_file": "new_string"}


class LinsightCitationSourceMiddleware(AgentMiddleware):
    """Ephemeral source table (+ one-shot handle reminder) on every model call.

    ``budget_sink`` is the dict the resilience middleware publishes its
    ``soft_landing`` flag into: while the run is wrapping up, a reminder to
    re-edit the file would only burn the last model calls (design decision 2).
    """

    def __init__(
        self,
        scope: Any,
        budget_sink: dict | None = None,
        is_subagent: bool = False,
        max_rows: int = 150,
    ) -> None:
        super().__init__()
        self.tools = []
        self._scope = scope
        self._budget_sink = budget_sink if budget_sink is not None else {}
        self._is_subagent = bool(is_subagent)
        self._max_rows = max(1, int(max_rows))
        # fast path; Redis is the cross-instance truth (design §5 #13)
        self._nudged_paths: set[str] = set()

    @property
    def name(self) -> str:
        # Distinct names so the main-graph and researcher instances can coexist
        # in one graph family (langchain rejects duplicate middleware names).
        return "LinsightCitationSourceSub" if self._is_subagent else "LinsightCitationSource"

    # ------------------------------------------------------------------
    # hooks
    # ------------------------------------------------------------------
    async def awrap_model_call(self, request, handler):
        try:
            prepared = await self._prepare(request, use_redis=True)
        except Exception:
            logger.opt(exception=True).warning(
                f"{NUDGE_LOG_PREFIX} preparation failed, passing request through ({self.name})"
            )
            prepared = request
        return await handler(prepared)

    def wrap_model_call(self, request, handler):
        # The sync path (not used by the linsight worker) cannot await Redis:
        # dedupe falls back to the in-process set alone.
        try:
            prepared = self._prepare_sync(request)
        except Exception:
            logger.opt(exception=True).warning(
                f"{NUDGE_LOG_PREFIX} preparation failed, passing request through ({self.name})"
            )
            prepared = request
        return handler(prepared)

    # ------------------------------------------------------------------
    # preparation
    # ------------------------------------------------------------------
    def _active(self) -> bool:
        scope = self._scope
        return bool(scope is not None and getattr(scope, "enabled", False) and getattr(scope, "entries", None))

    async def _prepare(self, request, *, use_redis: bool):
        if not self._active():
            return request
        extra = [HumanMessage(content=self._render_source_table())]
        for path in self._nudge_candidates(request):
            if await self._was_nudged(path, use_redis=use_redis):
                continue
            self._nudged_paths.add(path)
            if use_redis:
                await self._mark_nudged(path)
            logger.info(f"{NUDGE_LOG_PREFIX} session={self._svid()} file={path}")
            extra.append(HumanMessage(content=NUDGE_TEMPLATE.format(basename=posixpath.basename(path))))
        return request.override(messages=[*request.messages, *extra])

    def _prepare_sync(self, request):
        if not self._active():
            return request
        extra = [HumanMessage(content=self._render_source_table())]
        for path in self._nudge_candidates(request):
            if path in self._nudged_paths:
                continue
            self._nudged_paths.add(path)
            logger.info(f"{NUDGE_LOG_PREFIX} session={self._svid()} file={path}")
            extra.append(HumanMessage(content=NUDGE_TEMPLATE.format(basename=posixpath.basename(path))))
        return request.override(messages=[*request.messages, *extra])

    def _svid(self) -> str:
        return str(getattr(self._scope, "svid", "") or "")

    # ------------------------------------------------------------------
    # source table
    # ------------------------------------------------------------------
    def _render_source_table(self) -> str:
        entries = sorted(self._scope.entries or [], key=lambda e: _handle_number(e.get("handle", "")))
        overflow = len(entries) > self._max_rows
        if overflow:
            entries = entries[-self._max_rows :]  # the most recently allocated handles
        lines = [SOURCE_TABLE_HEADER]
        for entry in entries:
            lines.append(_render_row(entry))
        if overflow:
            lines.append(SOURCE_TABLE_OVERFLOW_LINE)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # nudge detection
    # ------------------------------------------------------------------
    def _nudge_candidates(self, request) -> list[str]:
        """Deliverable ``output/*.md`` paths written in the LAST tool batch with zero handles."""
        if self._is_subagent or self._budget_sink.get("soft_landing"):
            return []
        # Graph state, not ``request.messages``: the outer resilience middleware
        # may already have appended a wrap-up HumanMessage to the request list,
        # which would hide the trailing ToolMessage batch (see ``_repeat_nudge``).
        messages = _state_messages(getattr(request, "state", None)) or list(getattr(request, "messages", []) or [])
        batch_start = len(messages)
        while batch_start > 0 and isinstance(messages[batch_start - 1], ToolMessage):
            batch_start -= 1
        if batch_start == len(messages):
            return []
        tool_calls = _tool_calls_before(messages, batch_start)
        found: list[str] = []
        for tool_msg in messages[batch_start:]:
            tool_name = getattr(tool_msg, "name", None)
            if tool_name not in _WRITE_TOOLS or _is_error_result(tool_msg):
                continue
            args = tool_calls.get(getattr(tool_msg, "tool_call_id", None)) or {}
            path = _normalize_path(args.get("file_path"))
            if not path or not _DELIVERABLE_MD_RE.match(path):
                continue
            written = args.get(_WRITE_TOOLS[tool_name])
            if not isinstance(written, str):
                continue
            if count_handle_runs(written) > 0:
                continue
            if path not in found:
                found.append(path)
        return found

    # ------------------------------------------------------------------
    # dedupe (Redis field ``nudged:<svid>:<path>`` on the session handle table)
    # ------------------------------------------------------------------
    def _redis_field(self, path: str) -> str:
        return f"nudged:{self._svid()}:{path}"

    async def _was_nudged(self, path: str, *, use_redis: bool) -> bool:
        if path in self._nudged_paths:
            return True
        if not use_redis:
            return False
        try:
            redis_client = await get_redis_client()
            value = await redis_client.ahget(handle_redis_key(self._scope.session_id), self._redis_field(path))
        except Exception:
            logger.opt(exception=True).warning(
                f"{NUDGE_LOG_PREFIX} dedupe read failed session={self._svid()} file={path}"
            )
            return False
        if value:
            self._nudged_paths.add(path)
            return True
        return False

    async def _mark_nudged(self, path: str) -> None:
        try:
            redis_client = await get_redis_client()
            await redis_client.ahset(
                handle_redis_key(self._scope.session_id),
                key=self._redis_field(path),
                value="1",
                expiration=HANDLE_TTL_SECONDS,
            )
        except Exception:
            logger.opt(exception=True).warning(
                f"{NUDGE_LOG_PREFIX} dedupe write failed session={self._svid()} file={path}"
            )


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _handle_number(handle: str) -> int:
    digits = "".join(ch for ch in str(handle) if ch.isdigit())
    return int(digits) if digits else 0


def _render_row(entry: dict) -> str:
    handle = str(entry.get("handle", "") or "")
    type_label = _TYPE_LABEL_WEB if str(entry.get("type", "") or "") == "web" else _TYPE_LABEL_KB
    title = str(entry.get("title", "") or "")[:_TITLE_MAX_CHARS]
    loc = str(entry.get("loc", "") or "")
    row = f"{handle} {type_label}·{title}"
    if loc:
        row += f"（{loc}）"
    return row


def _state_messages(state: object) -> list:
    if isinstance(state, dict):
        return state.get("messages") or []
    return getattr(state, "messages", None) or []


def _tool_calls_before(messages: list, end: int) -> dict[str, dict]:
    """``tool_call_id -> args`` of the AIMessage that issued the trailing batch."""
    for idx in range(end - 1, -1, -1):
        msg = messages[idx]
        if isinstance(msg, AIMessage):
            calls = getattr(msg, "tool_calls", None) or []
            return {
                str(tc.get("id")): (tc.get("args") or {})
                for tc in calls
                if isinstance(tc, dict) and tc.get("id") is not None
            }
    return {}


def _is_error_result(tool_msg: ToolMessage) -> bool:
    if getattr(tool_msg, "status", None) == "error":
        return True
    return _content_to_text(getattr(tool_msg, "content", "")).lstrip().startswith("Error")


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return str(content or "")


def _normalize_path(raw: Any) -> str:
    if not isinstance(raw, str):
        return ""
    path = raw.strip().replace("\\", "/")
    while path.startswith("/"):
        path = path[1:]
    return path
