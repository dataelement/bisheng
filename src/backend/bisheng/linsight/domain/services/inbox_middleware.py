"""F004 T041: the inbox middleware (design 决策 5, AC-14 / AC-15 / AC-16).

A message the user sends while a run is in progress joins the inbox of the
conversation (``run_dispatch.submit``, branch ``queued``). Before every model
call of the MAIN graph this middleware takes the whole inbox and appends the
messages to the conversation as ``HumanMessage``. The step that is executing is
never interrupted: ``before_model`` runs after the tools node finished the whole
batch of tool calls, so the injected messages sit behind every tool result of
the previous step and never split a batch of tool messages.

Contract
--------

* ``drain(conversation_id)`` takes every inbox message, oldest first, exactly
  once. In production it is ``RunDispatchService.drain_inbox`` (one MULTI of
  LRANGE + DEL), so a message is read by exactly one caller: this middleware, or
  the runner that builds the input of a relay run. Each message is a dict with
  ``run_dispatch.INBOX_FIELDS``; this module reads ``message_id``, ``text``,
  ``ts`` (epoch milliseconds, written by ``submit``).
* For each message one ``steer_read`` event (``SteerData(message_id)``) goes to
  ``emit``. ``emit`` is the event sink of the run, so the event reaches the
  Redis stream and the event hooks of the runner. The events are written
  BEFORE the messages are returned to the graph.
* The wait of each message (``now - ts``) goes to ``record_wait`` in
  milliseconds (``run_metrics``).
* A message that arrives during the LAST model call is not read: no model call
  follows. It stays in the inbox and ``on_run_finished`` starts a relay run.

Known limit: the inbox is emptied in Redis before the graph checkpoints the
injected messages. A process that dies between the two loses these messages for
the model; the question rows of the conversation still hold them.

The middleware keeps no state of its own (C8). The factory mounts it on the main
graph only, and never for an unattended run.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import HumanMessage
from loguru import logger

from bisheng.linsight.domain.schemas import run_events
from bisheng.linsight.domain.services import run_metrics

# ``additional_kwargs["source"]`` of an injected message.
INBOX_SOURCE = "inbox"
# Prefix of the id of an injected message. The id is stable per inbox message,
# so the ``add_messages`` reducer replaces instead of duplicating if the same
# message were ever returned twice.
STEER_MESSAGE_ID_PREFIX = "steer-"

Drain = Callable[[str], Awaitable[list[dict]]]
Emit = Callable[[dict], Awaitable[None]]


class InboxMiddleware(AgentMiddleware):
    """Inject the unread inbox of one conversation before each model call.

    ``conversation_id``  the conversation whose inbox is read.
    ``drain``            ``async (conversation_id) -> list[dict]``, oldest first, exactly once.
    ``emit``             ``async (event) -> None``, the event sink of the run.
    ``run_id``           written into the ``steer_read`` events.
    ``clock``            epoch seconds; must be the clock ``submit`` stamps ``ts`` with.
    ``record_wait``      ``(wait_ms) -> None``; default ``run_metrics.record_steer_wait``.
    """

    def __init__(
        self,
        conversation_id: str,
        *,
        drain: Drain,
        emit: Emit,
        run_id: str | None = None,
        clock: Callable[[], float] = time.time,
        record_wait: Callable[[float], None] | None = None,
    ) -> None:
        super().__init__()
        if not conversation_id:
            raise ValueError("the inbox middleware needs a conversation_id")
        self.conversation_id = str(conversation_id)
        self.run_id = run_id
        self._drain = drain
        self._emit = emit
        self._clock = clock
        self._record_wait = record_wait or run_metrics.record_steer_wait

    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        # The inbox is read through an async Redis client; a sync run cannot read it.
        raise NotImplementedError("InboxMiddleware supports async execution only (ainvoke / astream)")

    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        drained = await self._drain(self.conversation_id)
        if not drained:
            return None
        now_ms = self._clock() * 1000
        injected: list[HumanMessage] = []
        for message in drained:
            message_id = str(message.get("message_id") or "")
            text = message.get("text")
            if isinstance(text, str) and text.strip():
                injected.append(
                    HumanMessage(
                        content=text,
                        id=f"{STEER_MESSAGE_ID_PREFIX}{message_id}" if message_id else None,
                        additional_kwargs={"source": INBOX_SOURCE, "message_id": message_id},
                    )
                )
            else:
                logger.warning(
                    "inbox message {} of conversation={} has no text; nothing is injected for it",
                    message_id,
                    self.conversation_id,
                )
            await self._mark_read(message_id, message.get("ts"), now_ms)
        logger.info(
            "run={} conversation={}: {} inbox message(s) read before the next model call",
            self.run_id,
            self.conversation_id,
            len(drained),
        )
        return {"messages": injected} if injected else None

    async def _mark_read(self, message_id: str, enqueued_ms: Any, now_ms: float) -> None:
        """Emit ``steer_read`` and record the wait. Never raises.

        The message has already left the inbox, so a failure here must not stop
        it from reaching the model.
        """
        try:
            wait_ms = max(0.0, now_ms - float(enqueued_ms)) if enqueued_ms else 0.0
            self._record_wait(wait_ms)
        except Exception:
            logger.exception("could not record the inbox wait of message {}", message_id)
        if not message_id:
            logger.warning("inbox message of conversation={} has no message_id; no steer_read", self.conversation_id)
            return
        try:
            await self._emit(
                run_events.make_event(
                    run_events.STEER_READ, run_events.SteerData(message_id=message_id), run_id=self.run_id
                )
            )
        except Exception:
            logger.exception(
                "run={} conversation={}: could not write steer_read of message {}",
                self.run_id,
                self.conversation_id,
                message_id,
            )


__all__ = ["INBOX_SOURCE", "STEER_MESSAGE_ID_PREFIX", "InboxMiddleware"]
