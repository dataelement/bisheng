"""F132 long-term memory in deep research: registration and rounds (design decisions 6, 15; R8).

Registration happens only at login-state endpoints (``register_memory_session``);
the worker never registers, it resolves the registration by the conversation's
``chat_id``. One round = one svid run on the main path (first submit, ask_user
resume continues the same round, a ``/workbench/continue`` follow-up is a new
round on the same task message row, see P-01). ``LinsightMemoryRound`` holds one
worker run's memory state: ``begin`` at round start, ``end`` once in the
``finally`` of the three worker entries. Unattended (Open API) runs never use
memory (AC-10).
"""

from __future__ import annotations

from loguru import logger

from bisheng.linsight.domain.services.unattended_run import is_unattended_run


async def register_memory_session(chat_id: str | None, login_user, timezone: str | None = None) -> None:
    """Login-state endpoints only. Registration failures never break the request."""
    if not chat_id or login_user is None:
        return
    from bisheng.memory.domain.services.gate import MemoryGate

    try:
        await MemoryGate.open(chat_id, login_user, timezone)
    except Exception:
        logger.exception("memory: registering deep-research chat {} failed", chat_id)


async def _task_message_id(session_model) -> int | None:
    """Id of the round's bot task message row (``extra.linsight_session_version_id == svid``)."""
    from bisheng.linsight.domain import utils as linsight_utils

    try:
        feedback = await linsight_utils.get_task_feedback_by_version(session_model.session_id)
    except Exception:
        logger.exception("memory: task message lookup failed svid={}", session_model.id)
        return None
    entry = feedback.get(session_model.id) or {}
    return entry.get("message_id")


class LinsightMemoryRound:
    """Memory state of one worker run of a deep-research round."""

    def __init__(self):
        self.started = False
        self.chat_id: str | None = None
        self.message_id: int | None = None
        self.ctx = None
        self.resident_text = ""
        self.experience_text = ""
        self._push = None
        self._last_signal: tuple | None = None
        self._tools: list | None = None

    # ---- round start --------------------------------------------------------------
    async def begin(self, session_model, *, follow_up: bool = False, resume: bool = False, push=None) -> None:
        """Open (or, on an ask_user resume, re-find) the round's summary row.

        ``follow_up`` marks a ``/workbench/continue`` round: its summary row is
        flagged consolidated so the round is never auto-consolidated (P-01 C).
        """
        self.__init__()
        if session_model is None or is_unattended_run(session_model):
            return
        self.started = True
        self.chat_id = session_model.session_id
        self._push = push
        self.message_id = await _task_message_id(session_model)

        from bisheng.memory.domain.ports import SCENE_LINSIGHT
        from bisheng.memory.domain.services.gate import MemoryGate

        try:
            ctx = await MemoryGate.resolve(self.chat_id, SCENE_LINSIGHT)
        except Exception:
            logger.exception("memory: resolving deep-research chat {} failed", self.chat_id)
            ctx = None
        if ctx is None:
            return
        self.ctx = ctx

        reused = False
        if resume:
            from bisheng.memory.domain.services.linsight_turns import LinsightTurnService

            turn_id = await LinsightTurnService.open_round_turn_id(ctx, self.message_id)
            if turn_id:
                ctx.turn_id = turn_id
                reused = True

        block = await self._load_texts(ctx)
        if reused:
            return
        from bisheng.memory.domain.services.resident import SCENE_CLASS_LINSIGHT
        from bisheng.memory.domain.services.turn_record import TurnRecordService

        try:
            await TurnRecordService.add_summary(
                ctx,
                block.rev if block is not None and block.text else None,
                block.day if block is not None else None,
                SCENE_CLASS_LINSIGHT,
                message_id=self.message_id,
                consolidated=follow_up,
            )
        except Exception:
            logger.exception("memory: summary row for deep-research round failed chat={}", self.chat_id)

    async def _load_texts(self, ctx):
        """Resident and experience text, fetched once per run (AC-51, AC-55). Failures are counted (AC-61)."""
        from bisheng.memory.domain.services import factory
        from bisheng.memory.domain.services import metrics as m
        from bisheng.memory.domain.services.resident import SCENE_CLASS_LINSIGHT

        resident = factory.get_resident_service()
        block = None
        try:
            block = await resident.resident(ctx, SCENE_CLASS_LINSIGHT)
            self.resident_text = block.text or ""
            experience = await resident.experience(ctx)
            self.experience_text = experience.text or ""
        except Exception:
            logger.exception("memory: injecting resident memory into deep research failed chat={}", self.chat_id)
            try:
                await factory.get_metrics().incr(ctx, m.INJECT_FAILED)
            except Exception:
                logger.exception("memory: counting an injection failure failed")
        return block

    # ---- tools and signal ---------------------------------------------------------
    def tools(self) -> list:
        """``memory_write`` / ``memory_search`` for this run; empty when memory is off."""
        if self.ctx is None:
            return []
        if self._tools is None:
            from bisheng.memory.domain.services.tools import build_memory_tools

            self._tools = build_memory_tools(self.ctx, on_write=self._on_write)
        return list(self._tools)

    def signal(self) -> dict | None:
        if self.ctx is None:
            return None
        return {
            "turn_id": self.ctx.turn_id,
            "has_write": bool(self.ctx.extra.get("memory_written")),
            "has_attribution": bool(self.resident_text) or bool(self.ctx.extra.get("memory_retrieved")),
        }

    async def push_signal(self) -> None:
        """Stream ``{turn_id, has_write, has_attribution}`` when it is new and non-empty."""
        data = self.signal()
        if not data or self._push is None or not (data["has_write"] or data["has_attribution"]):
            return
        key = (data["turn_id"], data["has_write"], data["has_attribution"])
        if key == self._last_signal:
            return
        self._last_signal = key
        try:
            await self._push(data)
        except Exception:
            logger.exception("memory: pushing the deep-research memory signal failed")

    async def _on_write(self, result) -> None:
        await self.push_signal()

    # ---- round end ----------------------------------------------------------------
    async def end(self, waiting_for_input: bool) -> None:
        """Once per worker run, from the entry's ``finally``. A parked round has not ended."""
        if not self.started or waiting_for_input:
            return
        from bisheng.memory.domain.services.activity import MemoryActivity
        from bisheng.memory.domain.services.linsight_turns import LinsightTurnService

        enabled = self.ctx is not None
        try:
            if enabled:
                await LinsightTurnService.mark_ended(self.ctx)
                await self.push_signal()
            await MemoryActivity.end_turn(self.chat_id, self.message_id, enabled)
        except Exception:
            logger.exception("memory: ending the deep-research round failed chat={}", self.chat_id)
        finally:
            self.started = False
