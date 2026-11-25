"""F004 T030: persistence projector of a ``direct`` run (design 决策 8).

Consumes the unified events of one run and, when the run ends, writes the answer
row daily chat writes today: ``ChatMessage`` with ``category="agent_answer"``,
``type="end"``, ``message`` = JSON ``{msg, events}``, ``files`` = the generated
files. The row is built by ``chat_service.build_daily_answer_row`` and its
citations and files go through ``save_message_citations`` and
``_promote_generated_files``, the helpers of the SSE path, so history, export,
audit and F016 downloads read it without knowing which path wrote it. The only
addition is ``run_id`` in ``extra``. A run the user stopped stores
``extra = {"status": "stopped", "run_id": ...}`` with the content generated so
far: no ``error`` key, so it is not a failed row.

Files (design §7 item 11): the ``file`` events of the run point at
``workspace/{conversation}/output/...``, which a later run may overwrite. When the
row is written, each of those objects is copied to
``chat/{partition}/answers/{run_id}/`` and the row's ``files`` point at the
copies (``chat_attachment.copy_answer_files``), so an old answer keeps its
content. The copy's ``file_id`` differs from the event's; the item keeps the
event's id in ``workspace_file_id``. A file whose copy fails stays on the row
with the workspace object and the event's id.

The projector is a pure function of the event sequence: the ``events`` list it
keeps is translation bookkeeping of ONE run in ONE process (like
``StreamEventMapper``'s context), not run state. The run state of record is the
Redis event stream; feeding that stream's events to a new projector rebuilds the
same row.

Interface (the run driver attaches projectors through its sink list):
``async on_event(event)`` and ``async aclose()``. ``async before_terminal(event)``
is asked by the driver before it writes the terminal event: it makes the answer's
file copies and returns ``{"answer_files": [...]}`` for the event's ``data``, so
the client learns the row's file ids with the event (``run_events.ANSWER_FILES_FIELD``).
"""

from __future__ import annotations

import json
import mimetypes
import time
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.tools import BaseTool
from loguru import logger

from bisheng.common.services.failure_context import FailureContextAdapter
from bisheng.core.storage.chat_attachment import WORKSPACE_FILE_ID_KEY, copy_answer_files
from bisheng.database.models.message import ChatMessage
from bisheng.linsight.domain.schemas import run_events
from bisheng.linsight.domain.services import file_events
from bisheng.linsight.domain.services.workspace_backend import workspace_prefix_for
from bisheng.workstation.domain.services import chat_service, direct_run_turn
from bisheng.workstation.domain.services.daily_memory import redact_args, redact_error, redact_results

# What today's daily chat stores when a turn is torn down before it finished
# (``persist_interrupted_turn("stream interrupted")``).
INTERRUPTED_REASON = "stream interrupted"
_TOOL_FAILED = "Tool execution failed."
# ``error`` of a tool call that was still running when the user stopped the run.
STOPPED_TOOL_NOTE = "stopped by user"


def _now_ms() -> int:
    return int(time.time() * 1000)


