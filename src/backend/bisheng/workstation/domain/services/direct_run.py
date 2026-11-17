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
3. Quota admission, once (AC-37), while tools and the agent are built.
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

State: nothing about a run is kept in process memory (C8). ``_TASKS`` only
protects running coroutines from garbage collection.

Event hooks (for the persistence projector)
-------------------------------------------

A hook is ``async def hook(event: dict) -> None`` (a plain function also
works). ``event`` is ``{"type", "data", "run_id"}`` exactly as it is handed to
the ``EventWriter``, before the 50 ms merge of ``text`` / ``thinking``. Hooks
are awaited one by one, in order, after the event was accepted by the writer.
The terminal event reaches the hooks BEFORE ``on_run_finished`` runs. A hook
that raises is logged and does not stop the run.

Pass hooks per run (``on_event=[...]``) or register a factory once with
``register_event_hook_factory(factory)``; ``factory(ctx)`` returns the hook of
one execution.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import asdict, dataclass, field, fields
from types import SimpleNamespace
from typing import Any

from loguru import logger

from bisheng.linsight.domain.schemas import run_events
from bisheng.linsight.domain.services import run_metrics
from bisheng.linsight.domain.services.run_event_stream import EventWriter, RunEventStream
from bisheng.workstation.domain.services.run_dispatch import RunDispatchService
from bisheng.workstation.domain.services.run_lease import RENEW_INTERVAL_SECONDS, RunLeaseService

PROFILE = "direct"
STOP_POLL_SECONDS = 1.0
STREAM_MODES = ["updates", "messages", "values"]

STATUS_FINISHED = "finished"
STATUS_FAILED = "failed"
STATUS_STOPPED = "stopped"
STATUS_WAITING = "waiting"
# Another caller took the conversation (the lease lapsed and the dispatcher
# already emitted run_failed for this run). Nothing more is written.
STATUS_LEASE_LOST = "lease_lost"

EventHook = Callable[[dict], Awaitable[None] | None]
EventHookFactory = Callable[["DirectRunContext"], EventHook]


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


# T037 (AC-51): the "reading attachments" progress frames are one ``tool_call``.
ATTACHMENT_TOOL_NAME = "read_attachments"


@dataclass
class AttachmentReading:
    """What ``_process_agent_files`` returns: inlined text, image data URLs, files with covers."""

    file_context: str = ""
    images: list = field(default_factory=list)
    files: list = field(default_factory=list)


def attachments_to_read(ctx: DirectRunContext) -> list:
    """Attachments a new execution parses; a resume already read them in its first execution."""
    if ctx.is_resume:
        return []
    return [f for f in ctx.files or [] if isinstance(f, dict) and f.get("filepath")]


def _attachment_name(item: dict) -> str:
    return str(item.get("file_name") or item.get("filename") or item.get("name") or item.get("filepath") or "")


def _with_attachments(graph_input: Any, reading: AttachmentReading | None) -> Any:
    """Add the parsed attachments to the first user message (legacy daily chat inlines them too)."""
    if reading is None or not (reading.file_context or reading.images):
        return graph_input
    messages = list(graph_input.get("messages") or []) if isinstance(graph_input, dict) else []
    if not messages or not isinstance(messages[0], dict):
        logger.warning("direct run: graph input has no first user message; attachments not inlined")
        return graph_input
    first = dict(messages[0])
    text = str(first.get("content") or "")
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


