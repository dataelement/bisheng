"""Long-term memory in daily mode (F132 Wave 8, design decisions 6, 10, 11, 15).

The daily-mode stream asks this module three things per turn: whether memory
is on, what to add to the system prompt and the tool list, and what to do with
memory tool events and the turn's end. Every memory failure is logged and
swallowed here, so the answer always completes (AC-61).

Eligibility: only a login-state endpoint passes ``memory_register`` (a callable
that runs ``MemoryGate.open``). The open-API entry calls the same service
function without it, and then this module never resolves a memory context,
even for a conversation that a login-state turn registered earlier (AC-10).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from loguru import logger

from bisheng.memory.domain.ports import SCENE_DAILY, MemoryContext
from bisheng.memory.domain.services import metrics as m
from bisheng.memory.domain.services.activity import MemoryActivity
from bisheng.memory.domain.services.factory import get_metrics, get_resident_service
from bisheng.memory.domain.services.gate import MemoryGate
from bisheng.memory.domain.services.redaction import is_memory_tool, redact_tool_event, split_reserved_tools
from bisheng.memory.domain.services.resident import SCENE_CLASS_CHAT, ResidentBlock
from bisheng.memory.domain.services.tools import build_memory_tools
from bisheng.memory.domain.services.turn_record import TurnRecordService

MemoryRegister = Callable[[str], Awaitable[None]]

MEMORY_TOOL_ERROR = "记忆操作失败"


async def register_session(memory_register: MemoryRegister | None, chat_id: str | None) -> None:
    """Run the endpoint-injected registration; a failure only disables memory for the turn."""
    if memory_register is None or not chat_id:
        return
    try:
        await memory_register(chat_id)
    except Exception:
        logger.exception("memory: registering daily chat {} failed", chat_id)


def with_resident(sys_prompt: str | None, resident_text: str) -> str | None:
    """Append the resident block after the system prompt (it is background, not instructions)."""
    if not resident_text:
        return sys_prompt
    return f"{sys_prompt}\n\n{resident_text}" if sys_prompt else resident_text


# ---- tool event redaction (decision 10): by tool name, whatever the turn's state ----
def redact_args(tool_name: str | None, args):
    return redact_tool_event(tool_name, args) if is_memory_tool(tool_name) else args


def redact_results(tool_name: str | None, raw_output, parse: Callable):
    """``parse`` is the normal result parser, used for every non-memory tool."""
    if is_memory_tool(tool_name):
        return redact_tool_event(tool_name, raw_output)
    return parse(raw_output, tool_name)


def redact_error(tool_name: str | None, error: str | None) -> str | None:
    """Error texts of memory tools may echo the arguments; replace them with a fixed text."""
    if error is not None and is_memory_tool(tool_name):
        return MEMORY_TOOL_ERROR
    return error


class DailyMemoryTurn:
    """Memory state of one daily-mode turn; disabled unless ``start`` resolves a context."""

    def __init__(self, chat_id: str):
        self.chat_id = chat_id
        self.ctx: MemoryContext | None = None
        self.block: ResidentBlock | None = None
        # True on the login-state path (the endpoint passed memory_register).
        self.registered = False
        self._last_signal: dict | None = None

    @property
    def enabled(self) -> bool:
        return self.ctx is not None

    async def start(self, registered: bool, actor_user_id: int | None = None) -> None:
        """Enablement check and a fresh ``turn_id`` (only on the login-state path).

        ``actor_user_id`` is the logged-in user of this request: a chat registered
        to someone else never resolves for them, even if they know its chat_id.
        """
        self.registered = registered
        if not registered:
            return
        try:
            self.ctx = await MemoryGate.resolve(self.chat_id, SCENE_DAILY, actor_user_id=actor_user_id)
        except Exception:
            logger.exception("memory: resolving daily chat {} failed", self.chat_id)
            self.ctx = None

    async def _count_failure(self, metric: str) -> None:
        try:
            await get_metrics().incr(self.ctx, metric)
        except Exception:
            logger.exception("memory: counting {} failed", metric)

    async def resident_text(self) -> str:
        """Resident block for this turn, and the turn's summary row (decision 15)."""
        if not self.enabled:
            return ""
        try:
            self.block = await get_resident_service().resident(self.ctx, SCENE_CLASS_CHAT)
        except Exception:
            logger.exception("memory: resident injection failed for chat {}", self.chat_id)
            self.block = None
            await self._count_failure(m.INJECT_FAILED)
        injected = self.block is not None and bool(self.block.text)
        try:
            await TurnRecordService.add_summary(
                self.ctx,
                self.block.rev if injected else None,
                self.block.day if injected else None,
                SCENE_CLASS_CHAT,
            )
        except Exception:
            logger.exception("memory: writing the turn summary failed for chat {}", self.chat_id)
        return self.block.text if injected else ""

    def tools(self, tools: list) -> list:
        """The turn's tool list plus the two memory tools; ``memory_`` names are reserved."""
        if not self.enabled:
            return tools
        try:
            memory_tools = build_memory_tools(self.ctx)
        except Exception:
            logger.exception("memory: building memory tools failed for chat {}", self.chat_id)
            return tools
        kept, _dropped = split_reserved_tools(tools)
        return [*kept, *memory_tools]

    # ---- stream signal (decision 15): flags only, never item text --------------------
    @property
    def has_write(self) -> bool:
        return bool(self.ctx and self.ctx.extra.get("memory_written"))

    @property
    def has_attribution(self) -> bool:
        """This turn injected a non-empty resident block or retrieved items."""
        if not self.ctx:
            return False
        return bool(self.block and self.block.text) or bool(self.ctx.extra.get("memory_retrieved"))

    def _flags(self) -> dict:
        return {"turn_id": self.ctx.turn_id, "has_write": self.has_write, "has_attribution": self.has_attribution}

    def pending_signal(self) -> dict | None:
        """Flags to stream now: set, and changed since the last signal; otherwise None."""
        if not self.enabled or not (self.has_write or self.has_attribution):
            return None
        flags = self._flags()
        if flags == self._last_signal:
            return None
        self._last_signal = flags
        return flags

    def final_signal(self) -> dict | None:
        """Flags sent once more just before the answer ends, alongside the answer's message id."""
        if not self.enabled or not (self.has_write or self.has_attribution):
            return None
        self._last_signal = self._flags()
        return self._last_signal

    # ---- end of turn (decisions 7 and 15) ---------------------------------------------
    async def finish(self, message_id: int | None) -> None:
        """Bind the turn's records to the answer row and record the end of the turn.

        Only the login-state path touches the session row; a disabled turn there
        advances the watermark past itself (AC-41).
        """
        if not self.registered:
            return
        try:
            if self.enabled:
                await TurnRecordService.bind_turn(self.ctx, message_id)
            await MemoryActivity.end_turn(self.chat_id, message_id, self.enabled)
        except Exception:
            logger.exception("memory: ending daily turn failed for chat {}", self.chat_id)

    def finish_sync(self, message_id: int | None) -> None:
        """Interrupt path: the task is being cancelled, so no ``await`` (design pitfall 24)."""
        if not self.registered:
            return
        try:
            if self.enabled:
                TurnRecordService.bind_turn_sync(self.ctx, message_id)
            MemoryActivity.end_turn_sync(self.chat_id, message_id, self.enabled)
        except Exception:
            logger.exception("memory: ending interrupted daily turn failed for chat {}", self.chat_id)