class DirectRunProjector:
    """Write the ``ChatMessage`` answer row of one ``direct`` run.

    :param run_id: stored in the row's ``extra``.
    :param conversation_id: ``chat_id`` of the row.
    :param user_id: owner of the conversation (``conversation.user_id``).
    :param sender: display name of the model, as today's row stores it.
    :param tools: the run's tools; files their code executors left under
        ``output/`` become the row's ``files`` (F016).
    :param promote_user_id: user the generated files are promoted for; defaults
        to ``user_id``.
    :param storage_partition: partition of the chat attachments (None = the
        user's own, as in the SSE path).
    :param citation_items: returns the citation registry items collected during
        the run (``CitationRegistryCollector.list_items``). Only the items the
        answer text cites are bound to the row.
    :param tool_meta: tool name -> ``{"display_name", "tool_type"}``, the map the
        SSE path builds with ``_build_tool_meta``.
    :param on_persisted: awaited with the saved row (memory binding, title, ...).
    :param object_store: ``await object_store()`` returns the object storage the
        per-answer file copies are made in; defaults to the MinIO storage.
    """

    def __init__(
        self,
        *,
        run_id: str,
        conversation_id: str,
        user_id: int,
        sender: str,
        tools: list[BaseTool] | None = None,
        promote_user_id: int | None = None,
        storage_partition: str | None = None,
        citation_items: Callable[[], list] | None = None,
        tool_meta: dict[str, dict[str, Any]] | None = None,
        on_persisted: Callable[[ChatMessage], Awaitable[None]] | None = None,
        object_store: Callable[[], Awaitable[Any]] | None = None,
        clock_ms: Callable[[], int] = _now_ms,
    ):
        self.run_id = run_id
        self.conversation_id = conversation_id
        self.user_id = user_id
        self.sender = sender
        self._tools = tools or []
        self._promote_user_id = promote_user_id if promote_user_id is not None else user_id
        self._storage_partition = storage_partition
        self._citation_items = citation_items
        self._tool_meta = tool_meta or {}
        self._on_persisted = on_persisted
        self._object_store = object_store
        self._clock_ms = clock_ms

        self.events: list[dict[str, Any]] = []
        self.final_msg = ""
        self.answer_row: ChatMessage | None = None
        # T059: the sources bound to the saved row (the legacy end frame sends them),
        # and the memory flags the ``on_persisted`` hook may leave for that frame.
        self.citations: list = []
        self.memory_signal: dict | None = None
        self._thinking_idx: int | None = None
        self._thinking_call_id: str | None = None
        self._inflight_tools: dict[str, int] = {}
        self._seen_event = False
        self._persisted = False
        self._content_safety = False
        # file_id -> ``data`` of the run's ``file`` events (T055); a file written
        # again keeps its place and takes the newer data.
        self._files: dict[str, dict[str, Any]] = {}
        # The answer's file items once ``before_terminal`` made the copies; None
        # until then (``_persist`` makes them itself).
        self._answer_file_items: list[dict] | None = None

    def seed_files(self, files: list | None) -> None:
        """Files the run announced before this projector existed (a resumed or
        recovered run): the ``files`` of the Redis snapshot."""
        for data in files or []:
            if isinstance(data, dict):
                self._on_file(data)

    @property
    def message_id(self) -> int | None:
        """Id of the saved answer row; None until the run ended."""
        return self.answer_row.id if self.answer_row is not None else None

    # -- interface -----------------------------------------------------------

    async def on_event(self, event: dict) -> None:
        if self._persisted:
            return
        self._seen_event = True
        event_type = event.get("type")
        data = event.get("data") or {}
        ts = event.get("ts")
        now_ms = int(ts) if ts else self._clock_ms()

        if event_type == run_events.TEXT:
            self._on_text(data, now_ms)
        elif event_type == run_events.THINKING:
            self._on_thinking(data, now_ms)
        elif event_type == run_events.TOOL_CALL:
            self._on_tool_call(data, now_ms)
        elif event_type == run_events.FILE:
            self._on_file(data)
        elif event_type == run_events.RUN_FINISHED:
            if data.get("content_safety"):
                # The output scanner hit: the stored answer is the replacement
                # only, like ``chat_service.persist_safety_replacement``.
                self._replace_with_safety_reply(str(data.get("auto_reply") or ""))
            await self._persist(now_ms, error=None)
        elif event_type == run_events.RUN_STOPPED:
            # The user stopped the run: its own mark, not an error row (design §7
            # item 2). What was generated so far is kept.
            await self._persist(now_ms, error=None, stopped=True)
        elif event_type == run_events.RUN_FAILED:
            await self._persist(now_ms, error=self._failure_extra(data))
        # plan / ask_user / steer_* / queued / run_started carry nothing the answer
        # row stores.

    async def before_terminal(self, event: dict) -> dict[str, Any] | None:
        """Fields to add to the ``data`` of the terminal event about to be written.

        Makes the per-answer file copies now (instead of in ``_persist``) and
        returns them as ``answer_files``: the same items the answer row stores.
        None when the row keeps no generated file (no file event, or the answer
        is replaced by the content-safety reply).
        """
        if self._persisted or self._answer_file_items is not None:
            return None
        if event.get("type") not in run_events.TERMINAL_EVENT_TYPES:
            return None
        if event.get("type") == run_events.RUN_FINISHED and (event.get("data") or {}).get("content_safety"):
            return None
        self._answer_file_items = await self._answer_files()
        if not self._answer_file_items:
            return None
        return {run_events.ANSWER_FILES_FIELD: [dict(item) for item in self._answer_file_items]}

    async def aclose(self) -> None:
        """Save what exists if the run was torn down without a terminal event."""
        if self._persisted or not self._seen_event:
            return
        logger.warning(
            "direct run projector closed without a terminal event; saving the partial answer run_id={} chat_id={}",
            self.run_id,
            self.conversation_id,
        )
        await self._persist(self._clock_ms(), error={"error_msg": INTERRUPTED_REASON})

    # -- event accumulation (the shapes of chat_service's ``events`` log) ------

    def _replace_with_safety_reply(self, auto_reply: str) -> None:
        """Drop thinking, tool calls and the blocked text; keep only the auto reply."""
        self._thinking_idx = None
        self._thinking_call_id = None
        self._inflight_tools.clear()
        self.final_msg = auto_reply
        self.events = list(chat_service.blocked_answer_payload(auto_reply)["events"])
        self._content_safety = True

    def _on_file(self, data: dict) -> None:
        file_id = str(data.get("file_id") or "")
        if not file_id or not file_events.is_deliverable_path(str(data.get("path") or "")):
            # Only files of the conversation workspace's ``output/`` can be stored
            # on the row: their object key is known without trusting the event.
            return
        self._files[file_id] = dict(data)

    def _workspace_files(self) -> list[dict]:
        """The run's ``file`` events as F016 attachment items, pointing at the workspace.

        Same ``file_id`` as the event; ``object_name`` is the workspace object in
        the main bucket. ``_answer_files`` repoints them at the answer's copies.
        """
        prefix = workspace_prefix_for(self.conversation_id)
        items = []
        for data in list(self._files.values())[-chat_service.GENERATED_FILES_LIMIT :]:
            path = file_events.normalize_rel(str(data["path"]))
            name = str(data.get("name") or path.rsplit("/", 1)[-1])
            items.append(
                {
                    "file_id": str(data["file_id"]),
                    "file_name": name,
                    "path": path,
                    "type": mimetypes.guess_type(name)[0] or "",
                    "size": data.get("size"),
                    "source": chat_service.GENERATED_FILE_SOURCE,
                    "object_name": file_events.workspace_object_key(prefix, path),
                }
            )
        return items

    async def _answer_files(self) -> list[dict]:
        """The files of this run as the answer row stores them: one copy per answer.

        The workspace object stays where it is (live ``file`` events and the
        workspace panel read it). An item whose copy failed keeps the workspace
        object and the event's ``file_id``; ``copy_answer_files`` logged why.
        """
        items = self._workspace_files()
        if not items:
            return items
        partition = self._storage_partition or str(self._promote_user_id)
        client = None
        if self._object_store is not None:
            try:
                client = await self._object_store()
            except Exception:
                logger.exception(
                    "direct run answer run_id={} chat_id={}: object storage unavailable; "
                    "{} generated file(s) stay on the workspace objects",
                    self.run_id,
                    self.conversation_id,
                    len(items),
                )
                return items
        await copy_answer_files(items, partition, self.run_id, minio_client=client)
        kept = sum(1 for item in items if WORKSPACE_FILE_ID_KEY not in item)
        if kept:
            logger.error(
                "direct run answer run_id={} chat_id={}: {} of {} generated file(s) have no copy; "
                "the row points at the workspace object, which a later run may overwrite",
                self.run_id,
                self.conversation_id,
                kept,
                len(items),
            )
        return items

    def _on_text(self, data: dict, now_ms: int) -> None:
        text = str(data.get("text") or "")
        if not text:
            return
        self._close_thinking(now_ms)
        self.final_msg += text
        if self.events and self.events[-1].get("type") == "text":
            self.events[-1]["content"] = self.events[-1].get("content", "") + text
        else:
            self.events.append({"type": "text", "content": text})

    def _on_thinking(self, data: dict, now_ms: int) -> None:
        if data.get("namespace"):
            # A subagent's reasoning is not part of the answer row, like the
            # nested tool events the SSE path skips.
            return
        call_id = data.get("call_id")
        if self._thinking_idx is None or call_id != self._thinking_call_id:
            self._close_thinking(now_ms)
            self.events.append({"type": "thinking", "content": "", "started_at": now_ms})
            self._thinking_idx = len(self.events) - 1
            self._thinking_call_id = call_id
        self.events[self._thinking_idx]["content"] += str(data.get("text") or "")

    def _close_thinking(self, now_ms: int) -> None:
        if self._thinking_idx is None:
            return
        entry = self.events[self._thinking_idx]
        entry["duration_ms"] = max(0, now_ms - entry.get("started_at", now_ms))
        entry["ended_at"] = now_ms
        self._thinking_idx = None
        self._thinking_call_id = None

    def _on_tool_call(self, data: dict, now_ms: int) -> None:
        extra_info = data.get("extra_info") or {}
        if extra_info.get("namespace"):
            return
        call_id = str(data.get("call_id") or "")
        name = str(data.get("name") or "")
        if data.get("status") != "end":
            self._close_thinking(now_ms)
            # The runner puts the tool's display data on the event (``extra_info``).
            meta = self._tool_meta.get(name) or {}
            self.events.append(
                {
                    "type": "tool_call",
                    "tool_call_id": call_id,
                    "tool_name": name,
                    "display_name": extra_info.get("display_name") or meta.get("display_name") or name,
                    "tool_type": extra_info.get("tool_type") or meta.get("tool_type") or "tool",
                    # F132: memory tool inputs are redacted before they are stored.
                    "args": redact_args(name, data.get("params") or {}),
                    "started_at": now_ms,
                }
            )
            self._inflight_tools[call_id] = len(self.events) - 1
            return

        output = data.get("output")
        results = redact_results(name, output, chat_service._parse_tool_results)
        error = redact_error(name, chat_service._extract_tool_error(output))
        idx = self._inflight_tools.pop(call_id, None)
        if idx is not None:
            entry = self.events[idx]
            entry["results"] = results
            entry["error"] = error
            entry["ended_at"] = now_ms
            entry["duration_ms"] = max(0, now_ms - entry.get("started_at", now_ms))
        else:
            # End frame without a start frame: synthesise the entry, as the SSE path does.
            entry = {
                "type": "tool_call",
                "tool_call_id": call_id,
                "tool_name": name,
                "display_name": extra_info.get("display_name") or name,
                "tool_type": extra_info.get("tool_type") or "tool",
                "args": {},
                "results": results,
                "error": error,
                "started_at": now_ms,
                "ended_at": now_ms,
                "duration_ms": 0,
            }
            self.events.append(entry)
        info = extra_info.get("failure_info") or FailureContextAdapter.from_payload(results)
        if info:
            entry["failure_info"] = info

    def _finalise_dangling(self, now_ms: int, error_msg: str | None) -> None:
        """Close the open thinking segment and tool calls that never ended, so a
        reloaded row does not render them as still running."""
        self._close_thinking(now_ms)
        for idx in self._inflight_tools.values():
            entry = self.events[idx]
            if entry.get("ended_at") is not None:
                continue
            entry["ended_at"] = now_ms
            if entry.get("error") is None:
                entry["error"] = error_msg or "tool did not complete"
            entry.setdefault("results", [])
            entry["duration_ms"] = max(0, now_ms - entry.get("started_at", now_ms))
        self._inflight_tools.clear()

    @staticmethod
    def _failure_extra(data: dict) -> dict[str, Any]:
        """``run_failed`` data in the keys today's failed row stores in ``extra``."""
        detail = str(data.get("detail") or "")
        extra: dict[str, Any] = {"error_msg": detail}
        if data.get("code") is not None:
            extra["error_code"] = data["code"]
        if data.get("reason"):
            extra["error_type"] = data["reason"]
        extra["detail"] = detail
        if data.get("reference_id"):
            extra["reference_id"] = data["reference_id"]
        if data.get("failure_info"):
            extra["failure_info"] = data["failure_info"]
        return extra

    # -- persistence -----------------------------------------------------------

    async def _persist(self, now_ms: int, *, error: dict[str, Any] | None, stopped: bool = False) -> None:
        # Set first: a second terminal event or ``aclose`` must not write twice.
        # A failure below propagates to the run driver; nothing is retried here,
        # because a retry after a half-finished write could double the row.
        self._persisted = True
        self._finalise_dangling(now_ms, STOPPED_TOOL_NOTE if stopped else (error or {}).get("error_msg"))

        # The text already carries citation markers (the runner converts ``[Sn]``
        # before it writes a text event). Bind exactly the sources the text cites:
        # from this execution's collector when there is one, else from the citation
        # runtime cache (a relay run, a run closed by another process, a source of an
        # earlier turn). A text without markers costs no lookup.
        collected = self._citation_items() if self._citation_items is not None else []
        citation_items = await chat_service.select_cited_items(collected, self.final_msg)
        self.citations = list(citation_items)
        if not self._content_safety:
            # Design §7 item 17: the audit line of the legacy daily chat, at the same
            # point (after the cited sources are selected, before the row is saved).
            # A blocked answer writes none, as the legacy stream returns before it.
            direct_run_turn.log_citation_audit(self.run_id, citation_items)
        files = await chat_service._promote_generated_files(
            self._tools, self.conversation_id, self._promote_user_id, self._storage_partition
        )
        if not self._content_safety:
            # T055: the files the run announced live, each as this answer's own copy
            # (design §7 item 11). A blocked answer keeps none, like the legacy
            # replacement row.
            answer_files = self._answer_file_items
            if answer_files is None:
                answer_files = await self._answer_files()
            files = [*files, *answer_files]
        row = chat_service.build_daily_answer_row(
            user_id=self.user_id,
            chat_id=self.conversation_id,
            sender=self.sender,
            db_content={"msg": self.final_msg, "events": self.events},
            files=files,
            error=error,
        )
        extra = (
            json.loads(chat_service.blocked_answer_extra()) if self._content_safety else json.loads(row.extra or "{}")
        )
        if stopped:
            # ``extra.status == "stopped"`` and no ``error`` key: the history shows
            # "stopped", not a failure.
            extra = {**extra, "status": run_events.STATUS_STOPPED}
        row.extra = json.dumps({**extra, "run_id": self.run_id}, ensure_ascii=False)

        saved = await chat_service.ChatMessageDao.ainsert_one(row)
        self.answer_row = saved
        await chat_service.save_message_citations(
            message_id=saved.id,
            items=citation_items,
            chat_id=self.conversation_id,
            flow_id="",
        )
        logger.info(
            "direct run answer saved run_id={} chat_id={} message_id={} files={} citations={} error={}",
            self.run_id,
            self.conversation_id,
            saved.id,
            len(files),
            len(citation_items),
            error is not None,
        )
        if self._on_persisted is not None:
            await self._on_persisted(saved)
