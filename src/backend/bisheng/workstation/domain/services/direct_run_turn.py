"""F004 T059: citations and long-term memory of ONE execution of a ``direct`` run.

A ``DirectTurn`` holds what the legacy daily-chat stream keeps in local
variables for one turn:

- the citation collector and the mirror of the conversation's numbering table
  (``linsight:cite_handles:<conversation id>``, shared with deep research, so a
  source keeps one number across direct and planned runs, AC-41);
- the converter that turns the ``[Sn]`` the model writes into the citation
  markers the frontend renders, before the text reaches the event stream;
- the memory turn (``DailyMemoryTurn``) when the conversation was registered at
  a login-state endpoint.

``rewrite`` is applied by ``DirectRunner`` to every event before it is written:
main-answer text is converted, and the input and output of the memory tools are
replaced by their content-free stand-ins (F132 decision 10).

Process memory: ``_TURNS`` maps a run id to the turn of the execution running
in THIS process, from ``open_turn`` to ``close_turn``. It lets the persistence
projector (attached by the caller of the runner, in the same process) reach the
collector and end the memory turn. It is not run state: another process rebuilds
everything from Redis (the numbering table, the citation runtime cache, the
memory turn id), and the projector binds citations from the answer text when it
has no collector.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from bisheng.citation.domain.services.citation_prompt_helper import CitationRegistryCollector
from bisheng.citation.domain.services.daily_citation_handles import HandleStreamConverter, markers_to_handles
from bisheng.citation.domain.services.daily_citation_scope import DailyCitationScope
from bisheng.linsight.domain.schemas import run_events
from bisheng.memory.domain.services.redaction import is_memory_tool, redact_tool_event
from bisheng.workstation.domain.services import daily_citation
from bisheng.workstation.domain.services.daily_memory import DailyMemoryTurn

# The memory turn id of a run, kept while the run may still be resumed (a parked
# run is kept 7 days, like the run state).
MEMORY_TURN_KEY_PREFIX = "bisheng:run:memory_turn:"
MEMORY_TURN_TTL_SECONDS = 7 * 24 * 3600


def memory_turn_key(run_id: str) -> str:
    return f"{MEMORY_TURN_KEY_PREFIX}{run_id}"


class DirectTurn:
    """Citation and memory state of one execution of a direct run."""

    def __init__(self, conversation_id: str, run_id: str):
        self.conversation_id = conversation_id
        self.run_id = run_id
        # Model id of the run (``DirectRunContext.model_id``); the audit line prints it.
        self.model: Any = None
        self.collector = CitationRegistryCollector()
        self.scope = DailyCitationScope(conversation_id)
        self.converter = HandleStreamConverter(self.scope.handles)
        self.memory: DailyMemoryTurn | None = None
        self.memory_wiring: Any = None
        self._text_event: dict | None = None
        self._text_pending = False
        self._prepared = False

    # ------------------------------------------------------------ preparation

    async def load(self) -> None:
        """Read the numbering table of the conversation. Never raises."""
        await self.scope.load()

    async def prepare(self, ctx: Any, redis: Any = None) -> None:
        """Before the tools are built: the numbering table, then the memory turn.

        ``ctx`` is the ``DirectRunContext``. Idempotent within one execution.
        """
        if self._prepared:
            return
        self._prepared = True
        if self.model is None:
            self.model = getattr(ctx, "model_id", None)
        await self.load()
        if getattr(ctx, "memory_registered", False):
            await self._start_memory(ctx, redis)

    async def _start_memory(self, ctx: Any, redis: Any) -> None:
        memory = DailyMemoryTurn(self.conversation_id)
        earlier = await self._read_turn_id(redis) if getattr(ctx, "is_resume", False) else None
        await memory.start(registered=True, actor_user_id=ctx.user_id, turn_id=earlier)
        self.memory = memory
        if not memory.enabled:
            return
        if not memory.continued:
            await self._remember_turn_id(redis, memory.ctx.turn_id)
        self.memory_wiring = memory.wiring(await memory.resident_text())

    async def _read_turn_id(self, redis: Any) -> str | None:
        if redis is None:
            return None
        try:
            value = await redis.get(memory_turn_key(self.run_id))
        except Exception:
            # The resumed execution then opens a new memory turn; the answer is not affected.
            logger.exception("memory: reading the turn id of run {} failed", self.run_id)
            return None
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        return str(value) if value else None

    async def _remember_turn_id(self, redis: Any, turn_id: str | None) -> None:
        if redis is None or not turn_id:
            return
        try:
            await redis.set(memory_turn_key(self.run_id), turn_id, ex=MEMORY_TURN_TTL_SECONDS)
        except Exception:
            # Only a resume after ask_user needs it; see ``_read_turn_id``.
            logger.exception("memory: saving the turn id of run {} failed", self.run_id)

    # ---------------------------------------------------------------- events

    def rewrite(self, event: dict) -> list[dict]:
        """The events to write in place of ``event`` (zero, one or two).

        Main-answer text goes through the handle converter, which holds back a
        tail that may still become ``[Sn]``. Any other event ends the text run:
        the held tail is written first, as one more ``text`` event.
        """
        data = event.get("data") or {}
        if event.get("type") == run_events.TEXT and not data.get("namespace"):
            self._text_event = event
            self._text_pending = True
            converted = self.converter.feed(str(data.get("text") or ""))
            return [{**event, "data": {**data, "text": converted}}] if converted else []

        out: list[dict] = []
        if self._text_pending and self._text_event is not None:
            self._text_pending = False
            tail = self.converter.flush()
            if tail:
                template = self._text_event
                out.append({**template, "data": {**(template.get("data") or {}), "text": tail}})
        if event.get("type") == run_events.TOOL_CALL and is_memory_tool(data.get("name")):
            event = {**event, "data": self._redacted_tool_call(data)}
        out.append(event)
        return out

    @staticmethod
    def _redacted_tool_call(data: dict) -> dict:
        """Same stand-in for input and output, as ``memory_turns.redact_exec_step``."""
        name = data.get("name")
        output = data.get("output")
        stand_in = redact_tool_event(name, output if output else data.get("params"))
        redacted = {**data, "params": stand_in}
        if output is not None:
            redacted["output"] = json.dumps(stand_in, ensure_ascii=False)
        return redacted

    def history_for_model(self, text: str) -> str:
        """Earlier answers as the model should read them: markers back to ``[Sn]``."""
        return markers_to_handles(text, self.scope.key_to_handle)

    # ------------------------------------------------------------ end of run

    async def finish_memory(self, message_id: int | None) -> dict | None:
        """Bind the turn's memory records to the answer row and end the turn.

        Returns the flags ``{turn_id, has_write, has_attribution}`` to signal, or
        None. ``DailyMemoryTurn.finish`` logs and swallows its own failures.
        """
        if self.memory is None:
            return None
        await self.memory.finish(message_id)
        return self.memory.final_signal()


_TURNS: dict[str, DirectTurn] = {}


def open_turn(conversation_id: str, run_id: str) -> DirectTurn:
    """The turn of the execution that starts now in this process."""
    turn = DirectTurn(conversation_id, run_id)
    _TURNS[run_id] = turn
    return turn


def close_turn(run_id: str, turn: DirectTurn | None = None) -> None:
    """Forget the turn. With ``turn`` given, only when it is still the registered one."""
    if turn is None or _TURNS.get(run_id) is turn:
        _TURNS.pop(run_id, None)


def current(run_id: str) -> DirectTurn | None:
    return _TURNS.get(run_id)


def collected_citations(run_id: str) -> list:
    """Sources the tools of the running execution registered; empty when it is not in this process."""
    turn = _TURNS.get(run_id)
    return turn.collector.list_items() if turn is not None else []


def log_citation_audit(run_id: str, cited: list) -> bool:
    """Write the ``[daily-citation-audit]`` line of the running execution.

    Same fields and format as the legacy daily chat (``daily_citation.log_citation_audit``):
    the sources the tools showed the model, the sources the answer cites, and the
    converter's counts of unknown handles and legacy markers. Called by the
    persistence projector once, when the answer row is written.

    Returns False without logging when the execution is not in this process (a
    row written by another process after the run's process died): the converter
    counts exist only where the answer was streamed.
    """
    turn = _TURNS.get(run_id)
    if turn is None:
        return False
    daily_citation.log_citation_audit(
        chat_id=turn.conversation_id,
        model=turn.model,
        scope=turn.scope,
        stats=turn.converter.stats,
        cited=cited,
    )
    return True


async def finish_memory_turn(run_id: str, message_id: int | None) -> dict | None:
    """End the memory turn of the running execution (the projector's ``on_persisted`` calls this)."""
    turn = _TURNS.get(run_id)
    if turn is None:
        return None
    return await turn.finish_memory(message_id)