_HOOK_FACTORIES: list[EventHookFactory] = []
_DEFAULT_ENQUEUE_RELAY: Callable[[dict], Awaitable[None]] | None = None
# Strong references to running coroutines (asyncio keeps only weak ones).
_TASKS: set[asyncio.Task] = set()


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
    from bisheng.linsight.worker import enqueue_relay_run, planned_queue_position

    return {
        "enqueue_relay": enqueue_relay or _DEFAULT_ENQUEUE_RELAY or enqueue_relay_run,
        "on_run_expired": mark_run_expired,
        "queue_position": planned_queue_position,
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
    ``read_attachments(ctx)``  parses ``ctx.files``; returns ``AttachmentReading``.
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
        read_attachments: Callable[[DirectRunContext], Awaitable[AttachmentReading]] | None = None,
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
        self._read_attachments = read_attachments or self._default_read_attachments
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

        async def sink(event: dict) -> None:
            await writer.emit(event)
            for hook in hooks:
                try:
                    result = hook(event)
                    if inspect.isawaitable(result):
                        await result
                except Exception:
                    logger.exception(
                        "direct run={} conversation={}: event hook failed on a {} event",
                        ctx.run_id,
                        ctx.conversation_id,
                        event.get("type"),
                    )

        output = UnifiedEventOutput(StreamEventMapper(svid=ctx.run_id), sink, run_id=ctx.run_id)
        started = self._clock()
        # T038: read before ``_execute`` renews the lease (the renew rewrites the time).
        metrics = run_metrics.RunMetrics(PROFILE, clock=self._clock, resume=ctx.is_resume, started_at=started)
        metrics.submitted_at = await run_metrics.read_submitted_at(
            self._redis_of_lease(), ctx.conversation_id, ctx.run_id
        )
        metrics_token = run_metrics.activate(metrics)
        try:
            outcome = await self._execute(ctx, output, sink)
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
        finally:
            try:
                await asyncio.shield(writer.aclose())
            except Exception:
                logger.exception("direct run={}: could not flush the event writer", ctx.run_id)
            run_metrics.deactivate(metrics_token)

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
                # The inbox is kept; the relay lease lapses and the next access
                # to the conversation recovers it (run_dispatch contract).
                logger.exception(
                    "direct run={} conversation={}: on_run_finished failed", ctx.run_id, ctx.conversation_id
                )
        # After the conversation was handed on: measuring the checkpoint delays nobody.
        checkpoint_bytes = await run_metrics.checkpoint_size(self._get_checkpointer(), ctx.thread_id)
        run_metrics.emit_run_metric(metrics, outcome.status, checkpoint_bytes)
        return outcome

    def _redis_of_lease(self) -> Any:
        """The Redis client that holds the conversation state."""
        return getattr(self.lease, "_redis", None) or self._redis

    async def _execute(self, ctx: DirectRunContext, output: Any, sink: Callable[[dict], Awaitable[None]]) -> Any:
        cid, run_id = ctx.conversation_id, ctx.run_id
        if not await self.lease.renew(cid, run_id):
            logger.warning("direct run={} does not hold conversation={}; not executed", run_id, cid)
            return DirectRunOutcome(STATUS_LEASE_LOST)

        work = asyncio.create_task(self._work(ctx, output, sink))
        watch = asyncio.create_task(self._watch(ctx))
        try:
            await asyncio.wait({work, watch}, return_when=asyncio.FIRST_COMPLETED)
            if work.done():
                error = work.exception()
                if error is not None:
                    # The traceback belongs to the task; log it here, where it is handled.
                    logger.opt(exception=error).error("direct run={} conversation={} failed", run_id, cid)
                    await output.run_failed(error)
                    return DirectRunOutcome(STATUS_FAILED, error)
                if work.result() == STATUS_WAITING:
                    return await self._park(ctx)
                await output.run_finished()
                return DirectRunOutcome(STATUS_FINISHED)

            reason = watch.result()
            work.cancel()
            await asyncio.gather(work, return_exceptions=True)
            if reason == STATUS_STOPPED:
                # Text already written stays in the accumulated state (AC-29).
                await output.run_stopped("user")
            return DirectRunOutcome(reason)
        finally:
            for task in (work, watch):
                if not task.done():
                    task.cancel()
            await asyncio.gather(work, watch, return_exceptions=True)

    async def _park(self, ctx: DirectRunContext) -> DirectRunOutcome:
        if not await self.lease.park(ctx.conversation_id, ctx.run_id):
            logger.warning(
                "direct run={} asked the user but no longer holds conversation={}", ctx.run_id, ctx.conversation_id
            )
            return DirectRunOutcome(STATUS_LEASE_LOST)
        logger.info("direct run={} conversation={} waits for the user's answer", ctx.run_id, ctx.conversation_id)
        return DirectRunOutcome(STATUS_WAITING)

    async def _watch(self, ctx: DirectRunContext) -> str:
        """Poll the stop flag every second, renew the lease every 10 s."""
        next_renew = self._clock() + RENEW_INTERVAL_SECONDS
        while True:
            await self._sleep(self._stop_poll_seconds)
            if await self.lease.should_stop(ctx.run_id):
                logger.info("direct run={} conversation={}: stop requested", ctx.run_id, ctx.conversation_id)
                return STATUS_STOPPED
            if self._clock() >= next_renew:
                if not await self.lease.renew(ctx.conversation_id, ctx.run_id):
                    logger.warning("direct run={} lost the lease of conversation={}", ctx.run_id, ctx.conversation_id)
                    return STATUS_LEASE_LOST
                next_renew = self._clock() + RENEW_INTERVAL_SECONDS

    async def _work(self, ctx: DirectRunContext, output: Any, sink: Callable[[dict], Awaitable[None]]) -> str:
        from bisheng_langchain.linsight.event import NeedUserInput

        if ctx.is_resume:
            snapshot = await self.stream.snapshot(ctx.conversation_id) or {}
            # A new mapper starts empty: give it the plan the run had when it parked.
            output.seed_plan(snapshot.get("plan") or [])
            pending = snapshot.get("pending_question") or {}
            await output.ask_user_answered(call_id=pending.get("call_id"), answer=ctx.answer)
        else:
            await output.run_started({"profile": PROFILE, "message_id": ctx.message_id, "relay": ctx.relay})
            for event in ctx.initial_events:
                await sink({**event, "run_id": ctx.run_id})

        # The agent is built while the quota is checked. Admission is awaited in
        # THIS task: it marks the context so the run's model calls skip the
        # per-call quota comparison (dsh ``admit_round``).
        # T037 (AC-51): the start frame is written before parsing begins; parsing
        # runs alongside admission and the agent build.
        files = attachments_to_read(ctx)
        reading_task = None
        if files:
            await sink(self._attachment_event(ctx, files, "start"))
            reading_task = asyncio.create_task(self._read_attachments_step(ctx, files, sink))
        prepare = asyncio.create_task(self._prepare(ctx, sink))
        try:
            await self._admit(ctx)
            agent = await prepare
            reading = await reading_task if reading_task is not None else None
        finally:
            for task in (prepare, reading_task):
                if task is not None and not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

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
        async for chunk in agent.astream(graph_input, config=config, stream_mode=STREAM_MODES, subgraphs=True):
            mode, raw, namespace = _unpack(chunk)
            # The summarisation model call is not part of this stream (langchain marks
            # it internal); test_summary_model_output_is_not_answer_text guards that.
            for event in await output.feed(mode, raw, namespace):
                if isinstance(event, NeedUserInput):
                    interrupted = True
        return STATUS_WAITING if interrupted else STATUS_FINISHED

    async def _prepare(self, ctx: DirectRunContext, sink: Callable[[dict], Awaitable[None]]) -> Any:
        file_dir = self._file_dir_for(ctx)
        assembly = await self._assemble(ctx, file_dir)
        for failure in getattr(assembly, "failures", None) or []:
            await sink(self._tool_failure_event(ctx, failure))
        return await self._build_agent(
            ctx, list(assembly.tools), self._get_checkpointer(), file_dir, **self._inbox_kwargs(ctx, sink)
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

    async def _read_attachments_step(
        self, ctx: DirectRunContext, files: list, sink: Callable[[dict], Awaitable[None]]
    ) -> AttachmentReading:
        """Parse the attachments, then close the progress frame (also on failure)."""
        try:
            reading = await self._read_attachments(ctx)
        except Exception as exc:
            logger.exception(
                "direct run={} conversation={}: reading attachments failed", ctx.run_id, ctx.conversation_id
            )
            await sink(self._attachment_event(ctx, files, "end", error=exc))
            raise
        await sink(self._attachment_event(ctx, files, "end"))
        return reading

    @staticmethod
    def _attachment_event(
        ctx: DirectRunContext, files: list, status: str, *, error: BaseException | None = None
    ) -> dict:
        """One frame of the "reading attachments" ``tool_call`` (start / end share ``call_id``)."""
        extra: dict[str, Any] = {"kind": "attachment_reading", "file_count": len(files)}
        output = None
        if status == "end":
            output = str(error) if error is not None else ""
            if error is not None:
                extra["error"] = str(error) or type(error).__name__
        return run_events.make_event(
            run_events.TOOL_CALL,
            run_events.ToolCallData(
                call_id=f"attachments:{ctx.run_id}",
                name=ATTACHMENT_TOOL_NAME,
                status=status,
                params={"files": [_attachment_name(f) for f in files]},
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
            api_meta=None,
            skills=list(ctx.skills or []),
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

        if not settings.dsh.enabled:
            return
        from bisheng.dsh.domain.services.chat_credits import admit_round
        from bisheng.linsight.domain.services import agent_factory

        model, _ = await agent_factory._resolve_model(self._session(ctx), ctx.model_id)
        await admit_round(model)

    async def _default_assemble(self, ctx: DirectRunContext, file_dir: str) -> Any:
        from bisheng.linsight.domain.services.tool_assembly import (
            CODE_INTERPRETER_TOOL_KEY,
            ToolAssemblyRequest,
            assemble_tools,
        )

        # Only a run whose user selected code execution gets the workspace-bound
        # interpreter (AC-46); other runs build no executor.
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
            )
        )

    async def _default_build_agent(
        self, ctx: DirectRunContext, tools: list, checkpointer: Any, file_dir: str, inbox: Any = None
    ) -> Any:
        from bisheng.linsight.domain.services import agent_factory
        from bisheng.linsight.domain.services.workspace_backend import WorkspaceBackend, workspace_prefix_for

        backend = WorkspaceBackend(
            minio=await self._object_store(),
            file_dir=file_dir,
            workspace_prefix=workspace_prefix_for(ctx.conversation_id),
            # 决策 10: no local directory until the first file operation.
            create_cache_dir=False,
        )
        return await agent_factory.create_linsight_agent(
            self._session(ctx),
            tools,
            model_id=ctx.model_id,
            file_dir=file_dir,
            backend=backend,
            checkpointer=checkpointer,
            profile=PROFILE,
            inbox=inbox,
        )

    async def _default_read_attachments(self, ctx: DirectRunContext) -> AttachmentReading:
        """The legacy daily chat parser, unchanged (T055 changes how parsing works)."""
        from bisheng.common.dependencies.user_deps import UserPayload
        from bisheng.workstation.domain.services.chat_service import _process_agent_files
        from bisheng.workstation.domain.services.workstation_service import WorkStationService

        ws_config = await WorkStationService.aget_config()
        models = getattr(ws_config, "models", None) or []
        model_info = next((m for m in models if str(getattr(m, "id", "")) == str(ctx.model_id)), None)
        if model_info is None:
            # No visual flag known: every file goes through text extraction.
            logger.warning(
                "direct run={}: model {} not in the workbench config; attachments parsed as documents",
                ctx.run_id,
                ctx.model_id,
            )
            model_info = SimpleNamespace(visual=False)
        login_user = await UserPayload.init_login_user(user_id=ctx.user_id, user_name="", tenant_id=ctx.tenant_id)
        file_context, images, files = await _process_agent_files(
            SimpleNamespace(files=list(ctx.files or [])),
            model_info,
            login_user,
            ws_config,
            conversation_id=ctx.conversation_id,
        )
        return AttachmentReading(file_context=file_context or "", images=list(images or []), files=list(files or []))

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
                parts.append(history)
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
