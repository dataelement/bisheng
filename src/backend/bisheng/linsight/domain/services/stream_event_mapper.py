"""F035 Track A · TA-2: LangGraph chunk -> BaseEvent normalization layer.

``StreamEventMapper`` is a **pure translator**. It sits between
``agent.astream(stream_mode=["updates","messages","values"], subgraphs=True)``
and the existing ``LinsightWorkflowTask._handle_event`` dispatch table. It
converts raw LangGraph/deepagents chunks into the existing ``BaseEvent`` family
(``GenerateSubTask`` / ``TaskStart`` / ``TaskEnd`` / ``ExecStep`` /
``NeedUserInput``), which ``_handle_event`` then maps onto the 10 frozen
``MessageEventType`` values. The frontend LPOP side is therefore unchanged.

Design references (features/v2.6.0/035-linsight-task-mode/design.md):
- §3.2 position & responsibility
- §3.3 full mapping table + §3.3.1 task_id stability
- §3.4 ordering / idempotency
- §3.5 termination收口
- §3.7 boundary anomalies (reordering, orphan end, namespace, dedup)
- §4.3 interrupt -> NeedUserInput

Hard rule: this module touches **no Redis and no MySQL**. All side effects
remain in ``_handle_event`` so ordering and dual-write semantics stay
single-sourced.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from bisheng_langchain.linsight.event import (
    BaseEvent,
    ExecStep,
    GenerateSubTask,
    NeedUserInput,
    TaskEnd,
    TaskStart,
)

# Output longer than this is truncated and flagged via extra_info.truncated
# (design §3.7 "超长截断"). Conservative default; the real value can be tuned.
_MAX_OUTPUT_CHARS = 8000

# Tool names whose ExecStep should render as a "knowledge" step_type
# (design §3.3 step_type variants; §5.2 knowledge RAG).
_KNOWLEDGE_TOOL_HINTS = ("search_knowledge", "knowledge_base", "knowledge_search")

# A reasoning model occasionally *writes* a tool call as plain text at the tail of
# its reasoning (e.g. ``play_search\n{"search_query": ...}``) instead of emitting a
# real function call. That leaks into the thinking row as raw text. Match a trailing
# ``<identifier>\n<json-object>`` block so we can strip only genuine pseudo-calls.
_PSEUDO_TOOL_TAIL = re.compile(r"\n[ \t]*[A-Za-z_][A-Za-z0-9_]*[ \t]*\n[ \t]*(\{.*\})[ \t]*$", re.DOTALL)


def _strip_pseudo_tool_call(text: str) -> str:
    """Drop a trailing ``toolname\\n{json}`` block a model wrote into its reasoning.

    Conservative: only strips when the tail's braces parse as JSON, so normal
    thinking that merely ends with prose (or unbalanced braces) is left intact.
    """
    if not text:
        return text
    match = _PSEUDO_TOOL_TAIL.search(text)
    if not match:
        return text
    try:
        json.loads(match.group(1))
    except (ValueError, TypeError):
        return text
    return text[: match.start()].rstrip()


def _stable_task_id(svid: str, content: str) -> str:
    """``md5(svid + ":" + content)[:8]`` — design §3.3.1 rule 1."""
    return hashlib.md5(f"{svid}:{content}".encode()).hexdigest()[:8]


def _truncate(text: str | None) -> tuple[str | None, bool]:
    if text is None:
        return None, False
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text, False
    return text[:_MAX_OUTPUT_CHARS] + "…", True


@dataclass
class _TodoProjection:
    """One projected todo item kept across ``write_todos`` updates."""

    task_id: str
    content: str
    status: str


@dataclass
class _OpenCall:
    """Buffered tool-call *start* frame, keyed by call_id (design §3.4)."""

    call_id: str
    task_id: str
    name: str
    params: Any
    step_type: str
    call_reason: str | None
    namespace: str | None


@dataclass
class StreamContext:
    """Mutable per-run state carried by the mapper.

    Holds only translation bookkeeping — no I/O handles. Design §3.2.
    """

    svid: str
    # content/positional projection of the latest write_todos snapshot
    todos: list[_TodoProjection] = field(default_factory=list)
    # task_id of the single in_progress todo (deepagents TodoList semantics:
    # at most one in_progress at a time). None during planning/wrap-up.
    current_in_progress_task_id: str | None = None
    # call_id -> open start frame, awaiting its end frame
    open_calls: dict[str, _OpenCall] = field(default_factory=dict)
    # call_id -> buffered orphan end payload (end arrived before start, §3.7)
    orphan_ends: dict[str, dict[str, Any]] = field(default_factory=dict)
    # call_id shared by the deltas of the current contiguous thinking stream;
    # None means "no open thinking segment" (closed by any non-thinking chunk).
    current_thinking_call_id: str | None = None
    # monotonic counter giving each thinking segment a distinct, stable call_id
    thinking_seq: int = 0
    # terminal收口 dedup: first terminal wins, later ones dropped (§3.7)
    terminated: bool = False


class StreamEventMapper:
    """Translate ``(mode, chunk)`` tuples into ``BaseEvent`` instances."""

    def __init__(self, svid: str):
        self.ctx = StreamContext(svid=svid)

    # -- public entry ------------------------------------------------------

    def normalize(
        self,
        mode: str,
        chunk: Any,
        namespace: tuple[str, ...] | None = None,
    ) -> list[BaseEvent]:
        """Map a single stream chunk to 0..N events.

        ``mode`` is one of ``updates`` / ``messages`` / ``values``. When
        ``subgraphs=True`` the caller threads the subgraph ``namespace`` tuple
        so subagent steps can be归并 under ``step_type="subagent"`` (§3.7).
        """
        # No more events are emitted after a terminal frame (§3.7 dedup;
        # interrupt交织 tail-chunk discard §3.7).
        if self.ctx.terminated:
            return []

        ns = self._namespace_str(namespace)
        try:
            if mode == "updates":
                result = self._handle_updates(chunk, ns)
            elif mode == "messages":
                result = self._handle_messages(chunk, ns)
            elif mode == "values":
                result = self._handle_values(chunk, ns)
            else:
                logger.warning("stream_event_mapper: unknown stream_mode=%s", mode)
                return []
        except Exception:
            # A malformed chunk must not crash the executor; log and skip.
            # Termination收口 is driven explicitly via terminate().
            logger.exception("stream_event_mapper failed on mode=%s", mode)
            return []

        # A contiguous thinking stream keeps one call_id; any other chunk
        # (tool call, answer text, todo update, …) closes the segment so the
        # next thinking block starts a fresh row. Thinking chunks emit exactly
        # one thinking ExecStep and must not reset their own segment.
        if not self._is_thinking_continuation(result):
            self.ctx.current_thinking_call_id = None
        return result

    @staticmethod
    def _is_thinking_continuation(events: list[BaseEvent]) -> bool:
        return len(events) == 1 and isinstance(events[0], ExecStep) and events[0].step_type == "thinking"

    def terminate(self, error: str | None = None, reason: str | None = None) -> list[tuple[str, dict[str, Any]]]:
        """Produce the terminal收口 pair (design §3.5).

        Returns a list of ``(message_event_type_value, data)`` tuples to be
        pushed by the executor. These have no 1:1 ``BaseEvent`` (mapping table
        rows 8 & 10) so they are emitted as raw event-type/data pairs rather
        than ``BaseEvent`` instances. Idempotent: the first call wins, later
        calls return ``[]`` so ``task_terminated`` is the single last frame.
        """
        if self.ctx.terminated:
            return []
        self.ctx.terminated = True

        out: list[tuple[str, dict[str, Any]]] = []
        if error is not None:
            out.append(("error_message", {"error": error}))
        out.append(
            (
                "task_terminated",
                {
                    "message": reason or error or "Task terminated",
                    "session_id": self.ctx.svid,
                },
            )
        )
        return out

    # -- updates mode ------------------------------------------------------

    def _handle_updates(self, chunk: Any, ns: str | None) -> list[BaseEvent]:
        if not isinstance(chunk, dict):
            return []

        # __interrupt__ surfaces at the tail of the updates stream (§4.3)
        if "__interrupt__" in chunk:
            return self._handle_interrupt(chunk["__interrupt__"])

        events: list[BaseEvent] = []
        # Each value is a per-node state delta; look for a todos write.
        for node_output in chunk.values():
            if not isinstance(node_output, dict):
                continue
            todos = node_output.get("todos")
            if todos is not None:
                # design #1 §5.2(a): a subagent carries its OWN write_todos
                # (TodoListMiddleware). Its todos arrive namespaced (ns set) and
                # would otherwise be merged into the main graph's single
                # ``ctx.todos`` via _diff_todos, polluting the main plan with
                # bogus GenerateSubTask/TaskStart/TaskEnd. Only the main graph
                # (ns is None) may drive the plan. Dropping namespaced updates is
                # also safe re: __interrupt__: subagents have NO interrupt source
                # by construction (design §3.1), so no __interrupt__ ever surfaces
                # under a namespace — only subagent *tool-call* steps do (those
                # are routed via the messages stream and still surface). This keeps
                # main-graph behavior identical.
                if ns:
                    continue
                events.extend(self._diff_todos(todos))
        return events

    def _handle_interrupt(self, interrupts: Any) -> list[BaseEvent]:
        """``{"__interrupt__": (Interrupt(value=...),)}`` -> NeedUserInput."""
        if not interrupts:
            return []
        first = interrupts[0] if isinstance(interrupts, (list, tuple)) else interrupts
        payload = getattr(first, "value", first)
        if not isinstance(payload, dict):
            payload = {"reason": str(payload)}

        # Single graph, single interrupt point at a time: route to the current
        # in_progress todo, else the session-level pseudo task (§4.3).
        task_id = self.ctx.current_in_progress_task_id or self.ctx.svid
        return [
            NeedUserInput(
                task_id=task_id,
                call_reason=payload.get("reason") or payload.get("call_reason") or "",
                params=payload.get("params"),
                step_type="call_user_input",
            )
        ]

    def _diff_todos(self, new_todos: list[dict[str, Any]]) -> list[BaseEvent]:
        """3-level diff alignment of write_todos snapshots (design §3.3.1)."""
        old = self.ctx.todos
        used_old_idx: set[int] = set()
        new_projection: list[_TodoProjection] = []
        newly_generated: list[_TodoProjection] = []
        status_events: list[BaseEvent] = []

        for pos, item in enumerate(new_todos):
            content = str(item.get("content", ""))
            status = str(item.get("status", "pending"))

            matched: _TodoProjection | None = None
            # Level 1: exact content match
            for i, o in enumerate(old):
                if i in used_old_idx:
                    continue
                if o.content == content:
                    matched = o
                    used_old_idx.add(i)
                    break
            # Level 2: positional alignment (content rewritten)
            if matched is None and pos < len(old) and pos not in used_old_idx:
                matched = old[pos]
                used_old_idx.add(pos)

            if matched is not None:
                proj = _TodoProjection(task_id=matched.task_id, content=content, status=status)
                new_projection.append(proj)
                status_events.extend(self._status_transition(matched.status, status, proj))
            else:
                # Level 3: brand new
                proj = _TodoProjection(
                    task_id=_stable_task_id(self.ctx.svid, content),
                    content=content,
                    status=status,
                )
                new_projection.append(proj)
                newly_generated.append(proj)
                status_events.extend(self._status_transition(None, status, proj))

        # Tasks that vanished from the new list are marked TERMINATED (not
        # deleted) — projection drop is enough at the mapper layer.
        self.ctx.todos = new_projection
        self._refresh_in_progress()

        events: list[BaseEvent] = []
        if newly_generated:
            events.append(
                GenerateSubTask(
                    task_id=self.ctx.svid,
                    subtask=[
                        {
                            "id": p.task_id,
                            "task_id": p.task_id,
                            "name": p.content,
                            "status": p.status,
                        }
                        for p in newly_generated
                    ],
                )
            )
        events.extend(status_events)
        return events

    def _status_transition(self, old_status: str | None, new_status: str, proj: _TodoProjection) -> list[BaseEvent]:
        """Map a todo status change to TaskStart / TaskEnd (design §3.3.1.5)."""
        if old_status == new_status:
            return []
        if new_status == "in_progress":
            return [TaskStart(task_id=proj.task_id, name=proj.content)]
        if new_status in ("completed", "done"):
            return [
                TaskEnd(
                    task_id=proj.task_id,
                    name=proj.content,
                    status="success",
                    answer="",
                    data={},
                )
            ]
        return []

    def _refresh_in_progress(self) -> None:
        self.ctx.current_in_progress_task_id = None
        for p in self.ctx.todos:
            if p.status == "in_progress":
                self.ctx.current_in_progress_task_id = p.task_id
                break

    # -- messages mode -----------------------------------------------------

    def _handle_messages(self, chunk: Any, ns: str | None) -> list[BaseEvent]:
        """``messages`` mode chunk is ``(message, metadata)``."""
        message = chunk[0] if isinstance(chunk, (list, tuple)) else chunk

        # Thinking stream: reasoning_content (DeepSeek-R1) or thinking blocks.
        thinking = self._extract_thinking(message)
        if thinking:
            return [self._build_thinking_step(thinking, ns)]

        # Tool-call start frames live on AIMessage.tool_calls.
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            return self._handle_tool_starts(tool_calls, ns)

        # Tool result -> end frame, keyed by tool_call_id.
        tool_call_id = getattr(message, "tool_call_id", None)
        if tool_call_id:
            return self._handle_tool_end(message, tool_call_id, ns)

        return []

    def _handle_tool_starts(self, tool_calls: list[dict[str, Any]], ns: str | None) -> list[BaseEvent]:
        events: list[BaseEvent] = []
        task_id = self.ctx.current_in_progress_task_id or self.ctx.svid
        for tc in tool_calls:
            call_id = tc.get("id") or tc.get("call_id")
            if not call_id:
                continue
            name = tc.get("name", "")
            args = tc.get("args")
            step_type = self._infer_step_type(name, ns)
            # call_reason is no longer model-injected — deepagents' native output
            # carries no per-step title, so we leave it empty and let the
            # frontend fall back to the tool display name (the tool ``name``).
            call_reason = ""

            open_call = _OpenCall(
                call_id=call_id,
                task_id=task_id,
                name=name,
                params=args,
                step_type=step_type,
                call_reason=call_reason,
                namespace=ns,
            )
            self.ctx.open_calls[call_id] = open_call

            extra_info = {"truncated": False}
            if ns:
                extra_info["namespace"] = ns

            events.append(
                ExecStep(
                    task_id=task_id,
                    call_id=call_id,
                    name=name,
                    call_reason=call_reason or "",
                    params=args,
                    output=None,
                    step_type=step_type,
                    status="start",
                    extra_info=extra_info,
                )
            )

            # An orphan end may already be buffered for this call_id (§3.7).
            buffered = self.ctx.orphan_ends.pop(call_id, None)
            if buffered is not None:
                events.append(self._build_end_step(open_call, buffered))
        return events

    def _handle_tool_end(self, message: Any, call_id: str, ns: str | None) -> list[BaseEvent]:
        output = self._message_text(message)
        payload = {"output": output}

        open_call = self.ctx.open_calls.pop(call_id, None)
        if open_call is None:
            # End arrived before start — buffer it (§3.7 reordering).
            self.ctx.orphan_ends[call_id] = payload
            return []
        return [self._build_end_step(open_call, payload)]

    def _build_end_step(self, open_call: _OpenCall, payload: dict[str, Any]) -> ExecStep:
        output, truncated = _truncate(payload.get("output"))
        extra_info: dict[str, Any] = {"truncated": truncated}
        if open_call.namespace:
            extra_info["namespace"] = open_call.namespace
        return ExecStep(
            task_id=open_call.task_id,
            call_id=open_call.call_id,
            name=open_call.name,
            call_reason=open_call.call_reason or "",
            params=open_call.params,
            output=output,
            step_type=open_call.step_type,
            status="end",
            extra_info=extra_info,
        )

    def _build_thinking_step(self, text: str, ns: str | None) -> ExecStep:
        output, truncated = _truncate(text)
        extra_info: dict[str, Any] = {"is_thinking": True, "truncated": truncated}
        if ns:
            extra_info["namespace"] = ns
        task_id = self.ctx.current_in_progress_task_id or self.ctx.svid
        # thinking has no tool call_id. ``messages`` mode streams it token-by-token,
        # so hashing the per-chunk delta would mint a new id every frame and the
        # frontend (merge-by-call_id) would render one row per token. Instead keep
        # a single id for the whole contiguous thinking stream; ``normalize`` resets
        # it once any non-thinking chunk closes the segment, so a thinking block that
        # resumes after a tool call still gets a fresh row.
        if self.ctx.current_thinking_call_id is None:
            self.ctx.thinking_seq += 1
            self.ctx.current_thinking_call_id = f"thinking:{task_id}:{self.ctx.thinking_seq}"
        call_id = self.ctx.current_thinking_call_id
        return ExecStep(
            task_id=task_id,
            call_id=call_id,
            name="thinking",
            call_reason="",
            params={},
            output=output,
            step_type="thinking",
            status="end",
            extra_info=extra_info,
        )

    # -- values mode -------------------------------------------------------

    def _handle_values(self, chunk: Any, ns: str | None) -> list[BaseEvent]:
        """Full state snapshot. Used as fallback/裁决 source by the executor's
        terminal收口; no incremental events are emitted from it here to avoid
        duplicate frames (§3.4). The snapshot is consumed by the executor for
        final_result assembly outside the mapper.
        """
        return []

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _namespace_str(namespace: tuple[str, ...] | None) -> str | None:
        if not namespace:
            return None
        # langgraph subgraph namespace is a tuple of "<node>:<idx>" segments.
        return "|".join(str(n) for n in namespace) if len(namespace) > 1 else str(namespace[0])

    def _infer_step_type(self, name: str, ns: str | None) -> str:
        # The deepagents `task` tool IS the delegation boundary — it spawns the
        # "general-purpose" researcher subagent. ONLY that call renders as a
        # subagent delegation row.
        #
        # Everything a subagent then runs *inside* its subgraph carries a namespace
        # (subgraphs=True), but those are ordinary tool/knowledge calls — NOT
        # delegations. Tagging each one step_type="subagent" made the UI render a
        # bogus "委派 1 个 ls/glob 子智能体" row per internal tool. Keep their real
        # type instead; the namespace still rides in extra_info so the frontend can
        # attribute them to their owning subagent.
        lowered = (name or "").lower()
        if lowered == "task":
            return "subagent"
        if any(hint in lowered for hint in _KNOWLEDGE_TOOL_HINTS):
            return "knowledge"
        return "tool"

    @staticmethod
    def _extract_thinking(message: Any) -> str | None:
        # DeepSeek-R1 style
        kwargs = getattr(message, "additional_kwargs", None)
        if isinstance(kwargs, dict) and kwargs.get("reasoning_content"):
            # Filter out a pseudo tool-call the model may have written into its
            # reasoning text (偶现) so it doesn't show as a raw blob in the thinking row.
            return _strip_pseudo_tool_call(str(kwargs["reasoning_content"]))
        # Anthropic thinking blocks in content list
        content = getattr(message, "content", None)
        if isinstance(content, list):
            chunks = [
                b.get("thinking") or b.get("text")
                for b in content
                if isinstance(b, dict) and b.get("type") == "thinking"
            ]
            chunks = [c for c in chunks if c]
            if chunks:
                return "".join(chunks)
        return None

    @staticmethod
    def _message_text(message: Any) -> str:
        content = getattr(message, "content", message)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    parts.append(block.get("text", ""))
                else:
                    parts.append(str(block))
            return "".join(parts)
        return str(content)
