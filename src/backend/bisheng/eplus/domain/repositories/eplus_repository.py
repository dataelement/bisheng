"""Caller-owned transactional repositories for E+ robot state."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.eplus.domain.models.eplus import (
    EPlusBotConfig,
    EPlusBotSpace,
    EPlusConversation,
    EPlusInboundMessage,
    EPlusInboundStatus,
    EPlusTurn,
    EPlusTurnStatus,
)


def _require_matching_tenant(tenant_id: int | None) -> int:
    resolved = int(tenant_id or 0)
    current = get_current_tenant_id()
    if resolved <= 0 or current is None or int(current) != resolved:
        raise ValueError("E+ repository requires the matching tenant context")
    return resolved


class EPlusConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, *, tenant_id: int, bot_config_id: int) -> EPlusBotConfig | None:
        resolved_tenant_id = _require_matching_tenant(tenant_id)
        return (
            await self.session.exec(
                select(EPlusBotConfig).where(
                    EPlusBotConfig.tenant_id == resolved_tenant_id,
                    EPlusBotConfig.id == int(bot_config_id),
                )
            )
        ).first()

    async def get_by_bot_id(self, *, tenant_id: int, bot_id: str) -> EPlusBotConfig | None:
        resolved_tenant_id = _require_matching_tenant(tenant_id)
        return (
            await self.session.exec(
                select(EPlusBotConfig).where(
                    EPlusBotConfig.tenant_id == resolved_tenant_id,
                    EPlusBotConfig.bot_id == str(bot_id),
                )
            )
        ).first()

    async def get_by_assistant_id(self, *, tenant_id: int, assistant_id: str) -> EPlusBotConfig | None:
        resolved_tenant_id = _require_matching_tenant(tenant_id)
        return (
            await self.session.exec(
                select(EPlusBotConfig).where(
                    EPlusBotConfig.tenant_id == resolved_tenant_id,
                    EPlusBotConfig.assistant_id == str(assistant_id),
                )
            )
        ).first()

    async def list_space_ids(self, *, tenant_id: int, bot_config_id: int) -> list[int]:
        resolved_tenant_id = _require_matching_tenant(tenant_id)
        statement = (
            select(EPlusBotSpace.space_id)
            .where(
                EPlusBotSpace.tenant_id == resolved_tenant_id,
                EPlusBotSpace.bot_config_id == int(bot_config_id),
            )
            .order_by(EPlusBotSpace.space_id.asc())
        )
        return [int(space_id) for space_id in (await self.session.exec(statement)).all()]

    async def save(self, *, tenant_id: int, row: EPlusBotConfig) -> EPlusBotConfig:
        resolved_tenant_id = _require_matching_tenant(tenant_id)
        if row.tenant_id != resolved_tenant_id:
            raise ValueError("E+ config tenant does not match the current tenant context")
        self.session.add(row)
        await self.session.flush()
        return row

    async def replace_space_ids(
        self,
        *,
        tenant_id: int,
        bot_config_id: int,
        space_ids: tuple[int, ...],
        bound_by: int,
    ) -> None:
        resolved_tenant_id = _require_matching_tenant(tenant_id)
        await self.session.exec(
            delete(EPlusBotSpace).where(
                EPlusBotSpace.tenant_id == resolved_tenant_id,
                EPlusBotSpace.bot_config_id == int(bot_config_id),
            )
        )
        self.session.add_all(
            [
                EPlusBotSpace(
                    tenant_id=resolved_tenant_id,
                    bot_config_id=int(bot_config_id),
                    space_id=space_id,
                    bound_by=int(bound_by),
                )
                for space_id in space_ids
            ]
        )
        await self.session.flush()


class EPlusMessageRepository:
    _SOURCE_STATUSES: dict[EPlusInboundStatus, frozenset[EPlusInboundStatus]] = {
        EPlusInboundStatus.QUEUED: frozenset({EPlusInboundStatus.RECEIVED}),
        EPlusInboundStatus.PROCESSING: frozenset({EPlusInboundStatus.QUEUED}),
        EPlusInboundStatus.SUCCEEDED: frozenset({EPlusInboundStatus.PROCESSING}),
        EPlusInboundStatus.FAILED: frozenset(
            {
                EPlusInboundStatus.RECEIVED,
                EPlusInboundStatus.QUEUED,
                EPlusInboundStatus.PROCESSING,
            }
        ),
        EPlusInboundStatus.REJECTED_BUSY: frozenset({EPlusInboundStatus.RECEIVED}),
    }
    _INFLIGHT_STATUSES = (EPlusInboundStatus.QUEUED.value, EPlusInboundStatus.PROCESSING.value)
    MAX_RECOVERY_BATCH = 500

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_or_get_inbound(
        self,
        row: EPlusInboundMessage,
    ) -> tuple[EPlusInboundMessage, bool]:
        tenant_id = _require_matching_tenant(row.tenant_id)
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
            return row, True
        except IntegrityError:
            existing = (
                await self.session.exec(
                    select(EPlusInboundMessage).where(
                        EPlusInboundMessage.tenant_id == tenant_id,
                        EPlusInboundMessage.bot_id == row.bot_id,
                        EPlusInboundMessage.msgid == row.msgid,
                    )
                )
            ).first()
            if existing is None:
                raise
            return existing, False

    async def get_inbound(self, *, tenant_id: int, message_id: int) -> EPlusInboundMessage | None:
        resolved_tenant_id = _require_matching_tenant(tenant_id)
        return (
            await self.session.exec(
                select(EPlusInboundMessage).where(
                    EPlusInboundMessage.tenant_id == resolved_tenant_id,
                    EPlusInboundMessage.id == int(message_id),
                )
            )
        ).first()

    async def lock_bot_admission(self, *, tenant_id: int, bot_config_id: int) -> None:
        """Serialize the short quota/create-turn section per robot."""
        resolved_tenant_id = _require_matching_tenant(tenant_id)
        statement = select(EPlusBotConfig.id).where(
            EPlusBotConfig.tenant_id == resolved_tenant_id,
            EPlusBotConfig.id == int(bot_config_id),
        )
        if self.session.get_bind().dialect.name != "sqlite":
            statement = statement.with_for_update()
        if (await self.session.exec(statement)).first() is None:
            raise LookupError(f"E+ bot config not found: {bot_config_id}")

    async def link_to_turn(
        self,
        *,
        tenant_id: int,
        message: EPlusInboundMessage,
        conversation_id: str,
        turn_id: str,
        sender_user_id: int,
    ) -> None:
        resolved_tenant_id = _require_matching_tenant(tenant_id)
        if message.tenant_id != resolved_tenant_id:
            raise ValueError("E+ inbound tenant does not match the current tenant context")
        message.conversation_id = str(conversation_id)
        message.turn_id = str(turn_id)
        message.sender_user_id = int(sender_user_id)
        self.session.add(message)
        await self.session.flush()

    async def transition(
        self,
        *,
        tenant_id: int,
        message_id: int | None,
        target: EPlusInboundStatus | str,
        error_code: str | None = None,
    ) -> bool:
        resolved_tenant_id = _require_matching_tenant(tenant_id)
        if message_id is None:
            raise ValueError("message_id must be persisted before a state transition")
        target_status = EPlusInboundStatus(target)
        source_statuses = self._SOURCE_STATUSES.get(target_status)
        if not source_statuses:
            raise ValueError(f"unsupported E+ inbound transition target: {target_status.value}")

        values: dict[str, object] = {"status": target_status.value}
        now = datetime.now()
        if target_status == EPlusInboundStatus.PROCESSING:
            values["started_at"] = now
        if target_status in {
            EPlusInboundStatus.SUCCEEDED,
            EPlusInboundStatus.FAILED,
            EPlusInboundStatus.REJECTED_BUSY,
        }:
            values["finished_at"] = now
        if error_code is not None:
            values["error_code"] = error_code

        statement = (
            update(EPlusInboundMessage)
            .where(
                EPlusInboundMessage.tenant_id == resolved_tenant_id,
                EPlusInboundMessage.id == int(message_id),
                col(EPlusInboundMessage.status).in_(status.value for status in source_statuses),
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        result = await self.session.exec(statement)
        if result.rowcount:
            await self.session.flush()
            return True
        return False

    async def count_inflight(
        self,
        *,
        tenant_id: int,
        bot_id: str,
        sender_external_id: str,
    ) -> int:
        resolved_tenant_id = _require_matching_tenant(tenant_id)
        statement = (
            select(func.count())
            .select_from(EPlusInboundMessage)
            .where(
                EPlusInboundMessage.tenant_id == resolved_tenant_id,
                EPlusInboundMessage.bot_id == str(bot_id),
                EPlusInboundMessage.sender_external_id == str(sender_external_id),
                col(EPlusInboundMessage.status).in_(self._INFLIGHT_STATUSES),
            )
        )
        return int((await self.session.exec(statement)).one())

    async def list_recoverable_queued(
        self,
        *,
        tenant_id: int,
        bot_config_id: int,
        limit: int = 100,
    ) -> list[EPlusInboundMessage]:
        resolved_tenant_id = _require_matching_tenant(tenant_id)
        bounded_limit = max(1, min(int(limit), self.MAX_RECOVERY_BATCH))
        statement = (
            select(EPlusInboundMessage)
            .where(
                EPlusInboundMessage.tenant_id == resolved_tenant_id,
                EPlusInboundMessage.bot_config_id == int(bot_config_id),
                EPlusInboundMessage.status == EPlusInboundStatus.QUEUED.value,
            )
            .order_by(EPlusInboundMessage.received_at.asc(), EPlusInboundMessage.id.asc())
            .limit(bounded_limit)
        )
        return list((await self.session.exec(statement)).all())


class EPlusConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create(
        self,
        *,
        tenant_id: int,
        conversation: EPlusConversation,
    ) -> EPlusConversation:
        resolved_tenant_id = _require_matching_tenant(tenant_id)
        if conversation.tenant_id != resolved_tenant_id:
            raise ValueError("E+ conversation tenant does not match the current tenant context")
        statement = select(EPlusConversation).where(
            EPlusConversation.tenant_id == resolved_tenant_id,
            EPlusConversation.bot_config_id == int(conversation.bot_config_id),
            EPlusConversation.chat_type == conversation.chat_type,
            EPlusConversation.conversation_key == conversation.conversation_key,
        )
        existing = (await self.session.exec(statement)).first()
        if existing is None:
            try:
                async with self.session.begin_nested():
                    self.session.add(conversation)
                    await self.session.flush()
                return conversation
            except IntegrityError:
                existing = (await self.session.exec(statement)).first()
                if existing is None:
                    raise
        if int(existing.scope_version) != int(conversation.scope_version):
            existing.scope_version = int(conversation.scope_version)
            self.session.add(existing)
            await self.session.flush()
        return existing

    async def save_turn(self, *, tenant_id: int, turn: EPlusTurn) -> EPlusTurn:
        resolved_tenant_id = _require_matching_tenant(tenant_id)
        if turn.tenant_id != resolved_tenant_id:
            raise ValueError("E+ turn tenant does not match the current tenant context")
        self.session.add(turn)
        await self.session.flush()
        return turn

    async def claim_next_turn(self, *, tenant_id: int, conversation_id: str) -> EPlusTurn | None:
        resolved_tenant_id = _require_matching_tenant(tenant_id)
        running = (
            await self.session.exec(
                select(func.count())
                .select_from(EPlusTurn)
                .where(
                    EPlusTurn.tenant_id == resolved_tenant_id,
                    EPlusTurn.conversation_id == str(conversation_id),
                    EPlusTurn.status == EPlusTurnStatus.RUNNING.value,
                )
            )
        ).one()
        if int(running):
            return None

        statement = (
            select(EPlusTurn)
            .where(
                EPlusTurn.tenant_id == resolved_tenant_id,
                EPlusTurn.conversation_id == str(conversation_id),
                EPlusTurn.status == EPlusTurnStatus.QUEUED.value,
            )
            .order_by(EPlusTurn.turn_seq.asc())
            .limit(1)
        )
        if self.session.get_bind().dialect.name != "sqlite":
            statement = statement.with_for_update(skip_locked=True)
        turn = (await self.session.exec(statement)).first()
        if turn is None:
            return None
        result = await self.session.exec(
            update(EPlusTurn)
            .where(
                EPlusTurn.tenant_id == resolved_tenant_id,
                EPlusTurn.id == turn.id,
                EPlusTurn.status == EPlusTurnStatus.QUEUED.value,
            )
            .values(status=EPlusTurnStatus.RUNNING.value, started_at=datetime.now())
            .execution_options(synchronize_session=False)
        )
        if not result.rowcount:
            return None
        await self.session.flush()
        await self.session.refresh(turn)
        transitioned = await EPlusMessageRepository(self.session).transition(
            tenant_id=resolved_tenant_id,
            message_id=turn.inbound_message_id,
            target=EPlusInboundStatus.PROCESSING,
        )
        if not transitioned:
            raise RuntimeError("E+ claimed turn has no matching queued inbound message")
        return turn

    async def list_history(
        self,
        *,
        tenant_id: int,
        conversation_id: str,
        before_sequence: int,
    ) -> list[EPlusTurn]:
        resolved_tenant_id = _require_matching_tenant(tenant_id)
        statement = (
            select(EPlusTurn)
            .where(
                EPlusTurn.tenant_id == resolved_tenant_id,
                EPlusTurn.conversation_id == str(conversation_id),
                EPlusTurn.turn_seq < int(before_sequence),
                EPlusTurn.status == EPlusTurnStatus.SUCCEEDED.value,
            )
            .order_by(EPlusTurn.turn_seq.asc())
        )
        return list((await self.session.exec(statement)).all())

    async def complete_turn(
        self,
        *,
        tenant_id: int,
        turn_id: str,
        succeeded: bool,
        answer_text: str | None,
        error_code: str | None,
    ) -> EPlusTurn | None:
        resolved_tenant_id = _require_matching_tenant(tenant_id)
        turn = (
            await self.session.exec(
                select(EPlusTurn).where(
                    EPlusTurn.tenant_id == resolved_tenant_id,
                    EPlusTurn.id == str(turn_id),
                    EPlusTurn.status == EPlusTurnStatus.RUNNING.value,
                )
            )
        ).first()
        if turn is None:
            return None
        turn.status = EPlusTurnStatus.SUCCEEDED.value if succeeded else EPlusTurnStatus.FAILED.value
        turn.answer_text = answer_text
        turn.error_code = error_code
        turn.finished_at = datetime.now()
        self.session.add(turn)
        await self.session.flush()
        inbound_target = EPlusInboundStatus.SUCCEEDED if succeeded else EPlusInboundStatus.FAILED
        transitioned = await EPlusMessageRepository(self.session).transition(
            tenant_id=resolved_tenant_id,
            message_id=turn.inbound_message_id,
            target=inbound_target,
            error_code=error_code,
        )
        if not transitioned:
            raise RuntimeError("E+ completed turn has no matching processing inbound message")
        return turn

    async def recover_bot_turns(self, *, tenant_id: int, bot_config_id: int) -> tuple[str, ...]:
        resolved_tenant_id = _require_matching_tenant(tenant_id)
        running_statement = (
            select(EPlusTurn)
            .join(EPlusConversation, EPlusConversation.id == EPlusTurn.conversation_id)
            .where(
                EPlusTurn.tenant_id == resolved_tenant_id,
                EPlusConversation.tenant_id == resolved_tenant_id,
                EPlusConversation.bot_config_id == int(bot_config_id),
                EPlusTurn.status == EPlusTurnStatus.RUNNING.value,
            )
        )
        running_turns = list((await self.session.exec(running_statement)).all())
        for turn in running_turns:
            turn.status = EPlusTurnStatus.FAILED.value
            turn.error_code = "WORKER_INTERRUPTED"
            turn.finished_at = datetime.now()
            self.session.add(turn)
            transitioned = await EPlusMessageRepository(self.session).transition(
                tenant_id=resolved_tenant_id,
                message_id=turn.inbound_message_id,
                target=EPlusInboundStatus.FAILED,
                error_code="WORKER_INTERRUPTED",
            )
            if not transitioned:
                raise RuntimeError("E+ recovery found a running turn without a processing inbound message")

        queued_statement = (
            select(EPlusTurn.conversation_id)
            .distinct()
            .join(EPlusConversation, EPlusConversation.id == EPlusTurn.conversation_id)
            .where(
                EPlusTurn.tenant_id == resolved_tenant_id,
                EPlusConversation.tenant_id == resolved_tenant_id,
                EPlusConversation.bot_config_id == int(bot_config_id),
                EPlusTurn.status == EPlusTurnStatus.QUEUED.value,
            )
            .order_by(EPlusTurn.conversation_id.asc())
        )
        conversation_ids = tuple(str(value) for value in (await self.session.exec(queued_statement)).all())
        await self.session.flush()
        return conversation_ids

    async def allocate_next_sequence(self, *, tenant_id: int, conversation_id: str) -> int:
        resolved_tenant_id = _require_matching_tenant(tenant_id)
        statement = select(EPlusConversation).where(
            EPlusConversation.tenant_id == resolved_tenant_id,
            EPlusConversation.id == str(conversation_id),
        )
        if self.session.get_bind().dialect.name != "sqlite":
            statement = statement.with_for_update()
        conversation = (await self.session.exec(statement)).first()
        if conversation is None:
            raise LookupError(f"E+ conversation not found: {conversation_id}")
        sequence = int(conversation.next_turn_seq)
        conversation.next_turn_seq = sequence + 1
        self.session.add(conversation)
        await self.session.flush()
        return sequence
