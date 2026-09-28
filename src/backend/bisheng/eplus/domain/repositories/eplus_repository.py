"""Caller-owned transactional repositories for E+ robot state."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, update
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
