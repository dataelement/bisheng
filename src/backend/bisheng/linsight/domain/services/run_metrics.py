"""F004 T038 (AC-34, design §7): one ``BS_METRIC domain=agent_run`` line per execution.

Both executors of the unified runtime (``direct_run`` and the planned path in
``task_exec``) emit the line when an execution ends (finished, failed, stopped,
parked on ask_user). Format and gating are the F042 ``emit_metric`` contract;
fields whose value is unknown are omitted (``None``).

Fields
------

``profile``           ``direct`` | ``planned``.
``status``            ``finished`` | ``failed`` | ``stopped`` | ``waiting`` | ``lease_lost``
                      (planned only: ``unknown`` when the execution ended without a
                      terminal event, e.g. a duplicate driver).
``resume``            1 when the execution continues a parked run with the user's answer.
``prep_ms``           message accepted by the send entry -> first model request of
                      this execution. Includes ``queue_ms``. Omitted when no model
                      request was made.
``queue_ms``          message accepted by the send entry -> this execution started.
                      Omitted when the run did not come through ``run_dispatch.submit``
                      (its acceptance time is unknown); ``prep_ms`` is then measured
                      from the start of the execution.
``steer_wait_ms``     the longest wait of a steer message of this execution, from
                      entering the inbox to being read by the model. 0 when none.
``steer_count``       number of steer messages read by this execution.
``checkpoint_bytes``  serialized size of the latest root checkpoint of the thread
                      after the execution. Omitted when it cannot be read.
``total_ms``          execution start -> end.

The run id is not a field: the log line carries it as its trace id.

The acceptance time is the ``updated_at`` field of the conversation state
(``run_lease``), which the send entry writes when it starts or queues the run
and which nothing rewrites before the executor's first ``renew``. So it must be
read BEFORE that ``renew``.

Steer messages: the inbox middleware calls ``record_steer_wait(wait_ms)``. The
metrics of the current execution live in a ContextVar set by the executor; the
graph's tasks inherit it. Nothing here is run state (C8): it is telemetry of one
execution in the process that drives it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any

from langchain_core.callbacks import AsyncCallbackHandler
from loguru import logger

from bisheng.common.services.metric_log import emit_metric

METRIC_DOMAIN = "agent_run"

_current: ContextVar[RunMetrics | None] = ContextVar("f004_run_metrics", default=None)


@dataclass
class RunMetrics:
    """Timings of one execution. Times are seconds of ``clock``."""

    profile: str
    clock: Callable[[], float] = time.time
    resume: bool = False
    started_at: float = 0.0
    submitted_at: float | None = None
    first_model_at: float | None = None
    # LangGraph thread the execution ran on (set by ``with_metric_callback``).
    thread_id: str | None = None
    steer_waits_ms: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.started_at:
            self.started_at = self.clock()

    def mark_model_request(self) -> None:
        if self.first_model_at is None:
            self.first_model_at = self.clock()

    def record_steer_wait(self, wait_ms: float) -> None:
        self.steer_waits_ms.append(max(0.0, float(wait_ms)))

    def fields(self, status: str, checkpoint_bytes: int | None) -> dict[str, Any]:
        origin = self.submitted_at if self.submitted_at is not None else self.started_at
        return {
            "profile": self.profile,
            "status": status,
            "resume": self.resume,
            "prep_ms": None if self.first_model_at is None else max(0.0, (self.first_model_at - origin) * 1000.0),
            "queue_ms": None if self.submitted_at is None else max(0.0, (self.started_at - self.submitted_at) * 1000.0),
            "steer_wait_ms": max(self.steer_waits_ms, default=0.0),
            "steer_count": len(self.steer_waits_ms),
            "checkpoint_bytes": checkpoint_bytes,
            "total_ms": max(0.0, (self.clock() - self.started_at) * 1000.0),
        }


def activate(metrics: RunMetrics) -> Token:
    """Make ``metrics`` the metrics of the current execution (tasks created afterwards inherit it)."""
    return _current.set(metrics)


def deactivate(token: Token) -> None:
    _current.reset(token)


def current() -> RunMetrics | None:
    return _current.get()


def record_steer_wait(wait_ms: float) -> None:
    """Record that a steer message waited ``wait_ms`` in the inbox before the model read it.

    For the inbox middleware. Outside an execution of the unified runtime it does nothing.
    """
    metrics = _current.get()
    if metrics is None:
        logger.debug("record_steer_wait outside a unified run; {} ms not recorded", wait_ms)
        return
    metrics.record_steer_wait(wait_ms)


class FirstModelRequestCallback(AsyncCallbackHandler):
    """Marks the moment the first model request of the execution goes out.

    Put it into the ``callbacks`` of the graph config; it is inherited by every
    model call of the run (sub-agents included). Only the first call counts.
    """

    def __init__(self, metrics: RunMetrics):
        self._metrics = metrics

    async def on_chat_model_start(self, serialized: Any, messages: Any, **kwargs: Any) -> None:
        self._metrics.mark_model_request()

    async def on_llm_start(self, serialized: Any, prompts: Any, **kwargs: Any) -> None:
        self._metrics.mark_model_request()


def with_metric_callback(config: dict, metrics: RunMetrics | None) -> dict:
    """``config`` plus the first-model-request callback (unchanged when ``metrics`` is None)."""
    if metrics is None:
        return config
    thread_id = (config.get("configurable") or {}).get("thread_id")
    if thread_id:
        metrics.thread_id = str(thread_id)
    callbacks = list(config.get("callbacks") or [])
    callbacks.append(FirstModelRequestCallback(metrics))
    return {**config, "callbacks": callbacks}


async def read_submitted_at(redis: Any, conversation_id: str, run_id: str) -> float | None:
    """When the send entry accepted the message of ``run_id`` (epoch seconds), or None.

    Call before the executor's first ``renew``, which rewrites ``updated_at``.
    """
    from bisheng.workstation.domain.services.run_lease import FIELD_UPDATED_AT, state_key

    if redis is None:
        return None
    try:
        holder, updated_at = await redis.hmget(state_key(conversation_id), ["run_id", FIELD_UPDATED_AT])
    except Exception as exc:
        # Telemetry only: the run goes on, queue_ms is omitted.
        logger.warning("run={}: could not read the acceptance time: {!r}", run_id, exc)
        return None
    if isinstance(holder, bytes):
        holder = holder.decode()
    if holder != run_id or updated_at in (None, b"", ""):
        return None
    try:
        return int(updated_at) / 1000.0
    except (TypeError, ValueError):
        logger.warning("run={}: unreadable updated_at {!r}", run_id, updated_at)
        return None


async def checkpoint_size(checkpointer: Any, thread_id: str) -> int | None:
    """Serialized size of the latest root checkpoint of ``thread_id``, or None."""
    if checkpointer is None:
        return None
    try:
        saved = await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id}})
        if saved is None:
            return 0
        _, data = checkpointer.serde.dumps_typed(saved.checkpoint)
        return len(data)
    except Exception as exc:
        # Telemetry only: the line goes out without the field.
        logger.warning("thread={}: could not measure the checkpoint: {!r}", thread_id, exc)
        return None


def emit_run_metric(metrics: RunMetrics, status: str, checkpoint_bytes: int | None) -> None:
    """Emit the ``agent_run`` line. Never raises (``emit_metric`` is best-effort)."""
    emit_metric(METRIC_DOMAIN, **metrics.fields(status, checkpoint_bytes))
