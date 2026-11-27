"""F004 T028: executor of a ``direct`` run (design 决策 3, 7, 9, 10).

A ``direct`` run is daily chat on the unified kernel. It executes in a
background coroutine that does not depend on the HTTP request which started it:
the events go to the Redis Stream of the conversation, so a client that
reconnects to any node keeps reading (AC-33).

Entry points
------------

* ``start_direct_run(run_ctx)`` -- API process. Starts the coroutine with
  ``asyncio.create_task`` and keeps a reference to the task until it is done.
* ``execute_direct_run(run_ctx)`` -- the coroutine itself. The Linsight worker
  awaits it for a relay run. It takes a plain dict (or ``DirectRunContext``),
  restores the tenant context from ``tenant_id`` and never raises for a failure
  of the run: the failure becomes a ``run_failed`` event.

Pipeline of one execution
-------------------------

1. ``RunLeaseService.renew`` -- proves this run still holds the conversation
   (``run_dispatch.submit`` already wrote "running"; never ``acquire`` here).
2. ``run_started`` (new run) or ``ask_user_answered`` (resume).
3. The department concurrency slot (AC-22), held until this execution ends.
   Then quota admission, once (AC-37), while tools and the agent are built.
4. ``agent.astream`` -> ``UnifiedEventOutput`` -> ``EventWriter`` -> Stream.
   In parallel one watcher polls the stop flag every second (AC-29) and renews
   the lease every ``RENEW_INTERVAL_SECONDS``.
5. Exit:
   - finished / failed / stopped -> terminal event, then
     ``RunDispatchService.on_run_finished(conversation_id, run_id)``;
   - ``interrupt`` (ask_user) -> the ``ask_user`` event is already on the
     Stream, the lease is parked ("waiting", AC-22). ``on_run_finished`` is NOT
     called: the run is not over. The answer starts a second execution of the
     same run with ``is_resume=True``.
   - the lease is lost (a renew failed) -> ``_end_lost``. The event Stream is
     keyed by conversation, not by run, so the run may write its terminal event
     only while the conversation state still names it. ``RunLeaseService.reclaim``
     decides that in one script: when it succeeds nobody has reported the run,
     the run writes ``run_failed`` (reason ``lease_expired``; the hooks save the
     partial answer as a failed row) and finishes as usual. When it fails,
     another caller owns the conversation: that caller wrote ``run_failed`` and
     saved the text from the snapshot (``mark_run_expired``), and this run
     writes nothing more, not even its buffered text.

State: nothing about a run is kept in process memory (C8). ``_TASKS`` only
protects running coroutines from garbage collection.

Workspace (决策 10, T053)
------------------------

The file tools and the code interpreter of a run share ``workspace/{conversation_id}``
in object storage. The local directory ``file_dir_for(ctx)`` is a cache:

* nothing local exists until the first file operation. The code interpreter's
  first execution creates the directory and fetches ``output/``, ``uploads/``
  and ``large_tool_results/`` from object storage (the earlier execution may
  have run on another node);
* the directory is removed when the execution ends (finished, failed, stopped
  or parked), before the conversation is handed to the next run.

Selected skills are copied into the workspace before the tools are built; only
then does the prompt advertise them.

Output-side content safety
--------------------------

The main answer text goes through the scanner of the legacy daily chat. A hit
ends the run with ONE terminal event::

    {"type": "run_finished", "run_id": ..., "data": {"content_safety": true, "auto_reply": "<text>"}}

Before that event the conversation and the question row are marked as a
violation. The persistence projector stores ``auto_reply`` as the answer.

Event hooks (for the persistence projector)
-------------------------------------------

A hook is ``async def hook(event: dict) -> None`` (a plain function also
works). ``event`` is ``{"type", "data", "run_id"}`` exactly as it is handed to
the ``EventWriter``, before the 50 ms merge of ``text`` / ``thinking``. Hooks
are awaited one by one, in order, after the event was accepted by the writer.
The terminal event reaches the hooks BEFORE ``on_run_finished`` runs. A hook
that raises is logged and does not stop the run.

Before a terminal event is written, the owner of a hook (the object a bound
method hook belongs to) may add fields to its ``data`` through
``async before_terminal(event) -> dict | None``; see ``_add_terminal_fields``.

Pass hooks per run (``on_event=[...]``) or register a factory once with
``register_event_hook_factory(factory)``; ``factory(ctx)`` returns the hook of
one execution.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import shutil
import time
from collections.abc import Awaitable, Callable, Iterable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import asdict, dataclass, field, fields
from types import SimpleNamespace
from typing import Any

from loguru import logger

from bisheng.linsight.domain.schemas import run_events
from bisheng.linsight.domain.services import run_metrics
from bisheng.linsight.domain.services.run_event_stream import EventWriter, RunEventStream
from bisheng.linsight.domain.services.unattended_run import OPEN_API_CHANNEL
from bisheng.workstation.domain.services import direct_attachments, direct_run_turn
from bisheng.workstation.domain.services.custom_system_prompt import custom_system_prompt
from bisheng.workstation.domain.services.direct_attachments import AttachmentIntake, AttachmentView
from bisheng.workstation.domain.services.run_dispatch import EXPIRED_REASON, RunDispatchService
from bisheng.workstation.domain.services.run_lease import LEASE_SECONDS, RENEW_INTERVAL_SECONDS, RunLeaseService

PROFILE = "direct"
STOP_POLL_SECONDS = 1.0
STREAM_MODES = ["updates", "messages", "values"]

STATUS_FINISHED = "finished"
STATUS_FAILED = "failed"
STATUS_STOPPED = "stopped"
STATUS_WAITING = "waiting"
# A renew failed. Either another caller took the conversation (it emitted
# run_failed for this run; nothing more is written), or nobody did and the run
# ended itself with run_failed (``DirectRunOutcome.lease_reclaimed``).
STATUS_LEASE_LOST = "lease_lost"
# ``run_failed`` of a run that ended itself after its lease lapsed. Same code and
# reason as ``task_exec.mark_run_expired`` writes for a run somebody else found dead.
LEASE_LOST_ERROR_CODE = 11091
LEASE_LOST_DETAIL = "The run could not renew its lease in time and was ended."
# Internal result of ``_work``: the output scanner hit. The outcome of the run is
# ``finished`` with ``content_safety=True``.
_WORK_BLOCKED = "blocked"

EventHook = Callable[[dict], Awaitable[None] | None]
EventHookFactory = Callable[["DirectRunContext"], EventHook]


async def log_daily_chat_telemetry(ctx: DirectRunContext, started_at: float) -> None:
    """The application telemetry the legacy daily chat logged once per answered turn."""
    from bisheng.workstation.domain.services.chat_service import log_telemetry_events

    try:
        await log_telemetry_events(str(ctx.user_id), ctx.conversation_id, started_at)
    except Exception:
        # Telemetry never fails a run; the answer is already saved.
        logger.exception("direct run={}: could not log daily-chat telemetry", ctx.run_id)


@dataclass
class DirectRunContext:
    """Everything one execution needs, as plain JSON-serialisable values.

    ``to_dict()`` goes into a queue item; ``from_dict()`` also accepts the relay
    item built by ``RunDispatchService._relay_item`` (unknown keys are ignored).

    ``tools`` are the daily tool payloads (``{id, tool_key, type}``).
    ``knowledge`` is the resolved ``knowledge_bases_info`` list of daily chat.
    """

    conversation_id: str
    run_id: str
    tenant_id: int
    user_id: int
    message_id: str = ""
    text: str = ""
    model_id: str | None = None
    tools: list = field(default_factory=list)
    skills: list = field(default_factory=list)
    knowledge: list = field(default_factory=list)
    files: list = field(default_factory=list)
    # Relay run: its input is the unread inbox of the conversation.
    relay: bool = False
    # Second execution of a parked run: ``answer`` goes into ``Command(resume=...)``.
    is_resume: bool = False
    answer: Any = None
    # Events to append right after ``run_started`` (``SubmitResult.events``).
    initial_events: list = field(default_factory=list)
    # Relay run: the inbox messages the runner took as this run's input. None
    # until the runner has read the inbox; never part of a queue item.
    inbox_messages: list | None = None
    # Row id of the question this run answers; marked when the answer is blocked
    # by content safety. None for a relay run (its questions are steer rows).
    question_message_id: int | None = None
    # Page lease of the department concurrency limit (``X-BS-...`` header of the
    # send request). With it the run renews the page's slot and does not release it.
    page_lease_id: str | None = None
    # F132: the send request came through a login-state endpoint that registered
    # the conversation for long-term memory. False for a relay item (no request).
    memory_registered: bool = False
    # Open API (AC-39): nobody can answer a question, so the run gets no
    # ``ask_user`` tool and no inbox (``unattended_run``).
    unattended: bool = False
    # Object-storage partition of the caller's files (``SessionSubject.storage_partition``).
    # None = the user's own partition.
    storage_partition: str | None = None
    # Execution lease that the send request took before the run started (Open
    # API). The run renews it and releases it when it ends.
    execution_lease_id: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.tenant_id, bool) or self.tenant_id is None or int(self.tenant_id) <= 0:
            raise ValueError("a direct run needs a positive tenant_id")
        if not self.conversation_id or not self.run_id:
            raise ValueError("a direct run needs conversation_id and run_id")
        self.tenant_id = int(self.tenant_id)

    @property
    def thread_id(self) -> str:
        """决策 7: one LangGraph thread per conversation."""
        return self.conversation_id

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> DirectRunContext:
        names = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in names})


@dataclass
class DirectRunOutcome:
    status: str
    error: BaseException | None = None
    # The answer was replaced by the content-safety reply (status is "finished").
    content_safety: bool = False
    # status "lease_lost" only: the state still named this run, so it wrote its
    # own ``run_failed``. False = another caller owns the conversation.
    lease_reclaimed: bool = False


class _SafetyGate:
    """Feeds the main answer text to the output scanner and remembers a hit.

    ``scanner`` has the interface of ``StreamContentSafetyScanner`` (``feed`` /
    ``finish`` return a hit with ``auto_reply``, or None). None = scanning is off.
    """

    def __init__(self, scanner: Any = None):
        self.scanner = scanner
        self.hit: Any = None

    def seed(self, text: str) -> None:
        """Text the run wrote before it parked: part of the same answer."""
        if self.scanner is not None and self.hit is None and text:
            self.hit = self.scanner.feed(text)

    def observe(self, event: dict) -> None:
        if self.scanner is None or self.hit is not None or event.get("type") != run_events.TEXT:
            return
        data = event.get("data") or {}
        # Thinking, tool output and a subagent's text are never scanned (legacy rule).
        if data.get("namespace"):
            return
        self.hit = self.scanner.feed(str(data.get("text") or ""))

    def finish(self) -> Any:
        if self.scanner is not None and self.hit is None:
            self.hit = self.scanner.finish()
        return self.hit

    @property
    def auto_reply(self) -> str:
        return str(getattr(self.hit, "auto_reply", None) or "")


# T037 (AC-51): the "reading attachments" progress frames are one ``tool_call``.
# T057 (决策 12): the frame opens when the run starts and closes when every
# attachment is in the workspace; the model request does not wait for it.
ATTACHMENT_TOOL_NAME = "read_attachments"


def attachments_to_read(ctx: DirectRunContext) -> list:
    """Attachments a new execution brings in; a resume already did in its first execution."""
    if ctx.is_resume:
        return []
    return [f for f in ctx.files or [] if isinstance(f, dict) and f.get("filepath")]


def _with_attachments(graph_input: Any, reading: AttachmentView | None) -> Any:
    """Add the attachment index, the inlined small files and the images to the first user message."""
    if reading is None or not (reading.listing or reading.file_context or reading.images):
        return graph_input
    messages = list(graph_input.get("messages") or []) if isinstance(graph_input, dict) else []
    if not messages or not isinstance(messages[0], dict):
        logger.warning("direct run: graph input has no first user message; attachments not inlined")
        return graph_input
    first = dict(messages[0])
    text = str(first.get("content") or "")
    if reading.listing:
        text = f"{text}\n\n{reading.listing}"
    if reading.file_context:
        text = f"{text}\n\n<uploaded_file_content>\n{reading.file_context}\n</uploaded_file_content>"
    if reading.images:
        first["content"] = [
            {"type": "text", "text": text},
            *({"type": "image_url", "image_url": {"url": url}} for url in reading.images),
        ]
    else:
        first["content"] = text
    messages[0] = first
    return {**graph_input, "messages": messages}


class _RunExtras:
    """Per-execution data the sink adds to events (never kept on the runner: C8).

    ``tool_meta``  tool name -> ``{"display_name", "tool_type"}`` (``_build_tool_meta``),
                   filled when the tools are assembled. It goes into ``extra_info``
                   of the main-graph ``tool_call`` events, so every reader of the
                   stream (projector, legacy frames, a worker) shows the same name.
    ``backend``    the workspace backend of the execution (file events, T055).
    """

    def __init__(self, mapper: Any):
        self.mapper = mapper
        self.tool_meta: dict[str, dict[str, Any]] = {}
        self.backend: Any = None

    def dress(self, event: dict) -> dict:
        """Add the tool display data to ``event`` in place; return the event for the hooks.

        The returned event is ``event`` itself, or a copy that carries the complete
        tool output when the stream's copy was truncated.
        """
        if event.get("type") != run_events.TOOL_CALL:
            return event
        data = event.get("data")
        if not isinstance(data, dict):
            return event
        extra_info = data.get("extra_info") or {}
        if extra_info.get("namespace"):
            return event
        meta = self.tool_meta.get(str(data.get("name") or ""))
        if meta:
            extra_info = {**meta, **extra_info}
            data["extra_info"] = extra_info
        if data.get("status") != "end" or not extra_info.get("truncated"):
            return event
        full = (getattr(self.mapper, "full_outputs", None) or {}).pop(str(data.get("call_id") or ""), None)
        if full is None:
            return event
        return {**event, "data": {**data, "output": full}}


_HOOK_FACTORIES: list[EventHookFactory] = []
_DEFAULT_ENQUEUE_RELAY: Callable[[dict], Awaitable[None]] | None = None
# Strong references to running coroutines (asyncio keeps only weak ones).
_TASKS: set[asyncio.Task] = set()


# ``reason`` of a failure the classifier could not name, as the legacy daily chat
# sends it (``chat_service``): the client then shows "the reply failed", not the
# deep-research "the task failed".
CHAT_UNKNOWN_REASON = "chat_unknown"


def _as_chat_failure(event: dict) -> None:
    """Give an unclassified ``run_failed`` of a direct run the daily-chat reason."""
    data = event.get("data")
    if event.get("type") == run_events.RUN_FAILED and isinstance(data, dict) and data.get("reason") == "unknown":
        data["reason"] = CHAT_UNKNOWN_REASON


async def _add_terminal_fields(ctx: DirectRunContext, event: dict, hooks: list) -> None:
    """Let the hooks' owners add fields to a terminal event before it is written.

    A hook that is a bound method of an object with ``async before_terminal(event)``
    (the persistence projector) may return a dict; it is merged into ``data``
    without replacing a field the event already has. Today that is
    ``answer_files``: the files of the answer row, with the row's ids. A failure
    is logged and the event is written without the fields; the client then takes
    the files from the history.
    """
    for hook in hooks:
        prepare = getattr(getattr(hook, "__self__", None), "before_terminal", None)
        if prepare is None:
            continue
        try:
            extra = await prepare(event)
        except Exception:
            logger.exception(
                "direct run={} conversation={}: could not prepare the {} event",
                ctx.run_id,
                ctx.conversation_id,
                event.get("type"),
            )
            continue
        if not extra:
            continue
        data = event.get("data")
        if not isinstance(data, dict):
            data = {}
            event["data"] = data
        for key, value in extra.items():
            data.setdefault(key, value)


def register_event_hook_factory(factory: EventHookFactory) -> None:
    """Attach a hook to every direct run of this process (idempotent)."""
    if factory not in _HOOK_FACTORIES:
        _HOOK_FACTORIES.append(factory)


def set_default_enqueue_relay(enqueue: Callable[[dict], Awaitable[None]] | None) -> None:
    """How a finished run hands a relay run to the worker queue (wired at startup)."""
    global _DEFAULT_ENQUEUE_RELAY
    _DEFAULT_ENQUEUE_RELAY = enqueue


def production_dispatch_wiring(enqueue_relay: Callable[[dict], Awaitable[None]] | None = None) -> dict[str, Any]:
    """Keyword arguments that give ``RunDispatchService`` its production wiring.

    Relay runs go to the Linsight worker queue, an expired planned run is marked
    failed, and the queue position comes from the worker queue. Every process
    that submits or finishes runs (API and worker) needs the same wiring, so it
    does not depend on a startup hook having run. Imported lazily: linsight
    imports this package.
    """
    from bisheng.linsight.domain.task_exec import mark_run_expired
    from bisheng.linsight.worker import enqueue_relay_run, enqueue_waiting_item, planned_queue_position

    return {
        "enqueue_relay": enqueue_relay or _DEFAULT_ENQUEUE_RELAY or enqueue_relay_run,
        "on_run_expired": mark_run_expired,
        "queue_position": planned_queue_position,
        # A run that waited for the conversation goes back to the worker queue.
        "enqueue_item": enqueue_waiting_item,
    }


def _coerce(run_ctx: DirectRunContext | dict) -> DirectRunContext:
    return run_ctx if isinstance(run_ctx, DirectRunContext) else DirectRunContext.from_dict(run_ctx)


def _unpack(chunk: Any) -> tuple[str, Any, Any]:
    """``(namespace, mode, data)`` with subgraphs, ``(mode, data)`` without."""
    if isinstance(chunk, tuple) and len(chunk) == 3:
        return chunk[1], chunk[2], chunk[0]
    if isinstance(chunk, tuple) and len(chunk) == 2:
        return chunk[0], chunk[1], None
    return "values", chunk, None


class DirectRunner:
    """Runs ``direct`` executions. Every collaborator can be injected.

    ``redis``            redis-py asyncio client; default ``get_redis_client()``.
    ``clock``            epoch seconds; must be the clock of lease and dispatch.
    ``sleep``            used by the stop / renew watcher.
    ``stream`` / ``lease`` / ``dispatch``  prebuilt services (else built on ``redis``).
    ``checkpointer``     LangGraph checkpointer; default ``make_checkpointer()``.
    ``admit(ctx)``       quota admission; raises to reject the run.
    ``assemble(ctx, file_dir)``  returns a ``ToolAssembly``.
    ``build_agent(ctx, tools, checkpointer, file_dir)``  returns the graph. When it
                         also declares an ``inbox`` parameter it receives the
                         ``InboxMiddleware`` of the run (T041).
    ``build_input(ctx)`` returns the graph input of a new run.
    ``object_store()``   async, returns the MinIO client of the workspace.
    ``file_dir_for(ctx)``  local cache directory of the workspace.
    ``recursion_limit``  LangGraph recursion limit; default from the Linsight settings.
    ``attachment_source(ctx)``  the attachment source of the run (parse state and
                         workspace copy; see ``direct_attachments``).
    ``build_backend(ctx, file_dir, sink)``  returns the ``WorkspaceBackend`` of the run.
                         ``sink`` writes an event of this run (for a file-event callback).
    ``provision_skills(ctx, backend)``  copies the selected skills into the workspace;
                         returns a ``SkillProvisionResult``. Called only when ``ctx.skills``.
    ``sync_workspace(ctx, backend, file_dir)``  fetches the workspace files the code
                         interpreter needs into ``file_dir`` (first code execution only).
    ``department_slot(ctx)``  async context manager held while the run executes;
                         raises to refuse the run.
    ``safety_scanner(ctx)``  output scanner of the run, or None when scanning is off.
    ``mark_violation(ctx)``  marks the conversation and the question row after a hit.
    ``custom_prompt()``  the administrator's custom system prompt (or the built-in default).
    ``log_telemetry(ctx, started_at)``  application telemetry of a finished or failed run.

    ``build_agent`` also receives ``backend=`` and ``skills_present=`` when it
    declares those parameters.
    """

    def __init__(
        self,
        *,
        redis: Any = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        stream: RunEventStream | None = None,
        lease: RunLeaseService | None = None,
        dispatch: RunDispatchService | None = None,
        checkpointer: Any = None,
        admit: Callable[[DirectRunContext], Awaitable[None]] | None = None,
        assemble: Callable[[DirectRunContext, str], Awaitable[Any]] | None = None,
        build_agent: Callable[..., Awaitable[Any]] | None = None,
        build_input: Callable[[DirectRunContext], Awaitable[Any]] | None = None,
        object_store: Callable[[], Awaitable[Any]] | None = None,
        file_dir_for: Callable[[DirectRunContext], str] | None = None,
        enqueue_relay: Callable[[dict], Awaitable[None]] | None = None,
        attachment_source: Callable[[DirectRunContext], Any] | None = None,
        build_backend: Callable[..., Awaitable[Any]] | None = None,
        provision_skills: Callable[[DirectRunContext, Any], Awaitable[Any]] | None = None,
        sync_workspace: Callable[[DirectRunContext, Any, str], Awaitable[None]] | None = None,
        department_slot: Callable[[DirectRunContext], AbstractAsyncContextManager] | None = None,
        safety_scanner: Callable[[DirectRunContext], Any] | None = None,
        mark_violation: Callable[[DirectRunContext], Awaitable[None]] | None = None,
        custom_prompt: Callable[[], Awaitable[str | None]] | None = None,
        log_telemetry: Callable[[DirectRunContext, float], Awaitable[None]] | None = None,
        stop_poll_seconds: float = STOP_POLL_SECONDS,
        recursion_limit: int | None = None,
    ):
        self._redis = redis
        self._clock = clock
        self._sleep = sleep
        self.stream = stream
        self.lease = lease
        self.dispatch = dispatch
        self._checkpointer = checkpointer
        self._admit = admit or self._default_admit
        self._assemble = assemble or self._default_assemble
        self._build_agent = build_agent or self._default_build_agent
        self._build_input = build_input or self._default_build_input
        self._object_store = object_store or self._default_object_store
        self._file_dir_for = file_dir_for or self._default_file_dir
        self._enqueue_relay = enqueue_relay
        self._attachment_source = attachment_source or self._default_attachment_source
        self._build_backend = build_backend or self._default_build_backend
        self._provision_skills = provision_skills or self._default_provision_skills
        self._sync_workspace = sync_workspace or self._default_sync_workspace
        self._department_slot = department_slot or self._default_department_slot
        self._safety_scanner = safety_scanner or self._default_safety_scanner
        self._mark_violation = mark_violation or self._default_mark_violation
        self._custom_prompt = custom_prompt or custom_system_prompt
        self._log_telemetry = log_telemetry or log_daily_chat_telemetry
        self._stop_poll_seconds = stop_poll_seconds
        self._recursion_limit_override = recursion_limit

    # ------------------------------------------------------------- services

    async def _ensure_services(self) -> None:
        if self._redis is None and None in (self.stream, self.lease, self.dispatch):
            from bisheng.core.cache.redis_manager import get_redis_client

            self._redis = (await get_redis_client()).async_connection
        if self.stream is None:
            self.stream = RunEventStream(self._redis, wall_clock=self._clock)
        if self.lease is None:
            self.lease = RunLeaseService(self._redis, clock=self._clock)
        if self.dispatch is None:
            self.dispatch = RunDispatchService(
                self._redis, clock=self._clock, **production_dispatch_wiring(self._enqueue_relay)
            )

    def _get_checkpointer(self) -> Any:
        if self._checkpointer is None:
            from bisheng.linsight.domain.services.checkpointer import make_checkpointer

            self._checkpointer = make_checkpointer()
        return self._checkpointer

    # ------------------------------------------------------------------ run

    async def run(self, run_ctx: DirectRunContext | dict, on_event: Iterable[EventHook] = ()) -> DirectRunOutcome:
        """Execute once. The tenant context must already be set (``execute_direct_run`` does it)."""
        from bisheng.linsight.domain.services.stream_event_mapper import StreamEventMapper, UnifiedEventOutput

        ctx = _coerce(run_ctx)
        await self._ensure_services()
        hooks = [*on_event, *(factory(ctx) for factory in _HOOK_FACTORIES)]
        writer = EventWriter(self.stream, ctx.conversation_id, ctx.run_id)
        gate = _SafetyGate(self._safety_scanner(ctx))
        # T059: citations and memory of this execution (see ``direct_run_turn``).
        turn = direct_run_turn.open_turn(ctx.conversation_id, ctx.run_id)
        # The citation audit line names the model (design §7 item 17).
        turn.model = ctx.model_id

        mapper = StreamEventMapper(svid=ctx.run_id)
        # The stream carries tool output cut at 8000 characters; the hooks (the
        # answer row) get the complete output, as the legacy daily chat stores it.
        mapper.full_outputs = {}
        extras = _RunExtras(mapper)

        async def sink(raw_event: dict) -> None:
            # ``[Sn]`` in the answer becomes the citation marker before the text is
            # written, and memory tool events lose their content (T059).
            for event in turn.rewrite(raw_event):
                await write(event)

        async def write(event: dict) -> None:
            if event.get("type") in run_events.TERMINAL_EVENT_TYPES:
                _as_chat_failure(event)
                await _add_terminal_fields(ctx, event, hooks)
            for_hooks = extras.dress(event)
            await writer.emit(event)
            # Like the legacy stream: the text is sent, then scanned. ``_work``
            # reads ``gate.hit`` after each chunk.
            gate.observe(event)
            for hook in hooks:
                try:
                    result = hook(for_hooks)
                    if inspect.isawaitable(result):
                        await result
                except Exception:
                    logger.exception(
                        "direct run={} conversation={}: event hook failed on a {} event",
                        ctx.run_id,
                        ctx.conversation_id,
                        event.get("type"),
                    )

        # ``_prepare`` and ``_execute`` reach the per-execution extras through the sink.
        sink.extras = extras  # type: ignore[attr-defined]
        output = UnifiedEventOutput(mapper, sink, run_id=ctx.run_id)
        started = self._clock()
        # T038: read before ``_execute`` renews the lease (the renew rewrites the time).
        metrics = run_metrics.RunMetrics(PROFILE, clock=self._clock, resume=ctx.is_resume, started_at=started)
        metrics.submitted_at = await run_metrics.read_submitted_at(
            self._redis_of_lease(), ctx.conversation_id, ctx.run_id
        )
        metrics_token = run_metrics.activate(metrics)
        outcome: DirectRunOutcome | None = None
        started_wall = time.time()
        try:
            outcome = await self._execute(ctx, output, sink, gate)
        except asyncio.CancelledError:
            # The process is going down. The lease lapses on its own and the next
            # access to the conversation reports the run as failed (决策 3).
            logger.warning("direct run={} conversation={} was cancelled", ctx.run_id, ctx.conversation_id)
            raise
        except Exception as exc:
            logger.exception("direct run={} conversation={} failed", ctx.run_id, ctx.conversation_id)
            outcome = DirectRunOutcome(STATUS_FAILED, exc)
            try:
                await output.run_failed(exc)
            except Exception:
                logger.exception("direct run={}: could not write run_failed", ctx.run_id)
            # ``_execute`` did not reach its own cleanup.
            await self._cleanup_local(ctx)
        finally:
            if outcome is not None and outcome.status == STATUS_LEASE_LOST and not outcome.lease_reclaimed:
                # The Stream belongs to another run now: the buffered text is not written.
                writer.discard()
            try:
                await asyncio.shield(writer.aclose())
            except Exception:
                logger.exception("direct run={}: could not flush the event writer", ctx.run_id)
            run_metrics.deactivate(metrics_token)
            # The terminal event has reached the hooks; nothing reads the turn after this.
            direct_run_turn.close_turn(ctx.run_id, turn)

        logger.info(
            "direct run={} conversation={} ended status={} resume={} relay={} seconds={:.2f}",
            ctx.run_id,
            ctx.conversation_id,
            outcome.status,
            ctx.is_resume,
            ctx.relay,
            self._clock() - started,
        )
        if outcome.status != STATUS_WAITING:
            try:
                await self.dispatch.on_run_finished(ctx.conversation_id, ctx.run_id)
            except Exception:
                # The inbox is kept and the conversation is freed; the next message
                # starts the relay run (run_dispatch contract).
                logger.exception(
                    "direct run={} conversation={}: on_run_finished failed", ctx.run_id, ctx.conversation_id
                )
        if outcome.status in (STATUS_FINISHED, STATUS_FAILED):
            await self._log_telemetry(ctx, started_wall)
        # After the conversation was handed on: measuring the checkpoint delays nobody.
        checkpoint_bytes = await run_metrics.checkpoint_size(self._get_checkpointer(), ctx.thread_id)
        run_metrics.emit_run_metric(metrics, outcome.status, checkpoint_bytes)
        return outcome

    def _redis_of_lease(self) -> Any:
        """The Redis client that holds the conversation state."""
        return getattr(self.lease, "_redis", None) or self._redis

    async def _execute(
        self,
        ctx: DirectRunContext,
        output: Any,
        sink: Callable[[dict], Awaitable[None]],
        gate: _SafetyGate | None = None,
    ) -> Any:
        cid, run_id = ctx.conversation_id, ctx.run_id
        gate = gate or _SafetyGate()
        if not await self.lease.renew(cid, run_id):
            logger.warning("direct run={} does not hold conversation={}; not executed", run_id, cid)
            return await self._end_lost(ctx, sink)

        work = asyncio.create_task(self._work(ctx, output, sink, gate))
        watch = asyncio.create_task(self._watch(ctx))
        try:
            await asyncio.wait({work, watch}, return_when=asyncio.FIRST_COMPLETED)
            # The local cache is removed in every branch below BEFORE the
            # conversation can pass to another execution (park here, or
            # ``on_run_finished`` in ``run``): the next one may use the same
            # directory on this node.
            if work.done():
                # T055: every file of this execution is announced before the
                # terminal event (the projector reads the ``file`` events) and
                # before the local cache is removed.
                await self._settle_files(ctx, sink)
                error = work.exception()
                if error is not None:
                    # The traceback belongs to the task; log it here, where it is handled.
                    logger.opt(exception=error).error("direct run={} conversation={} failed", run_id, cid)
                    await output.run_failed(error)
                    await self._cleanup_local(ctx)
                    return DirectRunOutcome(STATUS_FAILED, error)
                if work.result() == STATUS_WAITING:
                    if await self._stop_pending(ctx):
                        # The stop arrived after the question was asked and before
                        # the run parked. Parking now would leave the flag behind,
                        # and the resumed run (same run_id) would stop on the answer.
                        return await self._end_stopped(ctx, output, sink)
                    await self._cleanup_local(ctx)
                    return await self._park(ctx)
                if not await self._still_holds(ctx):
                    # Another caller declared this run dead and saved its partial
                    # answer: write nothing more (design §5 #24).
                    logger.warning("direct run={} finished after losing conversation={}; nothing written", run_id, cid)
                    return DirectRunOutcome(STATUS_LEASE_LOST)
                if work.result() == _WORK_BLOCKED:
                    await self._finish_blocked(ctx, output, gate)
                    await self._cleanup_local(ctx)
                    return DirectRunOutcome(STATUS_FINISHED, content_safety=True)
                await output.run_finished()
                await self._cleanup_local(ctx)
                return DirectRunOutcome(STATUS_FINISHED)

            reason = watch.result()
            work.cancel()
            await asyncio.gather(work, return_exceptions=True)
            if reason == STATUS_STOPPED:
                return await self._end_stopped(ctx, output, sink)
            return await self._end_lost(ctx, sink)
        finally:
            for task in (work, watch):
                if not task.done():
                    task.cancel()
            await asyncio.gather(work, watch, return_exceptions=True)

    async def _end_stopped(self, ctx: DirectRunContext, output: Any, sink: Callable[[dict], Awaitable[None]]) -> Any:
        await self._settle_files(ctx, sink)
        # Text already written stays in the accumulated state (AC-29).
        # Messages the run never read go back to the client inside the
        # event; ``on_run_finished`` then finds an empty inbox and starts
        # no relay run (design §7 item 6).
        await output.run_stopped("user", await self._discard_unread(ctx))
        await self._cleanup_local(ctx)
        return DirectRunOutcome(STATUS_STOPPED)

    async def _still_holds(self, ctx: DirectRunContext) -> bool:
        """The run may write its own terminal event: it still holds the conversation.

        ``renew`` proves it; when the lease lapsed unnoticed, ``reclaim`` takes it
        back unless another caller already reported the run. A Redis error counts
        as "still holds": the watcher renewed the lease within the last
        RENEW_INTERVAL_SECONDS, and one failed call must not fail a finished answer.
        """
        cid, run_id = ctx.conversation_id, ctx.run_id
        try:
            return await self.lease.renew(cid, run_id) or await self.lease.reclaim(cid, run_id)
        except Exception:
            logger.exception(
                "direct run={} conversation={}: could not confirm the lease; writing the ending", run_id, cid
            )
            return True

    async def _stop_pending(self, ctx: DirectRunContext) -> bool:
        """A stop requested before the run parks. A Redis error counts as "no stop" (the run parks)."""
        try:
            return await self.lease.should_stop(ctx.run_id)
        except Exception:
            logger.exception("direct run={}: could not read the stop flag before parking", ctx.run_id)
            return False

    async def _end_lost(self, ctx: DirectRunContext, sink: Callable[[dict], Awaitable[None]]) -> DirectRunOutcome:
        """End a run whose renew failed (see "the lease is lost" in the module docstring).

        The run writes ``run_failed`` only after ``reclaim`` proved that the
        conversation state still names it. Otherwise nothing is written and the
        local cache is left alone: another execution of this conversation may
        already use the Stream and the directory.
        """
        cid, run_id = ctx.conversation_id, ctx.run_id
        if not await self.lease.reclaim(cid, run_id):
            logger.warning(
                "direct run={} lost conversation={} to another caller; it writes no terminal event", run_id, cid
            )
            return DirectRunOutcome(STATUS_LEASE_LOST)
        logger.warning(
            "direct run={} conversation={}: the lease lapsed and nobody took the conversation; ending the run",
            run_id,
            cid,
        )
        snapshot = await self.stream.snapshot(cid)
        if not ctx.is_resume and (snapshot is None or snapshot.get("run_id") != run_id):
            # The run wrote nothing yet and the Stream still holds an earlier run:
            # ``run_started`` clears it, as for every new run.
            await sink(
                run_events.make_event(
                    run_events.RUN_STARTED,
                    {"profile": PROFILE, "message_id": ctx.message_id, "relay": ctx.relay},
                    run_id=run_id,
                )
            )
        await self._settle_files(ctx, sink)
        await sink(
            run_events.make_event(
                run_events.RUN_FAILED,
                run_events.RunFailedData(
                    code=LEASE_LOST_ERROR_CODE, reason=EXPIRED_REASON, detail=LEASE_LOST_DETAIL, reference_id=run_id
                ),
                run_id=run_id,
            )
        )
        await self._cleanup_local(ctx)
        return DirectRunOutcome(STATUS_LEASE_LOST, lease_reclaimed=True)

    async def _discard_unread(self, ctx: DirectRunContext) -> list[dict]:
        """The unread inbox of a run the user stopped, removed from the inbox.

        When the removal fails the stop still completes: the error is logged, the
        event carries no messages, and the messages that stayed in the inbox are
        answered by a relay run instead of being lost.
        """
        from bisheng.workstation.domain.services import run_message_persist

        try:
            return await run_message_persist.discard_unread(
                self.dispatch, ctx.conversation_id, redis=self._redis_of_lease()
            )
        except Exception:
            logger.exception(
                "direct run={} conversation={}: could not take back the unread messages on stop",
                ctx.run_id,
                ctx.conversation_id,
            )
            return []

    async def _finish_blocked(self, ctx: DirectRunContext, output: Any, gate: _SafetyGate) -> None:
        """End a run whose answer hit the output scanner (legacy ``persist_safety_replacement``)."""
        logger.warning(
            "workbench content safety hit tenant_id={} mode=output chat_id={} run={}",
            ctx.tenant_id,
            ctx.conversation_id,
            ctx.run_id,
        )
        try:
            await self._mark_violation(ctx)
        except Exception:
            # The replacement must still reach the user and the answer row.
            logger.exception(
                "direct run={} conversation={}: could not mark the content-safety violation",
                ctx.run_id,
                ctx.conversation_id,
            )
        await output.run_finished({"content_safety": True, "auto_reply": gate.auto_reply})

    async def _settle_files(self, ctx: DirectRunContext, sink: Any) -> None:
        """T055: write the pending ``file`` events, then announce what nobody reported.

        The reconcile lists ``output/`` in object storage (the local cache may be
        on another node, C8) and runs only when this execution ran code: the file
        tools report every write themselves. Never raises.
        """
        from bisheng.linsight.domain.services.file_events import FileEventRelay

        backend = getattr(getattr(sink, "extras", None), "backend", None)
        relay = getattr(backend, "on_output_file", None)
        if not isinstance(relay, FileEventRelay):
            return
        try:
            if relay.baseline is None:
                await relay.drain()
                return
            await relay.reconcile(await asyncio.to_thread(backend.output_listing))
        except Exception:
            logger.exception(
                "direct run={} conversation={}: could not reconcile the generated files",
                ctx.run_id,
                ctx.conversation_id,
            )

    async def _file_baseline(self, ctx: DirectRunContext, backend: Any) -> None:
        """T055: remember ``output/`` as it is before the first code execution of this run."""
        from bisheng.linsight.domain.services.file_events import FileEventRelay

        relay = getattr(backend, "on_output_file", None)
        if not isinstance(relay, FileEventRelay) or relay.baseline is not None:
            return
        try:
            relay.take_baseline(await asyncio.to_thread(backend.output_listing))
        except Exception:
            # Without a baseline the files of earlier runs cannot be told from new
            # ones, so this execution is not reconciled; the executor's own
            # notices still arrive.
            logger.exception(
                "direct run={} conversation={}: could not list output/ before code execution",
                ctx.run_id,
                ctx.conversation_id,
            )

    @staticmethod
    def _attach_run_extras(sink: Any, backend: Any, tools: list) -> None:
        """T055: tool display data for the events, and the executor's file notices."""
        from bisheng.linsight.domain.services.file_events import FileEventRelay
        from bisheng.workstation.domain.services.chat_service import _build_tool_meta

        extras = getattr(sink, "extras", None)
        if extras is not None:
            extras.backend = backend
            extras.tool_meta = {tool.name: _build_tool_meta(tool) for tool in tools if getattr(tool, "name", None)}
        relay = getattr(backend, "on_output_file", None)
        if not isinstance(relay, FileEventRelay):
            return
        for tool in tools:
            executor = getattr(tool, "executor", None)
            if executor is not None and getattr(executor, "workspace_prefix", None):
                # ``sync_to_workspace`` calls it for every file it mirrored.
                executor.on_workspace_file = relay.synced

    async def _cleanup_local(self, ctx: DirectRunContext) -> None:
        """Remove the local cache of the workspace; object storage keeps the files (C8).

        Same two steps as ``LinsightWorkflowTask._cleanup_resources``. Never raises:
        a leftover directory costs disk space, not correctness.
        """
        file_dir = self._file_dir_for(ctx)
        if not file_dir:
            return
        try:
            # Shielded: a cancel during cleanup must not abandon a half-done release
            # (it ends the run's leftover processes and frees the uid).
            await asyncio.shield(asyncio.to_thread(self._remove_local_dir, file_dir))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "direct run={} conversation={}: local cache cleanup failed", ctx.run_id, ctx.conversation_id
            )

    @staticmethod
    def _remove_local_dir(file_dir: str) -> None:
        from bisheng_langchain.gpts.tools.code_interpreter.local_run_registry import release_local_run

        try:
            # No-op when no code interpreter registered a retained run for the directory.
            release_local_run(file_dir)
        finally:
            if os.path.exists(file_dir):
                shutil.rmtree(file_dir, ignore_errors=True)

    async def _park(self, ctx: DirectRunContext) -> DirectRunOutcome:
        if not await self.lease.park(ctx.conversation_id, ctx.run_id):
            logger.warning(
                "direct run={} asked the user but no longer holds conversation={}", ctx.run_id, ctx.conversation_id
            )
            return DirectRunOutcome(STATUS_LEASE_LOST)
        logger.info("direct run={} conversation={} waits for the user's answer", ctx.run_id, ctx.conversation_id)
        return DirectRunOutcome(STATUS_WAITING)

    async def _watch(self, ctx: DirectRunContext) -> str:
        """Poll the stop flag every second, renew the lease every 10 s.

        One failed poll (a Redis hiccup) does not end the run, as in the planned
        tier. When no renewal succeeded for a whole lease, the lease has lapsed
        and the run ends as lost.
        """
        next_renew = self._clock() + RENEW_INTERVAL_SECONDS
        last_renewed = self._clock()
        while True:
            await self._sleep(self._stop_poll_seconds)
            try:
                if await self.lease.should_stop(ctx.run_id):
                    logger.info("direct run={} conversation={}: stop requested", ctx.run_id, ctx.conversation_id)
                    return STATUS_STOPPED
                if self._clock() >= next_renew:
                    if not await self.lease.renew(ctx.conversation_id, ctx.run_id):
                        logger.warning(
                            "direct run={} lost the lease of conversation={}", ctx.run_id, ctx.conversation_id
                        )
                        return STATUS_LEASE_LOST
                    last_renewed = self._clock()
                    next_renew = last_renewed + RENEW_INTERVAL_SECONDS
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "direct run={} conversation={}: stop/lease poll failed", ctx.run_id, ctx.conversation_id
                )
                if self._clock() - last_renewed >= LEASE_SECONDS:
                    return STATUS_LEASE_LOST

    async def _work(
        self,
        ctx: DirectRunContext,
        output: Any,
        sink: Callable[[dict], Awaitable[None]],
        gate: _SafetyGate | None = None,
    ) -> str:
        gate = gate or _SafetyGate()
        if ctx.is_resume:
            snapshot = await self.stream.snapshot(ctx.conversation_id) or {}
            # A new mapper starts empty: give it the plan the run had when it parked.
            output.seed_plan(snapshot.get("plan") or [])
            # The scanner checks the whole answer, including what was written before the park.
            gate.seed(str(snapshot.get("text") or ""))
            pending = snapshot.get("pending_question") or {}
            await output.ask_user_answered(call_id=pending.get("call_id"), answer=ctx.answer)
        else:
            await output.run_started({"profile": PROFILE, "message_id": ctx.message_id, "relay": ctx.relay})
            for event in ctx.initial_events:
                await sink({**event, "run_id": ctx.run_id})

        # AC-22: the department slot is held from here until this coroutine ends
        # (finished, failed, cancelled by a stop, or parked for an answer). A
        # refusal raises before anything is parsed or any model is called.
        async with self._department_slot(ctx):
            return await self._work_admitted(ctx, output, sink, gate)

    async def _work_admitted(
        self, ctx: DirectRunContext, output: Any, sink: Callable[[dict], Awaitable[None]], gate: _SafetyGate
    ) -> str:
        # T057 (决策 12, AC-51): the "reading attachments" frame opens before
        # anything is parsed and the files start coming into the workspace. The
        # model request does not wait for parsing; a read of ``uploads/`` does.
        files = attachments_to_read(ctx)
        if not files:
            return await self._work_graph(ctx, output, sink, gate, None)
        intake = self._open_intake(ctx, files, sink)
        try:
            await intake.start()
            return await self._work_graph(ctx, output, sink, gate, intake)
        finally:
            # Closes the frame before the terminal event. Parsing that is still
            # running continues once the graph has started (later runs read the
            # file, AC-26) and is cancelled when the run never got that far.
            await intake.close()

    def _open_intake(
        self, ctx: DirectRunContext, files: list, sink: Callable[[dict], Awaitable[None]]
    ) -> AttachmentIntake:
        from bisheng.linsight.domain.services.tool_assembly import CODE_INTERPRETER_TOOL_KEY

        async def emit_frame(status: str, extra: dict) -> None:
            await sink(self._attachment_event(ctx, files, status, extra=extra))

        return AttachmentIntake(
            ctx,
            files,
            self._attachment_source(ctx),
            emit_frame,
            has_code_interpreter=any(
                isinstance(p, dict) and p.get("tool_key") == CODE_INTERPRETER_TOOL_KEY for p in ctx.tools
            ),
        )

    async def _work_graph(
        self,
        ctx: DirectRunContext,
        output: Any,
        sink: Callable[[dict], Awaitable[None]],
        gate: _SafetyGate,
        intake: AttachmentIntake | None,
    ) -> str:
        from bisheng_langchain.linsight.event import NeedUserInput

        # The agent is built while the quota is checked. Admission is awaited in
        # THIS task: it marks the context so the run's model calls skip the
        # per-call quota comparison (dsh ``admit_round``).
        prepare = asyncio.create_task(self._prepare(ctx, sink, intake))
        try:
            await self._admit(ctx)
            agent = await prepare
            # Waits for copies and images only, never for a parse.
            reading = await intake.first_view() if intake is not None else None
        finally:
            if not prepare.done():
                prepare.cancel()
                await asyncio.gather(prepare, return_exceptions=True)
        if intake is not None:
            intake.keep_after_run = True

        if ctx.is_resume:
            from langgraph.types import Command

            graph_input: Any = Command(resume=ctx.answer)
        else:
            if ctx.relay:
                await self._read_relay_inbox(ctx, sink)
            graph_input = _with_attachments(await self._build_input(ctx), reading)
        config = run_metrics.with_metric_callback(
            {
                "configurable": {"thread_id": ctx.thread_id},
                "recursion_limit": self._recursion_limit_override or self._recursion_limit(),
            },
            run_metrics.current(),
        )

        interrupted = False
        stream = agent.astream(graph_input, config=config, stream_mode=STREAM_MODES, subgraphs=True)
        try:
            async for chunk in stream:
                mode, raw, namespace = _unpack(chunk)
                # The summarisation model call is not part of this stream (langchain marks
                # it internal); test_summary_model_output_is_not_answer_text guards that.
                for event in await output.feed(mode, raw, namespace):
                    if isinstance(event, NeedUserInput):
                        interrupted = True
                if gate.hit is not None:
                    # Nothing after the blocked text runs: no further tool or model call.
                    return _WORK_BLOCKED
        finally:
            # Ends the graph when the loop was left early; a no-op after a full run.
            await stream.aclose()
        if interrupted:
            # The rest of the answer comes after the user's reply; the resumed
            # execution scans the whole text.
            return STATUS_WAITING
        return _WORK_BLOCKED if gate.finish() is not None else STATUS_FINISHED

    async def _prepare(
        self, ctx: DirectRunContext, sink: Callable[[dict], Awaitable[None]], intake: AttachmentIntake | None = None
    ) -> Any:
        from bisheng.linsight.domain.services.tool_assembly import defer_workspace_preparation

        file_dir = self._file_dir_for(ctx)
        # T059: the numbering table of the conversation and the memory turn, before
        # any tool is built. ``run`` opened the turn; a caller that enters below
        # ``run`` gets one that lives for this call only.
        turn = direct_run_turn.current(ctx.run_id) or direct_run_turn.DirectTurn(ctx.conversation_id, ctx.run_id)
        await turn.prepare(ctx, self._redis_of_lease())
        backend = await self._build_backend(ctx, file_dir, sink)
        if intake is not None:
            # T057: a read of ``uploads/`` waits for attachments still being parsed.
            intake.guard(backend)
        if getattr(backend, "citation_scope", turn) is None:
            # Files the run writes go through the same ``[Sn]`` conversion as the answer.
            backend.citation_scope = turn.scope
        # Skills first: the copy must be in ``file_dir`` before the code tool is
        # built (the E2B executor reads its copy-in set at construction) and
        # before the prompt advertises them (prompt <=> tool lockstep).
        skills_present = await self._mount_skills(ctx, backend, sink)
        assembly = await self._assemble(ctx, file_dir, **self._accepted_kwargs(self._assemble, {"turn": turn}))
        for failure in getattr(assembly, "failures", None) or []:
            await sink(self._tool_failure_event(ctx, failure))
        tools = list(assembly.tools)

        prepared = False
        lock = asyncio.Lock()

        async def prepare_workspace() -> None:
            """First code execution: create the directory, fetch what earlier executions left."""
            nonlocal prepared
            async with lock:
                if prepared:
                    return
                os.makedirs(file_dir, exist_ok=True)
                if intake is not None:
                    # The code reads ``uploads/`` from the local copy fetched below.
                    await intake.wait()
                await self._sync_workspace(ctx, backend, file_dir)
                await self._file_baseline(ctx, backend)
                prepared = True

        self._attach_run_extras(sink, backend, tools)
        defer_workspace_preparation(tools, prepare_workspace)
        optional = {
            **self._inbox_kwargs(ctx, sink),
            "backend": backend,
            "skills_present": skills_present,
            "turn": turn,
        }
        return await self._build_agent(
            ctx, tools, self._get_checkpointer(), file_dir, **self._accepted_kwargs(self._build_agent, optional)
        )

    @staticmethod
    def _accepted_kwargs(func: Callable[..., Any], kwargs: dict[str, Any]) -> dict[str, Any]:
        """The entries of ``kwargs`` that ``func`` declares (an injected four-argument builder gets none)."""
        try:
            parameters = inspect.signature(func).parameters
        except (TypeError, ValueError):
            return {}
        return {name: value for name, value in kwargs.items() if name in parameters}

    async def _mount_skills(self, ctx: DirectRunContext, backend: Any, sink: Callable[[dict], Awaitable[None]]) -> bool:
        """Copy every skill the user may use into the run directory. True when at least one is there.

        F005 (AC-24): like deep research, a direct run mounts all of them whether or
        not the user picked any; the picked ones are only the highlight. The copy
        is local (no workspace write), so a user without skills still gets no
        local directory (决策 10).

        A failure to list the user's skills (database or permission service) does
        not fail the answer: skills are an extra here, and the user usually picked
        none. Unlike deep research, the run goes on without skills; picked skills
        are reported as not loaded. A single skill that fails to copy is already
        handled inside provisioning.

        The open API (``unattended``) uses only the skills its caller passed
        (AC-21): with none passed, nothing is mounted.
        """
        if ctx.unattended and not ctx.skills:
            return False
        try:
            result = await self._provision_skills(ctx, backend)
        except Exception:
            # Non-critical extra (user decision 2026-11-20); logged with the traceback, picked skills are reported.
            logger.exception(
                "direct run={} conversation={}: skill provisioning failed; answering without skills",
                ctx.run_id,
                ctx.conversation_id,
            )
            if ctx.skills:
                await sink(self._skill_failure_event(ctx, list(ctx.skills)))
            return False
        snapshot = getattr(result, "snapshot", None)
        if snapshot:
            # Reads of ``skills/<name>/`` check the row that owns the directory.
            backend.skill_snapshot = list(snapshot)
        failed = [name for name in (getattr(result, "failed", None) or []) if name in ctx.skills]
        if failed:
            logger.warning(
                "direct run={} conversation={}: selected skills could not be loaded: {}",
                ctx.run_id,
                ctx.conversation_id,
                failed,
            )
            await sink(self._skill_failure_event(ctx, failed))
        return bool(getattr(result, "copied", None))

    @staticmethod
    def _skill_failure_event(ctx: DirectRunContext, names: list[str]) -> dict:
        """Selected skills that could not be loaded, as one finished ``tool_call`` (the user sees it)."""
        message = "以下技能未能加载，本次回答不会使用：" + "、".join(names)
        return run_events.make_event(
            run_events.TOOL_CALL,
            run_events.ToolCallData(
                call_id=f"skill_load_fail:{ctx.run_id}",
                name="load_skills",
                status="end",
                params={"skills": list(names)},
                output=message,
                extra_info={"kind": "skill_load_failed", "error": message, "init_failed": True, "skills": list(names)},
            ),
            run_id=ctx.run_id,
        )

    async def _read_relay_inbox(self, ctx: DirectRunContext, sink: Callable[[dict], Awaitable[None]]) -> None:
        """T043: a relay run takes the unread inbox as its input and says so.

        Each message gets ``steer_read``, like a message the inbox middleware
        reads mid-run, so its "queued" mark is cleared (AC-14). A message that
        arrives after this is read by the middleware at the first model call.
        """
        ctx.inbox_messages = await self.dispatch.drain_inbox(ctx.conversation_id)
        metrics = run_metrics.current()
        now_ms = self._clock() * 1000
        for message in ctx.inbox_messages:
            message_id = str(message.get("message_id") or "")
            if metrics is not None and message.get("ts"):
                metrics.record_steer_wait(max(0.0, now_ms - float(message["ts"])))
            if message_id:
                await sink(
                    run_events.make_event(
                        run_events.STEER_READ, run_events.SteerData(message_id=message_id), run_id=ctx.run_id
                    )
                )

    def _inbox_kwargs(self, ctx: DirectRunContext, sink: Callable[[dict], Awaitable[None]]) -> dict[str, Any]:
        """T041: ``inbox=<InboxMiddleware of this run>`` for a ``build_agent`` that takes it.

        The middleware writes ``steer_read`` through ``sink``, so the event reaches
        the stream and the event hooks. An injected ``build_agent`` with the
        four-argument signature is called as before.
        """
        try:
            parameters = inspect.signature(self._build_agent).parameters
        except (TypeError, ValueError):
            # Not introspectable (a C callable): treat it as the four-argument form.
            return {}
        if "inbox" not in parameters:
            return {}
        from bisheng.linsight.domain.services.inbox_middleware import InboxMiddleware

        metrics = run_metrics.current()
        return {
            "inbox": InboxMiddleware(
                ctx.conversation_id,
                run_id=ctx.run_id,
                drain=self.dispatch.drain_inbox,
                emit=sink,
                clock=self._clock,
                record_wait=metrics.record_steer_wait if metrics is not None else None,
            )
        }

    @staticmethod
    def _attachment_event(ctx: DirectRunContext, files: list, status: str, *, extra: dict | None = None) -> dict:
        """One frame of the "reading attachments" ``tool_call`` (start / end share ``call_id``).

        ``extra`` of the end frame: ``failed`` (names that could not be read) and
        ``still_parsing`` (names whose parsing continues after the run).
        """
        extra = {"kind": "attachment_reading", "file_count": len(files), **(extra or {})}
        output = None
        if status == "end":
            failed = extra.get("failed") or []
            output = ("以下附件未能读取：" + "、".join(failed)) if failed else ""
            if failed:
                extra["error"] = output
        return run_events.make_event(
            run_events.TOOL_CALL,
            run_events.ToolCallData(
                call_id=f"attachments:{ctx.run_id}",
                name=ATTACHMENT_TOOL_NAME,
                status=status,
                params={"files": [direct_attachments.file_name_of(f) for f in files]},
                output=output,
                extra_info=extra,
            ),
            run_id=ctx.run_id,
        )

    @staticmethod
    def _tool_failure_event(ctx: DirectRunContext, failure: dict) -> dict:
        """A tool that could not be initialised, as one finished ``tool_call`` (AC: the user sees it)."""
        extra = {key: failure[key] for key in ("display_name", "tool_type", "failure_info") if failure.get(key)}
        return run_events.make_event(
            run_events.TOOL_CALL,
            run_events.ToolCallData(
                call_id=f"init_fail:{ctx.run_id}:{failure.get('tool_key')}",
                name=str(failure.get("tool_key") or ""),
                status="end",
                output=str(failure.get("error") or ""),
                extra_info={**extra, "error": failure.get("error"), "init_failed": True},
            ),
            run_id=ctx.run_id,
        )

    # ------------------------------------------------------------- defaults

    @staticmethod
    def _session(ctx: DirectRunContext) -> Any:
        """What ``create_linsight_agent`` reads from a session version.

        A direct run has no ``linsight_session_version`` row (决策 7, pitfall 8).
        """
        return SimpleNamespace(
            id=ctx.conversation_id,
            session_id=ctx.conversation_id,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            question=ctx.text,
            api_meta={"channel": OPEN_API_CHANNEL} if ctx.unattended else None,
            skills=list(ctx.skills or []),
            skill_snapshot=None,
        )

    @staticmethod
    def _recursion_limit() -> int:
        from bisheng.common.services.config_service import settings
        from bisheng.linsight.domain.task_exec import _resolve_recursion_limit

        return _resolve_recursion_limit(settings.get_linsight_conf())

    @staticmethod
    def _default_file_dir(ctx: DirectRunContext) -> str:
        from bisheng.core.cache.utils import CACHE_DIR

        return os.path.normpath(os.path.join(CACHE_DIR, "linsight", f"c_{ctx.conversation_id}"))

    @staticmethod
    async def _default_object_store() -> Any:
        from bisheng.core.storage.minio.minio_manager import get_minio_storage

        return await get_minio_storage()

    async def _default_admit(self, ctx: DirectRunContext) -> None:
        """Same rule as deep research: one quota check when the run starts (AC-37)."""
        from bisheng.common.services.config_service import settings

        if not settings.credit_billing.enabled:
            return
        from bisheng.dsh.domain.services.chat_credits import admit_round
        from bisheng.linsight.domain.services import agent_factory

        model, _ = await agent_factory._resolve_model(self._session(ctx), ctx.model_id)
        await admit_round(model)

    async def _default_assemble(self, ctx: DirectRunContext, file_dir: str, turn: Any = None) -> Any:
        from bisheng.linsight.domain.services.tool_assembly import (
            CODE_INTERPRETER_TOOL_KEY,
            ToolAssemblyRequest,
            assemble_tools,
        )

        # Only a run whose user selected code execution gets the workspace-bound
        # interpreter (AC-46); other runs build no executor. It is bound the
        # deep-research way: ``file_dir`` is its working directory and
        # ``workspace/{conversation_id}`` the prefix it mirrors its files into.
        # ``_prepare`` defers creating the directory to the first execution.
        wants_code = any(isinstance(p, dict) and p.get("tool_key") == CODE_INTERPRETER_TOOL_KEY for p in ctx.tools)
        login_user = None
        if ctx.knowledge:
            from bisheng.common.dependencies.user_deps import UserPayload

            login_user = await UserPayload.init_login_user(user_id=ctx.user_id, user_name="", tenant_id=ctx.tenant_id)
        return await assemble_tools(
            ToolAssemblyRequest(
                user_id=ctx.user_id,
                login_user=login_user,
                tool_payloads=list(ctx.tools or []),
                knowledge_bases_info=list(ctx.knowledge or []) or None,
                file_dir=file_dir if wants_code else None,
                # The interpreter mirrors its files into workspace/{conversation_id}.
                session_version_id=ctx.conversation_id if wants_code else None,
                # T059: the tools register their hits with the turn's collector and
                # show the conversation's ``[Sn]`` numbers (shared with deep research).
                citation_collector=turn.collector if turn is not None else None,
                citation_scope=turn.scope if turn is not None else None,
            )
        )

    async def _default_build_backend(
        self, ctx: DirectRunContext, file_dir: str, sink: Callable[[dict], Awaitable[None]] | None = None
    ) -> Any:
        """The workspace of the conversation: ``workspace/{conversation_id}`` plus a local cache.

        ``sink`` writes one event of this run to the stream and to the event
        hooks; a file-event callback of the backend is attached here.
        """
        from bisheng.linsight.domain.services.file_events import FileEventRelay
        from bisheng.linsight.domain.services.workspace_backend import WorkspaceBackend, workspace_prefix_for

        prefix = workspace_prefix_for(ctx.conversation_id)
        return WorkspaceBackend(
            minio=await self._object_store(),
            file_dir=file_dir,
            workspace_prefix=prefix,
            # 决策 10: no local directory until the first file operation.
            create_cache_dir=False,
            # T055: a file stored under ``output/`` becomes a ``file`` event at once.
            on_output_file=(
                FileEventRelay(sink, run_id=ctx.run_id, workspace_prefix=prefix) if sink is not None else None
            ),
        )

    async def _default_provision_skills(self, ctx: DirectRunContext, backend: Any) -> Any:
        """Deep research's skill copy, addressed by conversation instead of a session-version row.

        With ``user_id`` every skill the user may use is copied and the selected
        names are the highlighted ones, exactly as in a deep-research run. A
        direct run keeps no snapshot between executions, so each execution
        copies them again from the node cache (F005 决策 5).
        """
        from bisheng.linsight.domain.services import skill_provisioning

        return await skill_provisioning.materialize_session_skills(
            backend, ctx.tenant_id, list(ctx.skills or []), user_id=ctx.user_id
        )

    async def _default_sync_workspace(self, ctx: DirectRunContext, backend: Any, file_dir: str) -> None:
        """Fetch ``output/``, ``uploads/`` and ``large_tool_results/`` into the local cache.

        Reuses ``LinsightWorkflowTask._sync_workspace_originals``: the method reads
        only ``file_dir``, ``_baseline_files`` and ``_workspace_backend`` of its
        task, so it is called with a stand-in that carries those three. It is
        best-effort and never raises.
        """
        from bisheng.linsight.domain.task_exec import LinsightWorkflowTask

        stand_in = SimpleNamespace(
            file_dir=file_dir,
            _baseline_files={},
            _workspace_backend=lambda _session, _minio, **_kwargs: backend,
        )
        await LinsightWorkflowTask._sync_workspace_originals(stand_in, SimpleNamespace(id=ctx.conversation_id))

    @staticmethod
    @asynccontextmanager
    async def _default_department_slot(ctx: DirectRunContext):
        """The department concurrency limit of the legacy daily chat (``DepartmentFlowService``).

        With a page lease the run renews the page's slot and leaves it to the
        page heartbeat. Without one it takes an execution lease, renews it while
        the run executes and releases it when the run leaves this block.
        """
        from bisheng.common.errcode.workstation import DepartmentDailyChatConcurrentLimitError
        from bisheng.department.domain.services.department_flow_service import DepartmentFlowService, SlotOutcome

        # ``DepartmentFlowService`` reads only ``user_id`` of the login user.
        user = SimpleNamespace(user_id=ctx.user_id)
        if ctx.execution_lease_id:
            # Taken by the send request before the run started; released here.
            async with DepartmentFlowService.hold_execution_lease(user, ctx.execution_lease_id) as (outcome, _lease):
                if outcome is SlotOutcome.REJECTED:
                    raise DepartmentDailyChatConcurrentLimitError()
                yield
            return
        if ctx.page_lease_id:
            outcome, _ = await DepartmentFlowService.ensure_lease(user, ctx.page_lease_id)
            if outcome is SlotOutcome.REJECTED:
                raise DepartmentDailyChatConcurrentLimitError()
            yield
            return
        async with DepartmentFlowService.hold_execution_lease(user) as (outcome, _lease):
            if outcome is SlotOutcome.REJECTED:
                raise DepartmentDailyChatConcurrentLimitError()
            yield

    @staticmethod
    def _default_safety_scanner(ctx: DirectRunContext) -> Any:
        """The output scanner of the legacy daily chat, or None when the tenant has it off."""
        from bisheng.sensitive_word.domain.services.sensitive_word_policy_service import SensitiveWordPolicyService

        if not SensitiveWordPolicyService.is_workbench_content_safety_active(ctx.tenant_id):
            return None
        from bisheng.sensitive_word.domain.services.stream_scanner import StreamContentSafetyScanner

        return StreamContentSafetyScanner(ctx.tenant_id)

    @staticmethod
    async def _default_mark_violation(ctx: DirectRunContext) -> None:
        """What ``persist_safety_replacement`` writes besides the answer row."""
        from bisheng.database.models.message import ChatMessageDao
        from bisheng.database.models.session import SensitiveStatus
        from bisheng.workstation.domain.services.content_safety import mark_session_content_violation

        if ctx.question_message_id is not None:
            await ChatMessageDao.update_fields_by_id(
                int(ctx.question_message_id), sensitive_status=SensitiveStatus.VIOLATIONS.value
            )
        else:
            logger.warning(
                "direct run={} conversation={}: no question row id; only the conversation is marked",
                ctx.run_id,
                ctx.conversation_id,
            )
        # A synchronous DAO call.
        await asyncio.to_thread(mark_session_content_violation, ctx.conversation_id)

    async def _default_build_agent(
        self,
        ctx: DirectRunContext,
        tools: list,
        checkpointer: Any,
        file_dir: str,
        inbox: Any = None,
        backend: Any = None,
        skills_present: bool = False,
        turn: Any = None,
    ) -> Any:
        from bisheng.linsight.domain.services import agent_factory

        if backend is None:
            backend = await self._build_backend(ctx, file_dir, None)
        session = self._session(ctx)
        session.skill_snapshot = getattr(backend, "skill_snapshot", None)
        return await agent_factory.create_linsight_agent(
            session,
            tools,
            model_id=ctx.model_id,
            file_dir=file_dir,
            backend=backend,
            checkpointer=checkpointer,
            # Lockstep: the prompt lists skills only when the copy is in the workspace.
            skills_present=skills_present,
            profile=PROFILE,
            inbox=inbox,
            # T059: citation rules and memory follow what the turn actually has.
            citation_scope=turn.scope if turn is not None else None,
            memory=turn.memory_wiring if turn is not None else None,
            custom_system_prompt=await self._custom_prompt(),
        )

    def _default_attachment_source(self, ctx: DirectRunContext) -> Any:
        """Upload-parse state in Redis, files in the conversation workspace (决策 12)."""
        # Wall clock on purpose: the upload wrote ``started_at`` with ``time.time()``.
        return direct_attachments.WorkspaceAttachmentSource(object_store=self._object_store)

    async def _default_build_input(self, ctx: DirectRunContext) -> dict:
        """First message of a new run; a relay run reads the unread inbox instead."""
        from bisheng.linsight.domain import utils as linsight_utils
        from bisheng.linsight.domain.task_exec import LinsightWorkflowTask

        texts = [ctx.text] if ctx.text else []
        if ctx.relay:
            # ``_work`` has read the inbox; a direct caller of this function has not.
            unread = ctx.inbox_messages
            if unread is None:
                unread = await self.dispatch.drain_inbox(ctx.conversation_id)
            for message in unread:
                if message.get("text"):
                    texts.append(message["text"])
        if not texts:
            raise ValueError(f"direct run {ctx.run_id} has no input message")

        parts = [LinsightWorkflowTask._current_time_block()]
        # 决策 7 / K6: a thread without a checkpoint (expired, or older than the
        # unified runtime) gets the earlier turns rebuilt from ChatMessage.
        thread = {"configurable": {"thread_id": ctx.thread_id}}
        if await self._get_checkpointer().aget_tuple(thread) is None:
            history = await linsight_utils.build_prior_conversation_summary(ctx.conversation_id)
            if history:
                # Stored answers carry citation markers; the model reads ``[Sn]`` (F075).
                turn = direct_run_turn.current(ctx.run_id)
                parts.append(turn.history_for_model(history) if turn is not None else history)
        parts.append(f"# 用户问题\n{texts[0]}")
        messages = [{"role": "user", "content": "\n".join(parts)}]
        messages.extend({"role": "user", "content": text} for text in texts[1:])
        return {"messages": messages}


