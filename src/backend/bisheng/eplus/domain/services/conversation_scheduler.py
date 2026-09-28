"""SQL-backed per-conversation scheduling for E+ turns."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.eplus.domain.models.eplus import EPlusTurn
from bisheng.eplus.domain.repositories.eplus_repository import EPlusConversationRepository


@dataclass(frozen=True, slots=True)
class EPlusHistoryTurn:
    turn_id: str
    turn_seq: int
    sender_user_id: int
    sender_external_id: str
    user_text: str | None
    content_manifest: tuple[dict, ...]
    answer_text: str


@dataclass(frozen=True, slots=True)
class ReadyEPlusTurn:
    turn: EPlusTurn
    history: tuple[EPlusHistoryTurn, ...]


class EPlusConversationScheduler:
    """Use process-local events only as wakeups; SQL remains queue truth."""

    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._events: dict[tuple[int, str], asyncio.Event] = {}

    async def next_ready_turn(
        self,
        tenant_id: int,
        conversation_id: str,
    ) -> ReadyEPlusTurn | None:
        async with self._session_factory() as session, session.begin():
            repository = EPlusConversationRepository(session)
            turn = await repository.claim_next_turn(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
            )
            if turn is None:
                return None
            history = await repository.list_history(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                before_sequence=turn.turn_seq,
            )
            return ReadyEPlusTurn(
                turn=turn,
                history=tuple(_history_item(item) for item in history),
            )

    async def complete_and_wake_next(
        self,
        *,
        tenant_id: int,
        turn_id: str,
        succeeded: bool,
        answer_text: str | None = None,
        error_code: str | None = None,
    ) -> ReadyEPlusTurn | None:
        async with self._session_factory() as session, session.begin():
            completed = await EPlusConversationRepository(session).complete_turn(
                tenant_id=tenant_id,
                turn_id=turn_id,
                succeeded=succeeded,
                answer_text=answer_text,
                error_code=error_code,
            )
            if completed is None:
                return None
            conversation_id = completed.conversation_id

        self.wake(tenant_id, conversation_id)
        return await self.next_ready_turn(tenant_id, conversation_id)

    async def recover_queued(self, *, tenant_id: int, bot_config_id: int) -> tuple[str, ...]:
        async with self._session_factory() as session, session.begin():
            conversation_ids = await EPlusConversationRepository(session).recover_bot_turns(
                tenant_id=tenant_id,
                bot_config_id=bot_config_id,
            )
        for conversation_id in conversation_ids:
            self.wake(tenant_id, conversation_id)
        return conversation_ids

    def wake(self, tenant_id: int, conversation_id: str) -> None:
        self._event(tenant_id, conversation_id).set()

    async def wait_for_ready(self, tenant_id: int, conversation_id: str) -> None:
        event = self._event(tenant_id, conversation_id)
        await event.wait()
        event.clear()

    def _event(self, tenant_id: int, conversation_id: str) -> asyncio.Event:
        key = (int(tenant_id), str(conversation_id))
        event = self._events.get(key)
        if event is None:
            event = asyncio.Event()
            self._events[key] = event
        return event


def _history_item(turn: EPlusTurn) -> EPlusHistoryTurn:
    return EPlusHistoryTurn(
        turn_id=turn.id,
        turn_seq=int(turn.turn_seq),
        sender_user_id=int(turn.sender_user_id),
        sender_external_id=turn.sender_external_id,
        user_text=turn.user_text,
        content_manifest=tuple(turn.content_manifest or []),
        answer_text=turn.answer_text or "",
    )