async def execute_direct_run(
    run_ctx: DirectRunContext | dict,
    *,
    runner: DirectRunner | None = None,
    on_event: Iterable[EventHook] = (),
) -> DirectRunOutcome:
    """Run one execution to its end. Used by ``start_direct_run`` and by the worker (relay runs).

    Restores the tenant context from ``run_ctx`` and resets it afterwards.
    """
    from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
    from bisheng.core.logger import trace_id_var

    ctx = _coerce(run_ctx)
    token = set_current_tenant_id(ctx.tenant_id)
    trace_token = trace_id_var.set(ctx.run_id)
    try:
        return await (runner or DirectRunner()).run(ctx, on_event=on_event)
    finally:
        trace_id_var.reset(trace_token)
        current_tenant_id.reset(token)


def start_direct_run(
    run_ctx: DirectRunContext | dict,
    *,
    runner: DirectRunner | None = None,
    on_event: Iterable[EventHook] = (),
) -> asyncio.Task:
    """Start the run in a background coroutine that outlives the HTTP request."""
    ctx = _coerce(run_ctx)
    task = asyncio.create_task(
        execute_direct_run(ctx, runner=runner, on_event=on_event), name=f"direct-run:{ctx.run_id}"
    )
    _TASKS.add(task)
    task.add_done_callback(_on_task_done)
    return task


def _on_task_done(task: asyncio.Task) -> None:
    _TASKS.discard(task)
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.opt(exception=error).error("{} ended with an unhandled error", task.get_name())
